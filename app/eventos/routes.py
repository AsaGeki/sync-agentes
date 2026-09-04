from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from app.auth import exigir_token
from app.db import conectar
from app.eventos.relatorio import montar_relatorio, relatorio_markdown
from app.eventos.service import hidratar_evento
from app.projetos.service import buscar_projeto

router = APIRouter()


@router.get("/projetos/{slug}/mudancas", dependencies=[Depends(exigir_token)])
def ler_mudancas(
    slug: str, desde: int = Query(0, ge=0), limite: int = Query(200, ge=1, le=2000)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        linhas = conn.execute(
            "SELECT seq FROM eventos WHERE projeto_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (projeto["id"], desde, limite),
        ).fetchall()
        eventos = [hidratar_evento(conn, r["seq"]) for r in linhas]
        return {
            "projeto": slug,
            "desde": desde,
            "cursor": eventos[-1]["seq"] if eventos else desde,
            "total": len(eventos),
            "eventos": eventos,
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
