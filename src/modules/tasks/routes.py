import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from src.modules.tasks import service
from src.modules.tasks.models import CorpoIn, MensagemIn, TaskIn, TaskPatch
from src.shared.auth import autor_atual, exigir_token
from src.shared.db import conectar
from src.shared.enums import EStatusTask

router = APIRouter()


# ---------- tasks ---------- #


@router.post("/projetos/{slug}/tasks", status_code=201, dependencies=[Depends(exigir_token)])
async def create_task(
    slug: str, dados: TaskIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.create_task(conn, slug, autor["id"], dados)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks", dependencies=[Depends(exigir_token)])
def list_tasks(
    slug: str,
    status: EStatusTask | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_tasks(conn, slug, status, tag)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{code}", dependencies=[Depends(exigir_token)])
def read_task(slug: str, code: str, com_corpo: bool = True) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.read_task(conn, slug, code, com_corpo)
    finally:
        conn.close()


@router.patch("/projetos/{slug}/tasks/{code}", dependencies=[Depends(exigir_token)])
async def update_task(
    slug: str, code: str, dados: TaskPatch, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.update_task(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


# ---------- conversa ---------- #


@router.post(
    "/projetos/{slug}/tasks/{code}/mensagens",
    status_code=201,
    dependencies=[Depends(exigir_token)],
)
async def create_message(
    slug: str, code: str, dados: MensagemIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.create_message(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


@router.put("/projetos/{slug}/tasks/{code}/corpo", dependencies=[Depends(exigir_token)])
async def update_corpo(
    slug: str, code: str, dados: CorpoIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        return await service.update_corpo(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{code}/diff", dependencies=[Depends(exigir_token)])
def read_diff(slug: str, code: str, desde: int = Query(0, ge=0)) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.read_diff(conn, slug, code, desde)
    finally:
        conn.close()
