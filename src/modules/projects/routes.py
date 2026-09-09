import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.projects import service
from src.modules.projects.models import ConviteIn, ProjetoPatch, RepoIn
from src.shared.auth import pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.post("/repos/resolve")
def resolve_repo(repo: RepoIn, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> dict[str, Any]:
    """Troca um repositório git pelo projeto dele. Repo desconhecido cria o
    projeto; repo conhecido devolve o projeto e entra como membro se ele for
    `team`."""
    conn = conectar()
    try:
        return service.resolve_repo(conn, pessoa["id"], repo)
    finally:
        conn.close()


@router.post("/projetos/{slug}/repos", status_code=201)
def vincular_repo(
    slug: str, repo: RepoIn, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.vincular_repo(conn, slug, pessoa["id"], repo)
    finally:
        conn.close()


@router.get("/projetos")
def list_projects(pessoa: sqlite3.Row = Depends(pessoa_atual)) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_projects(conn, pessoa["id"])
    finally:
        conn.close()


@router.patch("/projetos/{slug}")
def update_project(
    slug: str, dados: ProjetoPatch, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.update_project(conn, slug, pessoa["id"], dados)
    finally:
        conn.close()


@router.get("/projetos/{slug}/membros")
def list_members(slug: str, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_members(conn, slug, pessoa["id"])
    finally:
        conn.close()


@router.post("/projetos/{slug}/membros", status_code=201)
def add_member(
    slug: str, dados: ConviteIn, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.add_member(conn, slug, pessoa["id"], dados.email)
    finally:
        conn.close()
