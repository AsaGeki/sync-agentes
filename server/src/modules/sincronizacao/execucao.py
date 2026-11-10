"""Prévia e execução da sincronização de uma pessoa, em segundo plano, com histórico em `sync_runs`.

Cada pessoa sincroniza o que é dela (ver `tasks_da_pessoa`). Duas credenciais, com papéis diferentes:
a de serviço (do .env, administradora do sistema) importa o que é novo, e o token pessoal da pessoa, se ela
tiver um, assina as edições e mudanças de status nas tasks que são dela. Os tokens vivem só na memória da
execução; quem rodou e quais credenciais valeram ficam no `resumo`.
"""

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any

from src.modules.sincronizacao import repositorio, service
from src.modules.sincronizacao.destino import ClienteDestino, aplicar_plano, conferir_autoria, planejar, resumo_plano
from src.modules.sincronizacao.pacote import (
    gerar_patch_replyto,
    montar_pacote,
    tasks_da_pessoa,
    tasks_donas,
    uuid_da_task,
)
from src.shared import config
from src.shared.db import conectar, now
from src.shared.erros import Conflict, Invalid, NotFound

log = logging.getLogger("sync_agents.sincronizacao")
TIMEOUT_IMPORTACAO = 900


def hash_config(conn: sqlite3.Connection, projeto: sqlite3.Row, pessoa_id: int) -> str:
    """Identifica a configuração e a pessoa; uma prévia só libera a execução se nada disso mudou."""
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    dados = {
        "pessoa": pessoa_id,
        "destino": vinculo["destino_id"] if vinculo else None,
        "padrao": vinculo["repo_padrao"] if vinculo else None,
        "repos": sorted(repositorio.vinculos_repos(conn, projeto["id"]).items()),
        "tasks": sorted(repositorio.escolhas_tasks(conn, projeto["id"]).items()),
    }
    return hashlib.sha256(json.dumps(dados, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def escopo_da_pessoa(conn: sqlite3.Connection, projeto: sqlite3.Row, pessoa_id: int) -> dict[str, int]:
    proprias, escopo = tasks_da_pessoa(conn, projeto["id"], pessoa_id)
    return {"proprias": len(proprias), "por_dependencia": len(escopo) - len(proprias)}


def _run(linha: sqlite3.Row) -> dict[str, Any]:
    resumo = json.loads(linha["resumo"] or "{}")
    terminada = linha["terminada_em"]
    segundos = None
    if terminada:
        segundos = (datetime.fromisoformat(terminada) - datetime.fromisoformat(linha["iniciada_em"])).total_seconds()
    return {
        "id": linha["id"],
        "modo": linha["modo"],
        "status": linha["status"],
        "iniciada_em": linha["iniciada_em"],
        "terminada_em": terminada,
        "segundos": segundos,
        "resumo": resumo,
    }


def listar(conn: sqlite3.Connection, project_id: int, pessoa_id: int, limite: int = 20) -> list[dict[str, Any]]:
    linhas = conn.execute(
        """SELECT * FROM sync_runs
            WHERE project_id = ? AND json_extract(resumo, '$.pessoa') = ?
            ORDER BY id DESC LIMIT ?""",
        (project_id, pessoa_id, limite),
    ).fetchall()
    return [_run(linha) for linha in linhas]


def obter(conn: sqlite3.Connection, project_id: int, pessoa_id: int, run_id: int) -> dict[str, Any]:
    linha = conn.execute(
        "SELECT * FROM sync_runs WHERE id = ? AND project_id = ? AND json_extract(resumo, '$.pessoa') = ?",
        (run_id, project_id, pessoa_id),
    ).fetchone()
    if linha is None:
        raise NotFound("Execução não encontrada.")
    return _run(linha)


def previa_vigente(conn: sqlite3.Connection, projeto: sqlite3.Row, pessoa_id: int) -> dict[str, Any] | None:
    """A última prévia concluída da pessoa, se foi feita com a configuração de hoje."""
    linha = conn.execute(
        """SELECT * FROM sync_runs
            WHERE project_id = ? AND modo = 'previa' AND status = 'ok' AND json_extract(resumo, '$.pessoa') = ?
            ORDER BY id DESC LIMIT 1""",
        (projeto["id"], pessoa_id),
    ).fetchone()
    if linha is None:
        return None
    run = _run(linha)
    return run if run["resumo"].get("config") == hash_config(conn, projeto, pessoa_id) else None


def em_andamento(conn: sqlite3.Connection, project_id: int) -> str | None:
    """Quem está com uma execução rodando neste projeto, se houver (só uma por vez)."""
    linha = conn.execute(
        "SELECT json_extract(resumo, '$.pessoa_nome') AS quem FROM sync_runs "
        "WHERE project_id = ? AND status = 'rodando'",
        (project_id,),
    ).fetchone()
    return (linha["quem"] or "outra pessoa") if linha else None


def _gravar(conn: sqlite3.Connection, run_id: int, resumo: dict[str, Any], status: str | None = None) -> None:
    texto = json.dumps(resumo, ensure_ascii=False)
    with conn:
        if status is None:
            conn.execute("UPDATE sync_runs SET resumo = ? WHERE id = ?", (texto, run_id))
        else:
            conn.execute(
                "UPDATE sync_runs SET resumo = ?, status = ?, terminada_em = ? WHERE id = ?",
                (texto, status, now(), run_id),
            )


def iniciar(conn: sqlite3.Connection, projeto: sqlite3.Row, modo: str, pessoa: sqlite3.Row, token: str | None) -> int:
    if modo not in ("previa", "aplicar"):
        raise Invalid("Modo inválido.")
    servico = config.DESTINO_TOKEN
    if not (token or servico):
        raise Invalid(
            "Informe o seu token do destino, ou peça ao administrador para configurar a credencial de serviço."
        )
    credenciais = {"importacao": "servico" if servico else "pessoal", "edicao": "pessoal" if token else "servico"}
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    if vinculo is None:
        raise Invalid("Este projeto ainda não foi vinculado a um projeto do destino. Peça ao administrador.")
    if not service.conexao()["tem_url"]:
        raise Invalid("O endereço do destino não está configurado no servidor.")
    if not tasks_da_pessoa(conn, projeto["id"], pessoa["id"])[0]:
        raise Invalid("Você não participa de nenhuma task deste projeto.")
    if modo == "aplicar" and previa_vigente(conn, projeto, pessoa["id"]) is None:
        raise Invalid("Gere uma prévia com a configuração atual antes de sincronizar.")
    conn.execute("BEGIN IMMEDIATE")
    try:
        andamento = conn.execute(
            "SELECT json_extract(resumo, '$.pessoa_nome') AS quem FROM sync_runs "
            "WHERE project_id = ? AND status = 'rodando'",
            (projeto["id"],),
        ).fetchone()
        if andamento:
            raise Conflict(
                f"Já existe uma execução em andamento neste projeto (de {andamento['quem'] or 'outra pessoa'})."
            )
        resumo = {
            "pessoa": pessoa["id"],
            "pessoa_nome": pessoa["name"],
            "credenciais": credenciais,
            "config": hash_config(conn, projeto, pessoa["id"]),
            "etapa": "Na fila",
        }
        run_id = conn.execute(
            "INSERT INTO sync_runs (project_id, modo, status, resumo, iniciada_em) VALUES (?,?,?,?,?)",
            (projeto["id"], modo, "rodando", json.dumps(resumo, ensure_ascii=False), now()),
        ).lastrowid
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    threading.Thread(
        target=_executar, args=(run_id, projeto["id"], modo, pessoa["id"], token, credenciais), daemon=True
    ).start()
    return int(run_id)


def _executar(
    run_id: int, project_id: int, modo: str, pessoa_id: int, token_pessoal: str | None, credenciais: dict[str, str]
) -> None:
    conn = conectar()
    resumo: dict[str, Any] = {}
    try:
        projeto = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        vinculo = repositorio.find_projeto(conn, project_id)
        pessoa = conn.execute("SELECT id, name, email FROM people WHERE id = ?", (pessoa_id,)).fetchone()
        resumo = {
            "pessoa": pessoa_id,
            "pessoa_nome": pessoa["name"],
            "credenciais": credenciais,
            # Em nome de quem as mudanças em tasks existentes devem aparecer, se o token for do dono esperado.
            "esperado": pessoa["email"] if credenciais["edicao"] == "pessoal" else config.DESTINO_USUARIO_SERVICO,
            "config": hash_config(conn, projeto, pessoa_id),
        }

        def etapa(texto: str) -> None:
            resumo["etapa"] = texto
            _gravar(conn, run_id, resumo)

        # A de serviço (administradora) lê e importa; a pessoa, se tiver token, assina as edições.
        token_importacao = config.DESTINO_TOKEN or token_pessoal
        token_edicao = token_pessoal or config.DESTINO_TOKEN
        etapa("Lendo o projeto no destino")
        destino = next(
            (d for d in service.projetos_destino(token_importacao) if d["_id"] == vinculo["destino_id"]), None
        )
        if destino is None:
            raise Invalid("O projeto vinculado não existe mais no destino, ou o seu token não enxerga esse projeto.")
        proprias, escopo = tasks_da_pessoa(conn, project_id, pessoa_id)
        donas = tasks_donas(conn, project_id, pessoa_id)
        editaveis = {uuid_da_task(projeto, task_id) for task_id in donas}
        resumo["escopo"] = {
            "proprias": len(proprias),
            "por_dependencia": len(escopo) - len(proprias),
            "donas": len(donas & escopo),
        }
        etapa("Montando o pacote")
        pacote, relatorio = montar_pacote(
            conn,
            projeto,
            destino,
            repositorio.vinculos_repos(conn, project_id),
            vinculo["repo_padrao"],
            repositorio.escolhas_tasks(conn, project_id),
            escopo,
        )
        resumo["pacote"] = {
            k: relatorio[k]
            for k in ("repositorio_das_tasks", "perguntas", "respostas_vinculadas", "areas_acrescentadas", "contagens")
        }
        cliente = ClienteDestino(config.DESTINO_URL, token_importacao)
        cliente_edicao = ClienteDestino(config.DESTINO_URL, token_edicao)
        etapa("Comparando com o destino")
        tasks = cliente.listar("task", projectId=destino["_id"])
        resumo["plano"] = resumo_plano(planejar(pacote, tasks, editaveis))
        if modo == "aplicar":
            etapa("Importando no destino")
            importacao = cliente.post("/admin/projects/import", pacote, timeout=TIMEOUT_IMPORTACAO)
            resumo["importacao"] = {
                k: importacao.get(k) for k in ("alreadyImported", "importedCounts", "skippedCounts", "warnings")
            }
            etapa("Aplicando as mudanças nas tasks existentes")
            tasks = cliente.listar("task", projectId=destino["_id"])
            aplicacao = aplicar_plano(cliente_edicao, destino["_id"], planejar(pacote, tasks, editaveis), tasks)
            alteradas = aplicacao.pop("alteradas")
            etapa("Conferindo quem o destino registrou como autor")
            try:
                aplicacao["autoria"] = conferir_autoria(cliente, destino["_id"], alteradas)
            except Exception:
                log.exception("Não consegui conferir a autoria da execução %s", run_id)
                aplicacao["autoria"] = {"erro": "Não consegui conferir quem o destino registrou como autor."}
            resumo["aplicacao"] = aplicacao
        resumo.pop("etapa", None)
        _gravar(conn, run_id, resumo, "ok")
    except Exception as erro:
        log.exception("Sincronização %s falhou", run_id)
        resumo.pop("etapa", None)
        resumo["erro"] = _mensagem(erro, credenciais["importacao"])
        _gravar(conn, run_id, resumo, "erro")
    finally:
        conn.close()


def _mensagem(erro: Exception, credencial: str) -> str:
    texto = str(erro) or erro.__class__.__name__
    if "System administrator required" in texto:
        quem = "o seu token" if credencial == "pessoal" else "a credencial de serviço do servidor"
        return (
            f"O destino recusou a importação: {quem} precisa ser de administrador do sistema "
            "(administrador só do projeto não basta)."
        )
    return texto


def encerrar_interrompidas() -> None:
    """Execução que ficou 'rodando' quando o servidor caiu não vai terminar nunca."""
    conn = conectar()
    try:
        with conn:
            conn.execute(
                """UPDATE sync_runs
                      SET status = 'erro', terminada_em = ?,
                          resumo = json_set(COALESCE(resumo, '{}'), '$.erro', 'Interrompida: o servidor reiniciou.')
                    WHERE status = 'rodando'""",
                (now(),),
            )
    finally:
        conn.close()


def patch_replyto(conn: sqlite3.Connection, projeto: sqlite3.Row) -> tuple[str, int]:
    """Script mongosh que preenche replyTo nas mensagens do projeto que já foram importadas sem ele.

    É uma ação de administração (precisa do token do .env e de acesso ao banco do destino) e cobre o
    projeto inteiro.
    """
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    if vinculo is None:
        raise Invalid("Vincule o projeto a um projeto do destino antes.")
    destino = next((d for d in service.projetos_destino() if d["_id"] == vinculo["destino_id"]), None)
    if destino is None:
        raise Invalid("O projeto vinculado não existe mais no destino.")
    pacote, _ = montar_pacote(
        conn,
        projeto,
        destino,
        repositorio.vinculos_repos(conn, projeto["id"]),
        vinculo["repo_padrao"],
        repositorio.escolhas_tasks(conn, projeto["id"]),
    )
    return gerar_patch_replyto([pacote])
