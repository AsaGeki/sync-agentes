import sqlite3

from src.shared.db import now


def find_by_id(conn: sqlite3.Connection, person_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM people WHERE id = ?", (person_id,)).fetchone()


def find_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM people WHERE email = ?", (email.lower(),)).fetchone()


def find_by_token_hash(conn: sqlite3.Connection, token_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM people WHERE token_hash = ?", (token_hash,)
    ).fetchone()


def insert(
    conn: sqlite3.Connection, email: str, alias: str, name: str, token_hash: str
) -> int:
    cursor = conn.execute(
        "INSERT INTO people (email, alias, name, token_hash, created_at) VALUES (?,?,?,?,?)",
        (email.lower(), alias, name, token_hash, now()),
    )
    return int(cursor.lastrowid)


def update_token(conn: sqlite3.Connection, person_id: int, name: str, token_hash: str) -> None:
    conn.execute(
        "UPDATE people SET name = ?, token_hash = ? WHERE id = ?",
        (name, token_hash, person_id),
    )


def find_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT id, email, alias, name, token_hash IS NOT NULL AS tem_token, created_at
             FROM people ORDER BY id"""
    ).fetchall()
