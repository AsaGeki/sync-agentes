"""Camada MCP do sync-agentes: mesmo contrato de `app/*/routes.py`, exposto
como tools em vez de rotas REST. Cada tool reaproveita as mesmas funcoes de
`service.py`/modelos Pydantic que a rota REST equivalente usa - a "cola" de
orquestracao (INSERT, registrar_evento, publicar) e replicada por tool porque
ja e assim que cada rota REST se organiza hoje (nada foi extraido pra
service.py alem do que ja existia).

Servidor compartilhado (1 processo, N IAs): quem fixa Authorization/X-Autor-Id
e cada cliente MCP na hora de registrar (`claude mcp add ... --header`), nao
o servidor - a autenticacao acontece por chamada, lendo os mesmos headers que
o REST le via `Header()` do FastAPI (ver `app/auth.py`).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from app.auth import resolver_autor, validar_token
from app.autores.models import AutorIn
from app.db import agora, conectar
from app.enums import EKindEvento, EStatusProjeto, EStatusTask, ETipoAutor, ETipoMensagem
from app.eventos.bus import publicar
from app.eventos.relatorio import montar_relatorio, relatorio_markdown
from app.eventos.service import hidratar_evento, registrar_evento
from app.projetos.models import ProjetoIn, ProjetoPatch
from app.projetos.service import buscar_projeto
from app.tasks.models import CorpoIn, DependenciaIn, MensagemIn, TaskIn, TaskPatch
from app.tasks.service import (
    buscar_task,
    diff_da_task,
    gravar_corpo,
    proximo_codigo,
    serializar_task,
)

mcp = MCPServer(
    "Sync de agentes",
    instructions=(
        "Canal de alinhamento entre agentes de IA e humanos, por projeto e task. "
        "Toda tool exige o header Authorization (Bearer <token>); as de escrita "
        "tambem exigem X-Autor-Id - ambos configurados na hora de registrar este "
        "servidor MCP, nunca como parametro de tool. Nunca escreva assinando "
        "como outro autor - voce ja sabe quem voce e pelo X-Autor-Id configurado, "
        "nao precisa perguntar nem pedir id em nenhuma tool.\n\n"
        "Tipo de mensagem (task_mensagem_criar), quando usar cada um:\n"
        "- mudanca: 'fiz/mudei isso'.\n"
        "- pergunta: precisa de resposta do outro lado ou de um humano - entra na "
        "lista de 'perguntas sem resposta' do relatorio ate ser respondida. So use "
        "quando realmente travou, nao pra conversa fiada.\n"
        "- resposta: responde a ultima pergunta daquela task - e o que tira ela da "
        "lista de abertas.\n"
        "- decisao: ficou decidido assim - use isto, nao prosa dentro do corpo, pra "
        "decisao ficar rastreavel a autor e horario.\n"
        "- bloqueio: nao da pra seguir, e por que.\n\n"
        "Regras de conduta:\n"
        "1. Nao reescreva o corpo do outro lado sem avisar. Se discorda, manda "
        "pergunta ou bloqueio primeiro.\n"
        "2. Antes de responder, leia a task inteira (task_ler) - nao responda so "
        "pelo resumo de um evento isolado.\n"
        "3. Uma task por assunto. Se a conversa virou outro assunto, crie task "
        "nova e ligue com task_dependencia_criar.\n"
        "4. status reflete o estado real, nao a intencao - 'feito' e feito e "
        "verificado; 'bloqueado' exige dono_id humano.\n"
        "5. task_corpo_atualizar sempre leva o texto COMPLETO da task, nunca um "
        "fragmento - o que voce manda vira a versao integra."
    ),
)


def _token_do_contexto(ctx: Context) -> None:
    headers = ctx.headers or {}
    validar_token(headers.get("authorization"))


def _autor_do_contexto(ctx: Context) -> sqlite3.Row:
    headers = ctx.headers or {}
    bruto = headers.get("x-autor-id")
    if bruto is None:
        autor_id = None
    else:
        try:
            autor_id = int(bruto)
        except ValueError:
            raise ValueError(f"Header X-Autor-Id invalido: {bruto!r}") from None
    return resolver_autor(autor_id)


# ---------- autores ---------- #


@mcp.tool()
def autor_criar(
    ctx: Context, tipo: ETipoAutor, nome: str, responsavel_id: int | None = None
) -> dict[str, Any]:
    """Cadastra um autor. 'ia' exige responsavel_id de um autor 'humano' ja
    cadastrado; 'humano' nao tem responsavel_id."""
    _token_do_contexto(ctx)
    dados = AutorIn(tipo=tipo, nome=nome, responsavel_id=responsavel_id)
    conn = conectar()
    try:
        if dados.responsavel_id is not None:
            resp = conn.execute(
                "SELECT tipo FROM autores WHERE id = ?", (dados.responsavel_id,)
            ).fetchone()
            if resp is None:
                raise LookupError(f"Responsavel {dados.responsavel_id} nao cadastrado")
            if resp["tipo"] != ETipoAutor.humano.value:
                raise ValueError("Responsavel de uma IA tem que ser autor do tipo 'humano'")
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO autores (tipo, nome, responsavel_id, criado_em) VALUES (?,?,?,?)",
                    (dados.tipo.value, dados.nome, dados.responsavel_id, agora()),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"Ja existe autor com o nome '{dados.nome}'") from None
        return {"id": cursor.lastrowid, **dados.model_dump(mode="json")}
    finally:
        conn.close()


@mcp.tool()
def autor_listar(ctx: Context) -> list[dict[str, Any]]:
    """Lista todos os autores cadastrados (IA e humano)."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        linhas = conn.execute(
            """SELECT a.id, a.tipo, a.nome, a.responsavel_id, r.nome AS responsavel, a.criado_em
                 FROM autores a LEFT JOIN autores r ON r.id = a.responsavel_id
                ORDER BY a.id"""
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        conn.close()


# ---------- projetos ---------- #


@mcp.tool()
def projeto_criar(
    ctx: Context,
    slug: str,
    nome: str,
    descricao: str | None = None,
    status: EStatusProjeto = EStatusProjeto.ativo,
) -> dict[str, Any]:
    """Cria um projeto. `slug` casa com ^[a-z0-9][a-z0-9-]*$ e e usado pra
    enderecar tudo dentro dele."""
    _token_do_contexto(ctx)
    dados = ProjetoIn(slug=slug, nome=nome, descricao=descricao, status=status)
    conn = conectar()
    try:
        try:
            with conn:
                cursor = conn.execute(
                    """INSERT INTO projetos
                       (slug, nome, descricao, status, criado_em, atualizado_em)
                       VALUES (?,?,?,?,?,?)""",
                    (dados.slug, dados.nome, dados.descricao, dados.status.value, agora(), agora()),
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"Projeto '{dados.slug}' ja existe") from None
        return {"id": cursor.lastrowid, **dados.model_dump(mode="json")}
    finally:
        conn.close()


@mcp.tool()
def projeto_listar(ctx: Context) -> list[dict[str, Any]]:
    """Lista projetos, com contagem de tasks e o cursor atual de eventos de cada um."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        linhas = conn.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM tasks   t WHERE t.projeto_id = p.id) AS tasks,
                      (SELECT MAX(seq) FROM eventos e WHERE e.projeto_id = p.id) AS cursor
                 FROM projetos p ORDER BY p.id"""
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        conn.close()


@mcp.tool()
def projeto_atualizar(
    ctx: Context,
    slug: str,
    nome: str | None = None,
    descricao: str | None = None,
    status: EStatusProjeto | None = None,
) -> dict[str, Any]:
    """Atualiza campos de um projeto existente. So os campos informados mudam."""
    _token_do_contexto(ctx)
    dados = ProjetoPatch(nome=nome, descricao=descricao, status=status)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        mudancas = dados.model_dump(mode="json", exclude_none=True)
        if not mudancas:
            raise ValueError("Nada pra atualizar")
        with conn:
            for campo, valor in mudancas.items():
                conn.execute(
                    f"UPDATE projetos SET {campo} = ? WHERE id = ?", (valor, projeto["id"])
                )
            conn.execute(
                "UPDATE projetos SET atualizado_em = ? WHERE id = ?", (agora(), projeto["id"])
            )
        return dict(buscar_projeto(conn, slug))
    finally:
        conn.close()


# ---------- tasks ---------- #


@mcp.tool()
async def task_criar(
    ctx: Context,
    slug: str,
    titulo: str,
    codigo: str | None = None,
    status: EStatusTask = EStatusTask.ideia,
    etiquetas: list[str] | None = None,
    dono_id: int | None = None,
    corpo: str | None = None,
) -> dict[str, Any]:
    """Cria uma task no projeto. `codigo` (ex: T-001) e gerado automatico se
    omitido. `corpo`, se enviado, ja vira a v1."""
    _token_do_contexto(ctx)
    autor = _autor_do_contexto(ctx)
    dados = TaskIn(
        titulo=titulo,
        codigo=codigo,
        status=status,
        etiquetas=etiquetas or [],
        dono_id=dono_id,
        corpo=corpo,
    )
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        codigo_final = dados.codigo or proximo_codigo(conn, projeto["id"])
        try:
            with conn:
                cursor = conn.execute(
                    """INSERT INTO tasks
                       (projeto_id, codigo, titulo, status, etiquetas,
                        dono_id, criado_em, atualizado_em)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        projeto["id"],
                        codigo_final,
                        dados.titulo,
                        dados.status.value,
                        json.dumps(dados.etiquetas, ensure_ascii=False),
                        dados.dono_id,
                        agora(),
                        agora(),
                    ),
                )
                task_id = int(cursor.lastrowid)
                seq = registrar_evento(
                    conn,
                    projeto_id=projeto["id"],
                    task_id=task_id,
                    autor_id=autor["id"],
                    kind=EKindEvento.task_criada.value,
                    texto=dados.titulo,
                )
                task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if dados.corpo is not None:
                    versao, _ = gravar_corpo(conn, task, dados.corpo, autor["id"])
                    registrar_evento(
                        conn,
                        projeto_id=projeto["id"],
                        task_id=task_id,
                        autor_id=autor["id"],
                        kind=EKindEvento.corpo.value,
                        versao=versao,
                    )
        except sqlite3.IntegrityError:
            raise ValueError(f"Task '{codigo_final}' ja existe neste projeto") from None
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, **serializar_task(conn, task)}
    finally:
        conn.close()


@mcp.tool()
def task_listar(
    ctx: Context, slug: str, status: EStatusTask | None = None, etiqueta: str | None = None
) -> list[dict[str, Any]]:
    """Lista tasks do projeto, com filtro opcional por status e/ou etiqueta."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        sql = "SELECT * FROM tasks WHERE projeto_id = ?"
        params: list[Any] = [projeto["id"]]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY codigo"
        tasks = [serializar_task(conn, t) for t in conn.execute(sql, params)]
        if etiqueta is not None:
            tasks = [t for t in tasks if etiqueta in t["etiquetas"]]
        return tasks
    finally:
        conn.close()


@mcp.tool()
def task_ler(ctx: Context, slug: str, codigo: str, com_corpo: bool = True) -> dict[str, Any]:
    """Le 1 task por codigo, com corpo atual e a trilha completa de eventos dela."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        dados = serializar_task(conn, task)
        if com_corpo:
            corpo = conn.execute(
                "SELECT versao, texto FROM corpos WHERE task_id = ? ORDER BY versao DESC LIMIT 1",
                (task["id"],),
            ).fetchone()
            dados["corpo"] = corpo["texto"] if corpo else None
        dados["eventos"] = [
            hidratar_evento(conn, r["seq"])
            for r in conn.execute(
                "SELECT seq FROM eventos WHERE task_id = ? ORDER BY seq", (task["id"],)
            )
        ]
        return dados
    finally:
        conn.close()


@mcp.tool()
async def task_atualizar(
    ctx: Context,
    slug: str,
    codigo: str,
    titulo: str | None = None,
    status: EStatusTask | None = None,
    etiquetas: list[str] | None = None,
    dono_id: int | None = None,
) -> dict[str, Any]:
    """Atualiza campos da task (titulo/status/etiquetas/dono). Gera 1 evento
    por campo que de fato mudou."""
    _token_do_contexto(ctx)
    autor = _autor_do_contexto(ctx)
    dados = TaskPatch(titulo=titulo, status=status, etiquetas=etiquetas, dono_id=dono_id)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        mudancas = dados.model_dump(mode="json", exclude_none=True)
        if not mudancas:
            raise ValueError("Nada pra atualizar")
        sequencias: list[int] = []
        with conn:
            for campo, valor in mudancas.items():
                antes = task[campo]
                novo = json.dumps(valor, ensure_ascii=False) if campo == "etiquetas" else valor
                if str(antes) == str(novo):
                    continue
                conn.execute(f"UPDATE tasks SET {campo} = ? WHERE id = ?", (novo, task["id"]))
                sequencias.append(
                    registrar_evento(
                        conn,
                        projeto_id=projeto["id"],
                        task_id=task["id"],
                        autor_id=autor["id"],
                        kind=EKindEvento.campo.value,
                        campo=campo,
                        valor_de=None if antes is None else str(antes),
                        valor_para=None if novo is None else str(novo),
                    )
                )
            conn.execute("UPDATE tasks SET atualizado_em = ? WHERE id = ?", (agora(), task["id"]))
        for seq in sequencias:
            await publicar(slug, hidratar_evento(conn, seq))
        atual = buscar_task(conn, projeto["id"], codigo)
        return {"cursor": sequencias[-1] if sequencias else None, **serializar_task(conn, atual)}
    finally:
        conn.close()


@mcp.tool()
async def task_dependencia_criar(
    ctx: Context, slug: str, codigo: str, depende_de: str
) -> dict[str, Any]:
    """Marca que a task `codigo` depende da task `depende_de` (mesmo projeto)."""
    _token_do_contexto(ctx)
    autor = _autor_do_contexto(ctx)
    dados = DependenciaIn(depende_de=depende_de)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        alvo = buscar_task(conn, projeto["id"], dados.depende_de)
        if task["id"] == alvo["id"]:
            raise ValueError("Task nao pode depender de si mesma")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO dependencias (task_id, depende_de_id) VALUES (?,?)",
                (task["id"], alvo["id"]),
            )
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.dependencia.value,
                valor_para=alvo["codigo"],
            )
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, **serializar_task(conn, task)}
    finally:
        conn.close()


# ---------- conversa ---------- #


@mcp.tool()
async def task_mensagem_criar(
    ctx: Context, slug: str, codigo: str, tipo: ETipoMensagem, texto: str
) -> dict[str, Any]:
    """Manda uma mensagem na task (mudanca/pergunta/resposta/decisao/bloqueio)
    - nao muda estado, so registra."""
    _token_do_contexto(ctx)
    autor = _autor_do_contexto(ctx)
    dados = MensagemIn(tipo=tipo, texto=texto)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        with conn:
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.mensagem.value,
                tipo=dados.tipo.value,
                texto=dados.texto,
            )
        evento = hidratar_evento(conn, seq)
        await publicar(slug, evento)
        return {"cursor": seq, **evento}
    finally:
        conn.close()


@mcp.tool()
async def task_corpo_atualizar(ctx: Context, slug: str, codigo: str, texto: str) -> dict[str, Any]:
    """Grava uma versao nova do corpo da task e devolve o diff contra a
    anterior. Mande sempre o texto completo, nunca um fragmento."""
    _token_do_contexto(ctx)
    autor = _autor_do_contexto(ctx)
    dados = CorpoIn(texto=texto)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        with conn:
            versao, diff = gravar_corpo(conn, task, dados.texto, autor["id"])
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.corpo.value,
                versao=versao,
            )
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, "codigo": codigo, "versao": versao, "diff": diff}
    finally:
        conn.close()


@mcp.tool()
def task_diff_ler(ctx: Context, slug: str, codigo: str, desde: int = 0) -> dict[str, Any]:
    """Diff unificado do corpo da task, da versao `desde` ate a mais recente."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        return diff_da_task(conn, task["id"], codigo, desde)
    finally:
        conn.close()


# ---------- eventos ---------- #


@mcp.tool()
def projeto_mudancas_ler(
    ctx: Context, slug: str, desde: int = 0, limite: int = 200
) -> dict[str, Any]:
    """O que mudou no projeto desde o cursor `desde` (use o `cursor` da
    ultima resposta na proxima chamada)."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        linhas = conn.execute(
            "SELECT seq FROM eventos WHERE projeto_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (projeto["id"], desde, limite),
        ).fetchall()
        eventos = [hidratar_evento(conn, r["seq"]) for r in linhas]
        return {
            "projeto": slug,
            "desde": desde,
            "cursor": eventos[-1]["seq"] if eventos else desde,
            "total": len(eventos),
            "eventos": eventos,
        }
    finally:
        conn.close()


@mcp.tool()
def projeto_relatorio_ler(
    ctx: Context,
    slug: str,
    desde: int = 0,
    formato: Literal["md", "json"] = "md",
    com_diff: bool = True,
) -> dict[str, Any] | str:
    """Relatorio consolidado do projeto (resumo geral, atividade por task,
    diffs). `formato=json` pra processar sem parsear markdown."""
    _token_do_contexto(ctx)
    conn = conectar()
    try:
        rel = montar_relatorio(conn, slug, desde)
        if formato == "json":
            return rel
        return relatorio_markdown(conn, rel, com_diff)
    finally:
        conn.close()
