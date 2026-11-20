"""Agregações que só a interface web usa: painel do projeto e cards entre projetos."""

import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from src.modules.events import repositorio as eventos_repositorio
from src.modules.events.relatorio import perguntas_abertas
from src.modules.features import repositorio as features_repositorio
from src.modules.features import service as features_service
from src.modules.projects import repositorio as projects_repositorio
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.modules.web import graficos
from src.shared.enums import EAgent, EKindEvent, EStatusTask

ORDEM_STATUS = [s.value for s in EStatusTask]
ORDEM_AGENT = [EAgent.human, EAgent.claude, EAgent.codex, EAgent.outro]
PEDEM_ATENCAO = (EStatusTask.bloqueado.value, EStatusTask.aguardando_decisao.value)


def _participantes(linhas: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Uma entrada por pessoa, com os eventos de cada ferramenta, o total e a
    data do último. Quem mais fez vem primeiro."""
    por_pessoa: dict[int, dict[str, Any]] = {}
    for linha in linhas:
        pessoa = por_pessoa.setdefault(
            linha["id"],
            {
                "id": linha["id"],
                "alias": linha["alias"],
                "name": linha["name"],
                "por_agent": {},
                "total": 0,
                "ultimo": "",
            },
        )
        pessoa["por_agent"][linha["agent"]] = linha["n"]
        pessoa["total"] += linha["n"]
        pessoa["ultimo"] = max(pessoa["ultimo"], linha["ultimo"])
    for pessoa in por_pessoa.values():
        pessoa["ferramentas"] = [(a, pessoa["por_agent"][a]) for a in ORDEM_AGENT if a in pessoa["por_agent"]]
    return sorted(por_pessoa.values(), key=lambda p: p["total"], reverse=True)


def participantes_do_projeto(conn: sqlite3.Connection, projeto_id: int) -> list[dict[str, Any]]:
    return _participantes(eventos_repositorio.atividade_por_pessoa(conn, projeto_id))


def participantes_por_feature(conn: sqlite3.Connection, projeto_id: int) -> dict[str, list[dict[str, Any]]]:
    linhas = eventos_repositorio.atividade_por_feature(conn, projeto_id)
    return {
        code: _participantes([linha for linha in linhas if linha["feature_code"] == code])
        for code in {linha["feature_code"] for linha in linhas}
    }


def lista_de_features(conn: sqlite3.Connection, projeto_id: int) -> dict[str, Any]:
    """Features (por code) com status, progresso, participantes e último evento,
    mais o resumo das tasks avulsas."""
    participantes = participantes_por_feature(conn, projeto_id)
    features = []
    for linha in features_repositorio.find_all(conn, projeto_id):
        feature = features_service.serializar(conn, linha)
        feature["participantes"] = participantes.get(feature["code"], [])
        feature["ultimo"] = max((p["ultimo"] for p in feature["participantes"]), default=feature["updated_at"])
        features.append(feature)
    avulsas = Counter(t["status"] for t in tasks_repositorio.find_all(conn, projeto_id, None, sem_feature=True))
    return {
        "features": features,
        "avulsas": {
            "total": sum(avulsas.values()) - avulsas[EStatusTask.cancelada.value],
            "feito": avulsas[EStatusTask.feito.value],
            "contagem_status": dict(avulsas),
        },
    }


def painel(conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None) -> dict[str, Any]:
    tasks = tasks_service.filtrar_tasks(conn, projeto, person_id, None, None)
    contagem = Counter(t["status"] for t in tasks)
    participantes = participantes_do_projeto(conn, projeto["id"])
    ativos = {p["id"] for p in participantes}
    por_feature = participantes_por_feature(conn, projeto["id"])
    features = [
        features_service.serializar(conn, f)
        for f in features_repositorio.find_all(conn, projeto["id"])
    ]
    for feature in features:
        feature["participantes"] = por_feature.get(feature["code"], [])
    agora = datetime.now().astimezone()
    historico = graficos.historico_de_status(conn, projeto["id"])
    ids = {linha["code"]: linha["id"] for linha in tasks_repositorio.find_all(conn, projeto["id"], None)}
    return {
        "agora": agora,
        "travadas": graficos.travadas(tasks, historico, ids, agora),
        "ritmo": graficos.ritmo_semanal(historico, agora),
        "comparado": graficos.status_comparado(historico, agora),
        "tempo": graficos.tempo_por_status(historico),
        "features_travadas": graficos.features_travadas(tasks, features),
        "pessoas": graficos.eventos_por_pessoa(conn, projeto["id"], agora),
        "total_tasks": len(tasks) - contagem[EStatusTask.cancelada.value],
        "canceladas": contagem[EStatusTask.cancelada.value],
        "feitas": contagem[EStatusTask.feito.value],
        "contagem_status": [(s, contagem[s]) for s in ORDEM_STATUS],
        "features": features,
        "participantes": participantes,
        "fazendo_agora": sorted(
            (t for t in tasks if t["fazendo_agora"]),
            key=lambda t: t["fazendo_agora"]["desde"],
            reverse=True,
        ),
        "atencao": [t for t in tasks if t["status"] in PEDEM_ATENCAO],
        "perguntas_abertas": perguntas_abertas(conn, projeto["id"], tasks),
        "membros": [
            {**dict(m), "sem_atividade": m["id"] not in ativos}
            for m in projects_repositorio.membros_do_projeto(conn, projeto["id"])
        ],
        "repos": [dict(r) for r in projects_repositorio.repos_do_projeto(conn, projeto["id"])],
        "nao_lidos": (
            sum(t.get("nao_lidos", 0) for t in tasks)
            + features_repositorio.eventos_nao_lidos(conn, projeto["id"], person_id)["nao_lidos"]
            if person_id is not None
            else None
        ),
        "ciclo": ciclo_medio(conn, projeto["id"]),
    }


def ciclo_medio(conn: sqlite3.Connection, projeto_id: int) -> dict[str, Any]:
    """Tempo médio da criação até a primeira vez em 'feito', nas tasks que hoje
    estão feitas e têm essa mudança registrada."""
    linhas = conn.execute(
        f"""SELECT t.created_at AS criada, MIN(e.created_at) AS feita
             FROM tasks t
             JOIN events e ON e.task_id = t.id AND e.kind = '{EKindEvent.task_field_changed}'
                          AND e.campo = 'status' AND e.valor_para = '{EStatusTask.feito}'
            WHERE t.project_id = ? AND t.status = '{EStatusTask.feito}'
            GROUP BY t.id""",
        (projeto_id,),
    ).fetchall()
    duracoes = [
        max((datetime.fromisoformat(linha["feita"]) - datetime.fromisoformat(linha["criada"])).total_seconds(), 0)
        for linha in linhas
    ]
    return {"segundos": sum(duracoes) / len(duracoes) if duracoes else None, "n": len(duracoes)}


def projetos_da_pessoa(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    return [p for p in projects_repositorio.find_all(conn, person_id) if p["role"] is not None]


def todos_projetos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def cards(
    conn: sqlite3.Connection, projetos: list[sqlite3.Row], person_id: int | None
) -> list[dict[str, Any]]:
    """Resumo de cada projeto pra visão entre projetos."""
    resultado = []
    for projeto in projetos:
        tasks = [dict(t) for t in tasks_repositorio.find_all(conn, projeto["id"], None)]
        contagem = Counter(t["status"] for t in tasks)
        ultimo = conn.execute(
            "SELECT MAX(created_at) AS ultimo FROM events WHERE project_id = ?", (projeto["id"],)
        ).fetchone()["ultimo"]
        card = {
            "slug": projeto["slug"],
            "name": projeto["name"],
            "description": projeto["description"],
            "status": projeto["status"],
            "visibility": projeto["visibility"],
            "total_tasks": len(tasks) - contagem[EStatusTask.cancelada.value],
            "feitas": contagem[EStatusTask.feito.value],
            "fazendo_agora": contagem[EStatusTask.em_andamento.value],
            "atencao": sum(contagem[s] for s in PEDEM_ATENCAO),
            "perguntas_abertas": len(perguntas_abertas(conn, projeto["id"], tasks)),
            "membros": len(projects_repositorio.membros_do_projeto(conn, projeto["id"])),
            "participantes": eventos_repositorio.total_participantes(conn, projeto["id"]),
            "ultima_atividade": ultimo,
            "eventos_14d": conn.execute(
                "SELECT COUNT(*) AS n FROM events WHERE project_id = ? AND created_at >= ?",
                (projeto["id"], (datetime.now().astimezone() - timedelta(days=14)).isoformat(timespec="seconds")),
            ).fetchone()["n"],
            "nao_lidos": None,
        }
        if person_id is not None:
            leitura = tasks_repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
            card["nao_lidos"] = (
                sum(marca["nao_lidos"] for marca in leitura.values())
                + features_repositorio.eventos_nao_lidos(conn, projeto["id"], person_id)["nao_lidos"]
            )
        resultado.append(card)
    return resultado
