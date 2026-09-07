# `events` e a trilha unica do projeto - nao existe tabela por tipo de evento.

import sqlite3
from typing import Any


def insert(conn: sqlite3.Connection, **campos: Any) -> int:
    colunas = ", ".join(campos)
    marcadores = ", ".join("?" for _ in campos)
    cursor = conn.execute(
        f"INSERT INTO events ({colunas}) VALUES ({marcadores})", tuple(campos.values())
    )
    return int(cursor.lastrowid)


def buscar_por_seq(conn: sqlite3.Connection, seq: int) -> sqlite3.Row:
    return conn.execute(
        """
        SELECT e.*, a.name AS author_name, a.type AS author_type,
               r.name AS author_responsible, t.code AS task_code,
               t.title AS task_title, p.slug AS project_slug
          FROM events e
          JOIN authors  a ON a.id = e.author_id
          LEFT JOIN authors r ON r.id = a.responsible_id
          LEFT JOIN tasks   t ON t.id = e.task_id
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
    conn: sqlite3.Connection, projeto_id: int, desde: int, limite: int | None = None
) -> list[int]:
    sql = "SELECT seq FROM events WHERE project_id = ? AND seq > ? ORDER BY seq"
    params: list[Any] = [projeto_id, desde]
    if limite is not None:
        sql += " LIMIT ?"
        params.append(limite)
    return [r["seq"] for r in conn.execute(sql, params)]


def mensagens_da_task(conn: sqlite3.Connection, projeto_id: int, code: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT e.seq, e.type, e.texto, e.created_at, a.name AS author_name,
                  a.type AS author_type, r.name AS author_responsible
             FROM events e
             JOIN authors a ON a.id = e.author_id
             LEFT JOIN authors r ON r.id = a.responsible_id
             JOIN tasks t ON t.id = e.task_id
            WHERE t.code = ? AND t.project_id = ? AND e.kind = 'mensagem'
            ORDER BY e.seq""",
        (code, projeto_id),
    ).fetchall()
