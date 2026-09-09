# Corpo versionado não tem tabela própria - é evento kind='body.updated' em `events`
# (ver ultimo_corpo/todos_corpos). find_by_code também é usado por outros domínios.

import json
import sqlite3
from typing import Any

from src.modules.tasks.models import TaskIn
from src.shared.db import now
from src.shared.enums import EStatusTask
from src.shared.erros import NotFound


def find_by_code(conn: sqlite3.Connection, projeto_id: int, code: str) -> sqlite3.Row:
    task = conn.execute(
        "SELECT * FROM tasks WHERE project_id = ? AND code = ?", (projeto_id, code)
    ).fetchone()
    if task is None:
        raise NotFound(f"Task '{code}' não existe neste projeto")
    return task


def find_by_id(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def count(conn: sqlite3.Connection, projeto_id: int) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE project_id = ?", (projeto_id,)
    ).fetchone()["n"]


def insert(conn: sqlite3.Connection, projeto_id: int, code: str, dados: TaskIn) -> int:
    cursor = conn.execute(
        """INSERT INTO tasks
           (project_id, code, title, status, tags, owner_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            projeto_id,
            code,
            dados.title,
            dados.status.value,
            json.dumps(dados.tags, ensure_ascii=False),
            dados.owner_id,
            now(),
            now(),
        ),
    )
    return int(cursor.lastrowid)


def find_all(
    conn: sqlite3.Connection, projeto_id: int, status: EStatusTask | None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM tasks WHERE project_id = ?"
    params: list[Any] = [projeto_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status.value)
    sql += " ORDER BY code"
    return conn.execute(sql, params).fetchall()


def update_campo(conn: sqlite3.Connection, task_id: int, campo: str, valor: Any) -> None:
    conn.execute(f"UPDATE tasks SET {campo} = ? WHERE id = ?", (valor, task_id))


def tocar(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("UPDATE tasks SET updated_at = ? WHERE id = ?", (now(), task_id))


def owner_name(conn: sqlite3.Connection, owner_id: int | None) -> str | None:
    if owner_id is None:
        return None
    linha = conn.execute("SELECT name FROM people WHERE id = ?", (owner_id,)).fetchone()
    return linha["name"] if linha else None


def ultimo_corpo(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT version, texto FROM events
            WHERE task_id = ? AND kind = 'body.updated' ORDER BY version DESC LIMIT 1""",
        (task_id,),
    ).fetchone()


def seqs_de_diff(conn: sqlite3.Connection, task_id: int) -> list[int]:
    return [
        linha["seq"]
        for linha in conn.execute(
            """SELECT seq FROM events
                WHERE task_id = ? AND kind = 'diff.published' ORDER BY seq""",
            (task_id,),
        )
    ]


def todos_corpos(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT version, texto FROM events
            WHERE task_id = ? AND kind = 'body.updated' ORDER BY version""",
        (task_id,),
    ).fetchall()
