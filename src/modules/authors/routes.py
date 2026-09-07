from typing import Any

from fastapi import APIRouter, Depends

from src.modules.authors import service
from src.modules.authors.models import AutorIn
from src.shared.auth import exigir_token
from src.shared.db import conectar

router = APIRouter()


@router.post("/authors", status_code=201, dependencies=[Depends(exigir_token)])
def create_author(dados: AutorIn) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.create_author(conn, dados)
    finally:
        conn.close()


@router.get("/authors", dependencies=[Depends(exigir_token)])
def list_authors() -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_authors(conn)
    finally:
        conn.close()
