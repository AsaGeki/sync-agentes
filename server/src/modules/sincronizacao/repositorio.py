import sqlite3

from src.shared.db import now


def find_projeto(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sync_projects WHERE project_id = ?", (project_id,)).fetchone()


def vincular_projeto(conn: sqlite3.Connection, project_id: int, destino_id: str, destino_nome: str) -> None:
    atual = find_projeto(conn, project_id)
    if atual is not None and atual["destino_id"] != destino_id:
        # Os vínculos de repositório valem só para o projeto de destino anterior.
        conn.execute("DELETE FROM sync_repos WHERE project_id = ?", (project_id,))
        conn.execute("UPDATE sync_projects SET repo_padrao = NULL WHERE project_id = ?", (project_id,))
    conn.execute(
        """INSERT INTO sync_projects (project_id, destino_id, destino_nome, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT (project_id) DO UPDATE
             SET destino_id = excluded.destino_id, destino_nome = excluded.destino_nome,
                 updated_at = excluded.updated_at""",
        (project_id, destino_id, destino_nome, now()),
    )


def desvincular_projeto(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM sync_repos WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM sync_projects WHERE project_id = ?", (project_id,))


def set_repo_padrao(conn: sqlite3.Connection, project_id: int, root_sha: str | None) -> None:
    conn.execute(
        "UPDATE sync_projects SET repo_padrao = ?, updated_at = ? WHERE project_id = ?",
        (root_sha, now(), project_id),
    )


def vinculos_repos(conn: sqlite3.Connection, project_id: int) -> dict[str, str]:
    linhas = conn.execute(
        "SELECT root_sha, destino_repo_id FROM sync_repos WHERE project_id = ?", (project_id,)
    ).fetchall()
    return {linha["root_sha"]: linha["destino_repo_id"] for linha in linhas}


def escolhas_tasks(conn: sqlite3.Connection, project_id: int) -> dict[int, str]:
    linhas = conn.execute(
        """SELECT s.task_id, s.root_sha FROM sync_task_repos s
             JOIN tasks t ON t.id = s.task_id WHERE t.project_id = ?""",
        (project_id,),
    ).fetchall()
    return {linha["task_id"]: linha["root_sha"] for linha in linhas}


def salvar_escolhas_tasks(conn: sqlite3.Connection, escolhas: dict[int, str | None]) -> None:
    for task_id, root_sha in escolhas.items():
        if root_sha:
            conn.execute(
                """INSERT INTO sync_task_repos (task_id, root_sha) VALUES (?,?)
                   ON CONFLICT (task_id) DO UPDATE SET root_sha = excluded.root_sha""",
                (task_id, root_sha),
            )
        else:
            conn.execute("DELETE FROM sync_task_repos WHERE task_id = ?", (task_id,))


def substituir_vinculos_repos(conn: sqlite3.Connection, project_id: int, vinculos: dict[str, str]) -> None:
    conn.execute("DELETE FROM sync_repos WHERE project_id = ?", (project_id,))
    conn.executemany(
        "INSERT INTO sync_repos (project_id, root_sha, destino_repo_id) VALUES (?,?,?)",
        [(project_id, root_sha, destino_repo_id) for root_sha, destino_repo_id in vinculos.items()],
    )
