import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import exigir_token
from app.db import agora, conectar
from app.projetos.models import ProjetoIn, ProjetoPatch
from app.projetos.service import buscar_projeto

router = APIRouter()


@router.post("/projetos", status_code=201, dependencies=[Depends(exigir_token)])
def criar_projeto(dados: ProjetoIn) -> dict[str, Any]:
    conn = conectar()
    try:
        try:
            with conn:
                cursor = conn.execute(
                    """INSERT INTO projetos
                       (slug, nome, descricao, status, criado_em, atualizado_em)
                       VALUES (?,?,?,?,?,?)""",
                    (dados.slug, dados.nome, dados.descricao, dados.status.value, agora(), agora()),
                )
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Projeto '{dados.slug}' ja existe") from None
        return {"id": cursor.lastrowid, **dados.model_dump(mode="json")}
    finally:
        conn.close()


@router.get("/projetos", dependencies=[Depends(exigir_token)])
def listar_projetos() -> list[dict[str, Any]]:
    conn = conectar()
    try:
        linhas = conn.execute(
            """SELECT p.*,
                      (SELECT COUNT(*) FROM tasks   t WHERE t.projeto_id = p.id) AS tasks,
                      (SELECT MAX(seq) FROM eventos e WHERE e.projeto_id = p.id) AS cursor
                 FROM projetos p ORDER BY p.id"""
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        conn.close()


@router.patch("/projetos/{slug}", dependencies=[Depends(exigir_token)])
def atualizar_projeto(slug: str, dados: ProjetoPatch) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        mudancas = dados.model_dump(mode="json", exclude_none=True)
        if not mudancas:
            raise HTTPException(422, "Nada pra atualizar")
        with conn:
            for campo, valor in mudancas.items():
                conn.execute(
                    f"UPDATE projetos SET {campo} = ? WHERE id = ?", (valor, projeto["id"])
                )
            conn.execute(
                "UPDATE projetos SET atualizado_em = ? WHERE id = ?", (agora(), projeto["id"])
            )
        return dict(buscar_projeto(conn, slug))
    finally:
        conn.close()
