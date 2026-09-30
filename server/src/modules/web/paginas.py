"""Contexto das páginas de projeto, igual pra pessoa e pra admin. `person_id=None`
é a leitura de admin: sem não lidos, sem marcar lido, sem formulário."""

import sqlite3
from datetime import datetime, timedelta
from typing import Any

from src.modules.events.relatorio import perguntas_abertas
from src.modules.features import repositorio as features_repositorio
from src.modules.projects import repositorio as projects_repositorio
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.modules.web import indicadores
from src.shared.enums import EKindEvent, EStatusTask, ETypeMessage

SEM_FEATURE = "_sem"
# Mensagens (ou eventos de sistema) seguidos do mesmo autor dentro desta janela
# viram um bloco só na conversa.
JANELA_GRUPO = timedelta(minutes=10)


def _base(person_id: int | None) -> dict[str, Any]:
    admin = person_id is None
    return {"base": "/web/admin" if admin else "/web", "admin": admin}


def ctx_nav(conn: sqlite3.Connection, person_id: int | None) -> list[dict[str, Any]]:
    """Projetos da barra lateral: os da pessoa (com não lidos) ou todos, pro admin."""
    if person_id is None:
        return [{"slug": p["slug"], "name": p["name"], "nao_lidos": 0} for p in indicadores.todos_projetos(conn)]
    itens = []
    for projeto in sorted(indicadores.projetos_da_pessoa(conn, person_id), key=lambda p: p["name"]):
        leitura = tasks_repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
        itens.append(
            {
                "slug": projeto["slug"],
                "name": projeto["name"],
                "nao_lidos": sum(marca["nao_lidos"] for marca in leitura.values()),
            }
        )
    return itens


def ctx_painel(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, por: str
) -> dict[str, Any]:
    return {
        **_base(person_id),
        "aba": "painel",
        "projeto": projeto,
        "painel": indicadores.painel(conn, projeto, person_id),
        "grafico": indicadores.atividade(conn, projeto["id"], por),
    }


def ctx_tasks(
    conn: sqlite3.Connection,
    projeto: sqlite3.Row,
    person_id: int | None,
    status: str,
    feature: str,
    tag: str,
    q: str,
    nao_lidas: bool,
    visao: str,
) -> dict[str, Any]:
    tasks = tasks_service.filtrar_tasks(
        conn,
        projeto,
        person_id,
        EStatusTask(status) if status else None,
        tag or None,
        q or None,
        nao_lidas and person_id is not None,
        feature if feature and feature != SEM_FEATURE else None,
        feature == SEM_FEATURE,
    )
    statuses = [s.value for s in EStatusTask]
    return {
        **_base(person_id),
        "aba": "tasks",
        "projeto": projeto,
        "tasks": tasks,
        "colunas": [(s, [t for t in tasks if t["status"] == s]) for s in statuses],
        "features": features_repositorio.find_all(conn, projeto["id"]),
        "statuses": statuses,
        "filtros": {
            "status": status,
            "feature": feature,
            "tag": tag,
            "q": q,
            "nao_lidas": nao_lidas,
            "visao": visao,
        },
        "SEM_FEATURE": SEM_FEATURE,
    }


def linha_do_tempo(eventos: list[dict[str, Any]], abertas: set[int]) -> list[dict[str, Any]]:
    """Eventos da task em blocos pra conversa: separador por dia, mensagens
    seguidas do mesmo autor juntas, eventos de sistema condensados juntos e
    cada diff num bloco próprio."""
    blocos: list[dict[str, Any]] = []
    dia_atual = None
    for evento in eventos:
        dia = evento["created_at"][:10]
        if dia != dia_atual:
            blocos.append({"tipo": "dia", "dia": dia})
            dia_atual = dia
        momento = datetime.fromisoformat(evento["created_at"])
        if evento["kind"] == EKindEvent.message_created:
            tipo = "mensagens"
        elif evento["kind"] == EKindEvent.diff_published:
            tipo = "diff"
        else:
            tipo = "sistema"
        autor = (evento["actor"]["person"], evento["actor"]["agent"])
        item = {**evento, "aberta": evento["seq"] in abertas}
        ultimo = blocos[-1]
        if (
            tipo != "diff"
            and ultimo["tipo"] == tipo
            and ultimo["autor"] == autor
            and momento - ultimo["fim"] <= JANELA_GRUPO
        ):
            ultimo["itens"].append(item)
            ultimo["fim"] = momento
        else:
            blocos.append(
                {
                    "tipo": tipo,
                    "autor": autor,
                    "actor": evento["actor"],
                    "inicio": evento["created_at"],
                    "fim": momento,
                    "itens": [item],
                }
            )
    return blocos


def ctx_task(
    conn: sqlite3.Connection, projeto: sqlite3.Row, code: str, person_id: int | None
) -> dict[str, Any]:
    task = tasks_service.montar_task(conn, projeto, code, person_id, com_corpo=True, marcar_lida=False)
    eventos = task["eventos"]
    abertas = {p["seq"] for p in perguntas_abertas(conn, projeto["id"], [task])}

    participantes: dict[str, dict[str, Any]] = {}
    for evento in eventos:
        ator = evento["actor"]
        dados = participantes.setdefault(ator["person"], {"person": ator["person"], "name": ator["name"], "agents": []})
        if ator["agent"] not in dados["agents"]:
            dados["agents"].append(ator["agent"])

    corpos = [e for e in eventos if e["kind"] == EKindEvent.body_updated]
    return {
        **_base(person_id),
        "aba": "task",
        "projeto": projeto,
        "task": task,
        "nomes": {str(linha["id"]): linha["name"] for linha in conn.execute("SELECT id, name FROM people")},
        "blocos": linha_do_tempo(eventos, abertas),
        "abertas": len(abertas),
        "participantes": list(participantes.values()),
        "diffs": [e for e in eventos if e["kind"] == EKindEvent.diff_published],
        "ultimo_corpo": corpos[-1] if corpos else None,
        "membros": projects_repositorio.membros_do_projeto(conn, projeto["id"]),
        "features": features_repositorio.find_all(conn, projeto["id"]),
        "statuses": [s.value for s in EStatusTask],
        "tipos_mensagem": [t.value for t in ETypeMessage],
    }


def ctx_corpo_diff(
    conn: sqlite3.Connection, projeto: sqlite3.Row, code: str, versao: int
) -> dict[str, Any]:
    task = tasks_repositorio.find_by_code(conn, projeto["id"], code)
    return {"diff": tasks_service.task_diff(conn, task["id"], code, versao - 1, versao)}
