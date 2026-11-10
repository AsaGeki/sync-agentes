import hashlib
import json
import re
import sqlite3

from fastapi.responses import Response

from src.modules.projects.exportacao import exportar
from src.shared.erros import Invalid


def preparar(conn: sqlite3.Connection, projeto: sqlite3.Row) -> dict:
    repos = conn.execute(
        "SELECT root_sha, name FROM project_repos WHERE project_id = ? ORDER BY name, root_sha", (projeto["id"],)
    ).fetchall()
    tasks = conn.execute(
        "SELECT t.id, t.code, t.title, t.tags, t.feature_id, t.updated_at, f.title AS feature "
        "FROM tasks t LEFT JOIN features f ON f.id = t.feature_id WHERE t.project_id = ? ORDER BY t.id",
        (projeto["id"],),
    ).fetchall()
    resultado = []
    for task in tasks:
        tags = json.loads(task["tags"])
        candidatas = []
        for repo in repos:
            palavras = set(re.split(r"[^a-z0-9]+", repo["name"].lower()))
            motivos = [tag for tag in tags if tag.lower() == repo["name"].lower()]
            if not motivos:
                motivos = [
                    tag
                    for tag in tags
                    if tag.lower() in ("backend", "frontend", "front")
                    and (
                        (tag.lower() == "backend" and bool(palavras & {"back", "backend"}))
                        or (tag.lower() in ("frontend", "front") and bool(palavras & {"front", "frontend"}))
                    )
                ]
            if motivos:
                candidatas.append((repo, motivos))
        sugestao = candidatas[0] if len(candidatas) == 1 else None
        resultado.append(
            {
                **dict(task),
                "tags": tags,
                "sugestao": sugestao[0]["root_sha"] if sugestao else "",
                "motivo": f"Tag {', '.join(sugestao[1])} corresponde a {sugestao[0]['name']}" if sugestao else "",
            }
        )
    features = conn.execute(
        "SELECT id, title FROM features WHERE project_id = ? ORDER BY title, id", (projeto["id"],)
    ).fetchall()
    snapshot = hashlib.sha256(
        json.dumps([[list(r) for r in repos], [list(t) for t in tasks]], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "repos": repos,
        "tasks": resultado,
        "features": features,
        "tags": sorted({tag for t in resultado for tag in t["tags"]}),
        "snapshot": snapshot,
    }


def baixar_projeto(conn: sqlite3.Connection, projeto: sqlite3.Row, dados) -> Response:
    snapshots = dados.getlist("snapshot")
    if len(snapshots) != 1 or snapshots[0] != preparar(conn, projeto)["snapshot"]:
        raise Invalid("As tasks ou repositórios mudaram. Reabra a exportação e revise as escolhas.")
    repos_por_task = {}
    for chave, valor in dados.multi_items():
        if chave == "snapshot":
            continue
        if (
            not isinstance(valor, str)
            or not chave.startswith("task_")
            or not chave[5:].isdigit()
            or chave[5:] != str(int(chave[5:]))
        ):
            raise Invalid("Dados da exportação inválidos. Reabra a página e tente novamente.")
        task_id = int(chave[5:])
        if task_id in repos_por_task:
            raise Invalid("Uma task foi enviada mais de uma vez. Reabra a página e tente novamente.")
        repos_por_task[task_id] = valor
    try:
        pacote = exportar(conn, projeto, repos_por_task)
    except ValueError as erro:
        raise Invalid(str(erro)) from erro
    return Response(
        content=json.dumps(pacote, ensure_ascii=False, indent=2).encode("utf-8"),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="exportacao-{projeto["slug"]}.json"',
            "Cache-Control": "no-store",
        },
    )
