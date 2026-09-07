import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.projects import service
from src.modules.projects.models import ProjetoIn, ProjetoPatch
from src.shared.auth import autor_atual, exigir_token
from src.shared.db import conectar

router = APIRouter()


@router.post("/projetos", status_code=201, dependencies=[Depends(exigir_token)])
def create_project(dados: ProjetoIn, autor: sqlite3.Row = Depends(autor_atual)) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.create_project(conn, dados, autor["id"])
    finally:
        conn.close()


@router.get("/projetos", dependencies=[Depends(exigir_token)])
def list_projects() -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_projects(conn)
    finally:
        conn.close()


@router.patch("/projetos/{slug}", dependencies=[Depends(exigir_token)])
def update_project(slug: str, dados: ProjetoPatch) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.update_project(conn, slug, dados)
    finally:
        conn.close()
