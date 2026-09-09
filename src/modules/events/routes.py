import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from src.modules.events import service as eventos_service
from src.modules.events.relatorio import montar_relatorio, relatorio_markdown
from src.modules.projects.service import exigir_acesso
from src.shared.auth import pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.get("/projetos/{slug}/mudancas")
def ler_mudancas(
    slug: str,
    desde: int = Query(0, ge=0),
    limite: int = Query(200, ge=1, le=2000),
    de_outros: bool = False,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        return {
            "projeto": slug,
            **eventos_service.mudancas_do_projeto(
                conn, projeto["id"], desde, limite, pessoa["id"] if de_outros else None
            ),
        }
    finally:
        conn.close()


@router.get("/projetos/{slug}/relatorio")
def ler_relatorio(
    slug: str,
    desde: int = Query(0, ge=0),
    formato: str = Query("md", pattern="^(md|json)$"),
    com_diff: bool = True,
    pessoa: sqlite3.Row = Depends(pessoa_atual),
):
    conn = conectar()
    try:
        rel = montar_relatorio(conn, slug, pessoa["id"], desde)
        if formato == "json":
            return rel
        return PlainTextResponse(
            relatorio_markdown(conn, rel, com_diff), media_type="text/markdown; charset=utf-8"
        )
    finally:
        conn.close()
