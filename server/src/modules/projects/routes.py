import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.projects import service
from src.modules.projects.models import ConviteIn, PapelIn, ProjetoIn, ProjetoPatch, RepoIn
from src.shared.auth import ContextoGit, contexto_git, exigir_admin, pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.post("/repos/resolve")
def resolve_repo(repo: RepoIn, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> list[dict[str, Any]]:
    """Troca um repositório git pelos projetos afiliados a ele - pode ser mais
    de 1. Repo desconhecido é 404 - use `POST /projetos` pra criar. Não adiciona
    ninguém: cada projeto vem com o `role` da pessoa, ou `null` se ela ainda não
    é membro (`POST /projetos/{slug}/entrar` em `public`, pedido em `private`)."""
    conn = conectar()
    try:
        return service.resolve_repo(conn, pessoa["id"], repo)
    finally:
        conn.close()


@router.post("/projetos", status_code=201)
def create_project(dados: ProjetoIn, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> dict[str, Any]:
    """Cria um projeto novo e afilia o repositório informado a ele. Quem chama
    vira owner."""
    conn = conectar()
    try:
        return service.create_project(conn, pessoa["id"], dados)
    finally:
        conn.close()


@router.post("/projetos/{slug}/entrar", status_code=201)
def join_project(slug: str, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> dict[str, Any]:
    """Entra num projeto `public` sem aprovação. Em `private` é 403: use o pedido."""
    conn = conectar()
    try:
        return service.join_project(conn, slug, pessoa["id"])
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


@router.delete("/projetos/{slug}", status_code=204, dependencies=[Depends(exigir_admin)])
def delete_project(slug: str) -> None:
    """Apaga o projeto e tudo que pendura nele. Só ADMIN_TOKEN - não é ação de
    owner comum."""
    conn = conectar()
    try:
        service.delete_project(conn, slug)
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


@router.patch("/projetos/{slug}/membros/{person_id}")
def set_member_role(
    slug: str, person_id: int, dados: PapelIn, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    """Owner troca o papel de um membro. O projeto nunca fica sem owner."""
    conn = conectar()
    try:
        return service.set_member_role(conn, slug, pessoa["id"], person_id, dados.role)
    finally:
        conn.close()


@router.delete("/projetos/{slug}/membros/{person_id}")
def remove_member(
    slug: str,
    person_id: int,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    """Owner tira um membro (ou qualquer um tira a si mesmo). As tasks dele ficam
    sem dono."""
    conn = conectar()
    try:
        return service.remove_member(conn, slug, pessoa["id"], person_id, ctx)
    finally:
        conn.close()


@router.post("/projetos/{slug}/sair")
def leave_project(
    slug: str,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.leave_project(conn, slug, pessoa["id"], ctx)
    finally:
        conn.close()


@router.post("/projetos/{slug}/pedidos", status_code=201)
def request_access(slug: str, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> dict[str, Any]:
    """Pede acesso de escrita a um projeto `private`. Fica pendente até um
    owner aceitar ou recusar."""
    conn = conectar()
    try:
        return service.request_access(conn, slug, pessoa["id"])
    finally:
        conn.close()


@router.get("/projetos/{slug}/pedidos")
def list_requests(slug: str, pessoa: sqlite3.Row = Depends(pessoa_atual)) -> list[dict[str, Any]]:
    """Pedidos de acesso pendentes deste projeto. Só owner."""
    conn = conectar()
    try:
        return service.list_requests(conn, slug, pessoa["id"])
    finally:
        conn.close()


@router.post("/projetos/{slug}/pedidos/{request_id}/aceitar")
def approve_request(
    slug: str, request_id: int, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.approve_request(conn, slug, pessoa["id"], request_id)
    finally:
        conn.close()


@router.post("/projetos/{slug}/pedidos/{request_id}/recusar")
def reject_request(
    slug: str, request_id: int, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.reject_request(conn, slug, pessoa["id"], request_id)
    finally:
        conn.close()
