import json
import sqlite3

from fastapi.responses import Response

from src.modules.projects.exportacao import exportar
from src.shared.erros import Invalid


def baixar_projeto(conn: sqlite3.Connection, projeto: sqlite3.Row, repositorio: str) -> Response:
    repo = conn.execute(
        "SELECT 1 FROM project_repos WHERE project_id = ? AND root_sha = ?",
        (projeto["id"], repositorio),
    ).fetchone()
    if repo is None:
        raise Invalid("Escolha um repositório vinculado ao projeto.")
    try:
        pacote = exportar(conn, projeto, repositorio)
    except ValueError as erro:
        raise Invalid(str(erro)) from erro
    return Response(
        content=json.dumps(pacote, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="project-tasks-{projeto["slug"]}.json"',
            "Cache-Control": "no-store",
        },
    )
