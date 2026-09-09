import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.modules.tasks import service
from src.modules.tasks.models import CorpoIn, DiffIn, MensagemIn, TaskIn, TaskPatch
from src.shared.auth import ContextoGit, contexto_git, pessoa_atual
from src.shared.db import conectar
from src.shared.enums import EStatusTask

router = APIRouter()


# ---------- tasks ---------- #


@router.post("/projetos/{slug}/tasks", status_code=201)
async def create_task(
    slug: str,
    dados: TaskIn,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.create_task(conn, slug, pessoa["id"], ctx, dados)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks")
def list_tasks(
    slug: str,
    status: EStatusTask | None = None,
    tag: str | None = None,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_tasks(conn, slug, pessoa["id"], status, tag)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{code}")
def read_task(
    slug: str,
    code: str,
    com_corpo: bool = True,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.read_task(conn, slug, pessoa["id"], code, com_corpo)
    finally:
        conn.close()


@router.patch("/projetos/{slug}/tasks/{code}")
async def update_task(
    slug: str,
    code: str,
    dados: TaskPatch,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.update_task(conn, slug, code, pessoa["id"], ctx, dados)
    finally:
        conn.close()


# ---------- conversa ---------- #


@router.post("/projetos/{slug}/tasks/{code}/mensagens", status_code=201)
async def create_message(
    slug: str,
    code: str,
    dados: MensagemIn,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.create_message(conn, slug, code, pessoa["id"], ctx, dados)
    finally:
        conn.close()


@router.put("/projetos/{slug}/tasks/{code}/corpo")
async def update_corpo(
    slug: str,
    code: str,
    dados: CorpoIn,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.update_corpo(conn, slug, code, pessoa["id"], ctx, dados)
    finally:
        conn.close()


@router.post("/projetos/{slug}/tasks/{code}/diffs", status_code=201)
async def publish_diff(
    slug: str,
    code: str,
    dados: DiffIn,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
    ctx: ContextoGit = Depends(contexto_git),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.publish_diff(conn, slug, code, pessoa["id"], ctx, dados)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{code}/diffs")
def list_diffs(
    slug: str, code: str, pessoa: sqlite3.Row = Depends(pessoa_atual)
) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_diffs(conn, slug, pessoa["id"], code)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{code}/corpo/diff")
def read_body_diff(
    slug: str,
    code: str,
    desde: int = Query(0, ge=0),
    pessoa: sqlite3.Row = Depends(pessoa_atual),
) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.read_diff(conn, slug, pessoa["id"], code, desde)
    finally:
        conn.close()
