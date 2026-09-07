import json
import sqlite3
from typing import Any

from src.modules.projects import repositorio
from src.modules.projects.models import ProjetoIn, ProjetoPatch
from src.shared.erros import AlreadyExists, Invalid


def _serializar(projeto: sqlite3.Row) -> dict[str, Any]:
    dados = dict(projeto)
    dados["git_repositories"] = json.loads(dados["git_repositories"])
    return dados


def create_project(conn: sqlite3.Connection, dados: ProjetoIn, created_by: int) -> dict[str, Any]:
    try:
        with conn:
            projeto_id = repositorio.insert(conn, dados, created_by)
    except sqlite3.IntegrityError:
        raise AlreadyExists(f"Projeto '{dados.slug}' já existe") from None
    return {"id": projeto_id, "created_by": created_by, **dados.model_dump(mode="json")}


def list_projects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_serializar(linha) for linha in repositorio.find_all(conn)]


def update_project(conn: sqlite3.Connection, slug: str, dados: ProjetoPatch) -> dict[str, Any]:
    projeto = repositorio.find_by_slug(conn, slug)
    mudancas = dados.model_dump(mode="json", exclude_none=True)
    if not mudancas:
        raise Invalid("Nada pra atualizar")
    with conn:
        repositorio.update_campos(conn, projeto["id"], mudancas)
    return _serializar(repositorio.find_by_slug(conn, slug))
