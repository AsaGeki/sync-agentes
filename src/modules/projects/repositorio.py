# find_by_slug também é usado por tasks/eventos pra endereçar um projeto.

import sqlite3
from typing import Any

from src.shared.db import now
from src.shared.erros import NotFound


def find_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    projeto = conn.execute("SELECT * FROM projects WHERE slug = ?", (slug,)).fetchone()
    if projeto is None:
        raise NotFound(f"Projeto '{slug}' não existe")
    return projeto


def find_by_root_sha(conn: sqlite3.Connection, root_sha: str) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT p.* FROM projects p
             JOIN project_repos r ON r.project_id = p.id
            WHERE r.root_sha = ?""",
        (root_sha,),
    ).fetchone()


def slug_livre(conn: sqlite3.Connection, base: str) -> str:
    slug = base
    sufixo = 2
    while conn.execute("SELECT 1 FROM projects WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{sufixo}"
        sufixo += 1
    return slug


def insert(conn: sqlite3.Connection, slug: str, name: str, created_by: int) -> int:
    cursor = conn.execute(
        """INSERT INTO projects
           (slug, name, description, status, visibility, created_by, created_at, updated_at)
           VALUES (?,?,NULL,'ativo','team',?,?,?)""",
        (slug, name, created_by, now(), now()),
    )
    return int(cursor.lastrowid)


def find_all_de(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    """Só os projetos em que a pessoa é membro - é isto que impede um agente de
    esbarrar no assunto de um projeto que não é dele."""
    return conn.execute(
        """SELECT p.*, m.role,
                  (SELECT COUNT(*) FROM tasks  t WHERE t.project_id = p.id) AS tasks,
                  (SELECT MAX(seq) FROM events e WHERE e.project_id = p.id) AS cursor
             FROM projects p
             JOIN memberships m ON m.project_id = p.id AND m.person_id = ?
            ORDER BY p.id""",
        (person_id,),
    ).fetchall()


def update_campos(conn: sqlite3.Connection, projeto_id: int, mudancas: dict[str, Any]) -> None:
    for campo, valor in mudancas.items():
        conn.execute(f"UPDATE projects SET {campo} = ? WHERE id = ?", (valor, projeto_id))
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), projeto_id))


# ---------- repos ---------- #


def insert_repo(
    conn: sqlite3.Connection, projeto_id: int, root_sha: str, name: str, remote: str | None
) -> None:
    conn.execute(
        "INSERT INTO project_repos (root_sha, project_id, name, remote, created_at)"
        " VALUES (?,?,?,?,?)",
        (root_sha, projeto_id, name, remote, now()),
    )


def repos_do_projeto(conn: sqlite3.Connection, projeto_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT root_sha, name, remote FROM project_repos WHERE project_id = ? ORDER BY name",
        (projeto_id,),
    ).fetchall()


# ---------- membership ---------- #


def find_membership(
    conn: sqlite3.Connection, projeto_id: int, person_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM memberships WHERE project_id = ? AND person_id = ?",
        (projeto_id, person_id),
    ).fetchone()


def insert_membership(
    conn: sqlite3.Connection, projeto_id: int, person_id: int, role: str
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO memberships (project_id, person_id, role, created_at)"
        " VALUES (?,?,?,?)",
        (projeto_id, person_id, role, now()),
    )


def membros_do_projeto(conn: sqlite3.Connection, projeto_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT pe.id, pe.email, pe.name, m.role, m.created_at
             FROM memberships m JOIN people pe ON pe.id = m.person_id
            WHERE m.project_id = ? ORDER BY m.role, pe.name""",
        (projeto_id,),
    ).fetchall()
