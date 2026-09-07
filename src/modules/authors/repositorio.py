import sqlite3

from src.modules.authors.models import AutorIn
from src.shared.db import now


def find_by_id(conn: sqlite3.Connection, autor_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM authors WHERE id = ?", (autor_id,)).fetchone()


def insert(conn: sqlite3.Connection, dados: AutorIn) -> int:
    cursor = conn.execute(
        "INSERT INTO authors (type, name, responsible_id, created_at) VALUES (?,?,?,?)",
        (dados.type.value, dados.name, dados.responsible_id, now()),
    )
    return int(cursor.lastrowid)


def find_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT a.id, a.type, a.name, a.responsible_id, r.name AS responsible_name, a.created_at
             FROM authors a LEFT JOIN authors r ON r.id = a.responsible_id
            ORDER BY a.id"""
    ).fetchall()
