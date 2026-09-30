# `events` é a trilha única do projeto - não existe tabela por tipo de evento.

import sqlite3
from typing import Any


def insert(conn: sqlite3.Connection, **campos: Any) -> int:
    colunas = ", ".join(campos)
    marcadores = ", ".join("?" for _ in campos)
    cursor = conn.execute(
        f"INSERT INTO events ({colunas}) VALUES ({marcadores})", tuple(campos.values())
    )
    # Todo evento de task carimba `tasks.updated_at`: o campo significa "quando
    # aconteceu a última coisa nesta task", e é por ele que `list_tasks` diz o
    # que andou sem precisar reler task por task.
    if campos.get("task_id") is not None:
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE id = ?",
            (campos["created_at"], campos["task_id"]),
        )
    return int(cursor.lastrowid)


def buscar_por_seq(conn: sqlite3.Connection, seq: int) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT e.*, pe.alias AS author_alias, pe.name AS author_name,
               t.code AS task_code, t.title AS task_title,
               f.code AS feature_code, p.slug AS project_slug
          FROM events e
          JOIN people   pe ON pe.id = e.author_id
          LEFT JOIN tasks t ON t.id = e.task_id
          LEFT JOIN features f ON f.id = COALESCE(e.feature_id, t.feature_id)
          JOIN projects p ON p.id = e.project_id
         WHERE e.seq = ?
        """,
        (seq,),
    ).fetchone()


def seqs_da_task(conn: sqlite3.Connection, task_id: int) -> list[int]:
    return [
        r["seq"]
        for r in conn.execute(
            "SELECT seq FROM events WHERE task_id = ? ORDER BY seq", (task_id,)
        )
    ]


def seqs_do_projeto(
    conn: sqlite3.Connection,
    projeto_id: int,
    desde: int,
    limite: int | None = None,
    exceto_autor: int | None = None,
) -> list[int]:
    sql = "SELECT seq FROM events WHERE project_id = ? AND seq > ?"
    params: list[Any] = [projeto_id, desde]
    if exceto_autor is not None:
        sql += " AND author_id != ?"
        params.append(exceto_autor)
    sql += " ORDER BY seq"
    if limite is not None:
        sql += " LIMIT ?"
        params.append(limite)
    return [r["seq"] for r in conn.execute(sql, params)]


# Condição SQL de cada tipo do feed de atividade. Só literais do código.
CONDICAO_TIPO = {
    "mensagem": "e.kind = 'message.created'",
    "status": "e.kind = 'task.field_changed' AND e.campo = 'status'",
    "campo": "e.kind = 'task.field_changed' AND e.campo != 'status'",
    "corpo": "e.kind = 'body.updated'",
    "diff": "e.kind = 'diff.published'",
    "criacao": "e.kind = 'task.created'",
    "feature": "e.kind LIKE 'feature.%'",
}


def seqs_do_feed(
    conn: sqlite3.Connection,
    projeto_id: int,
    limite: int,
    antes: int = 0,
    pessoa: str | None = None,
    agent: str | None = None,
    tipo: str | None = None,
    task_id: int | None = None,
    feature: str | None = None,
    desde: str | None = None,
) -> list[int]:
    """Seqs do projeto do mais novo pro mais antigo, abaixo de `antes` (0 = do
    começo). `feature` casa o evento da feature e os das tasks dela."""
    sql = """SELECT e.seq
               FROM events e
               JOIN people pe ON pe.id = e.author_id
               LEFT JOIN tasks t ON t.id = e.task_id
               LEFT JOIN features f ON f.id = COALESCE(e.feature_id, t.feature_id)
              WHERE e.project_id = ?"""
    params: list[Any] = [projeto_id]
    if antes:
        sql += " AND e.seq < ?"
        params.append(antes)
    if pessoa:
        sql += " AND pe.alias = ?"
        params.append(pessoa)
    if agent:
        sql += " AND e.agent = ?"
        params.append(agent)
    if tipo:
        sql += f" AND ({CONDICAO_TIPO[tipo]})"
    if task_id is not None:
        sql += " AND e.task_id = ?"
        params.append(task_id)
    if feature:
        sql += " AND f.code = ?"
        params.append(feature)
    if desde:
        sql += " AND e.created_at >= ?"
        params.append(desde)
    sql += " ORDER BY e.seq DESC LIMIT ?"
    params.append(limite)
    return [r["seq"] for r in conn.execute(sql, params)]


def atividade_por_pessoa(conn: sqlite3.Connection, projeto_id: int) -> list[sqlite3.Row]:
    """Eventos do projeto contados por pessoa e ferramenta."""
    return conn.execute(
        """SELECT pe.id, pe.alias, pe.name, e.agent, COUNT(*) AS n, MAX(e.created_at) AS ultimo
             FROM events e JOIN people pe ON pe.id = e.author_id
            WHERE e.project_id = ?
            GROUP BY pe.id, e.agent""",
        (projeto_id,),
    ).fetchall()


def atividade_por_feature(conn: sqlite3.Connection, projeto_id: int) -> list[sqlite3.Row]:
    """Mesma contagem, por feature: os eventos da feature e os das tasks dela."""
    return conn.execute(
        """SELECT f.code AS feature_code, pe.id, pe.alias, pe.name, e.agent,
                  COUNT(*) AS n, MAX(e.created_at) AS ultimo
             FROM events e
             JOIN people pe ON pe.id = e.author_id
             LEFT JOIN tasks t ON t.id = e.task_id
             JOIN features f ON f.id = COALESCE(e.feature_id, t.feature_id)
            WHERE e.project_id = ?
            GROUP BY f.id, pe.id, e.agent""",
        (projeto_id,),
    ).fetchall()


def total_participantes(conn: sqlite3.Connection, projeto_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(DISTINCT author_id) AS n FROM events WHERE project_id = ?", (projeto_id,)
    ).fetchone()["n"]


def mensagens_da_task(conn: sqlite3.Connection, projeto_id: int, code: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.seq, e.type, e.texto, e.agent, e.created_at, pe.alias AS author_alias
             FROM events e
             JOIN people pe ON pe.id = e.author_id
             JOIN tasks  t  ON t.id = e.task_id
            WHERE t.code = ? AND t.project_id = ? AND e.kind = 'message.created'
            ORDER BY e.seq""",
        (code, projeto_id),
    ).fetchall()
