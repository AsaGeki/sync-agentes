# find_by_slug também é usado por tasks/eventos/mcp_server pra endereçar um projeto.

import json
import sqlite3
from typing import Any

from src.modules.projects.models import ProjetoIn
from src.shared.db import now
from src.shared.erros import NotFound


def find_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    projeto = conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
    if projeto is None:
        raise NotFound(f"Projeto '{slug}' não existe")
    return projeto


def insert(conn: sqlite3.Connection, dados: ProjetoIn, created_by: int) -> int:
    cursor = conn.execute(
        """INSERT INTO projects
           (slug, name, description, git_repositories, status, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            dados.slug,
            dados.name,
            dados.description,
            json.dumps(dados.git_repositories, ensure_ascii=False),
            dados.status.value,
            created_by,
            now(),
            now(),
        ),
    )
    return int(cursor.lastrowid)


def find_all(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT p.*,
                  (SELECT COUNT(*) FROM tasks  t WHERE t.project_id = p.id) AS tasks,
                  (SELECT MAX(seq) FROM events e WHERE e.project_id = p.id) AS cursor
             FROM projects p ORDER BY p.id"""
    ).fetchall()


def update_campos(conn: sqlite3.Connection, projeto_id: int, mudancas: dict[str, Any]) -> None:
    for campo, valor in mudancas.items():
        novo = json.dumps(valor, ensure_ascii=False) if campo == "git_repositories" else valor
        conn.execute(f"UPDATE projects SET {campo} = ? WHERE id = ?", (novo, projeto_id))
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), projeto_id))
