import sqlite3

from fastapi import HTTPException


def buscar_projeto(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    projeto = conn.execute("SELECT * FROM projetos WHERE slug = ?", (slug,)).fetchone()
    if projeto is None:
        raise HTTPException(404, f"Projeto '{slug}' nao existe")
    return projeto
