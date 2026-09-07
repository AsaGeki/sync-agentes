from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from src.modules.events import service as eventos_service
from src.modules.events.relatorio import montar_relatorio, relatorio_markdown
from src.modules.projects import repositorio as projetos_repositorio
from src.shared.auth import exigir_token
from src.shared.db import conectar

router = APIRouter()


@router.get("/projetos/{slug}/mudancas", dependencies=[Depends(exigir_token)])
def ler_mudancas(
    slug: str, desde: int = Query(0, ge=0), limite: int = Query(200, ge=1, le=2000)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = projetos_repositorio.find_by_slug(conn, slug)
        return {
            "projeto": slug,
            **eventos_service.mudancas_do_projeto(conn, projeto["id"], desde, limite),
        }
    finally:
        conn.close()


@router.get("/projetos/{slug}/relatorio", dependencies=[Depends(exigir_token)])
def ler_relatorio(
    slug: str,
    desde: int = Query(0, ge=0),
    formato: str = Query("md", pattern="^(md|json)$"),
    com_diff: bool = True,
):
    conn = conectar()
    try:
        rel = montar_relatorio(conn, slug, desde)
        if formato == "json":
            return rel
        return PlainTextResponse(
            relatorio_markdown(conn, rel, com_diff), media_type="text/markdown; charset=utf-8"
        )
    finally:
        conn.close()
