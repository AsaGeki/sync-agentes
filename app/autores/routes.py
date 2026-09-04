import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.auth import exigir_token
from app.autores.models import AutorIn
from app.db import agora, conectar
from app.enums import ETipoAutor

router = APIRouter()


@router.post("/autores", status_code=201, dependencies=[Depends(exigir_token)])
def criar_autor(dados: AutorIn) -> dict[str, Any]:
    conn = conectar()
    try:
        if dados.responsavel_id is not None:
            resp = conn.execute(
                "SELECT tipo FROM autores WHERE id = ?", (dados.responsavel_id,)
            ).fetchone()
            if resp is None:
                raise HTTPException(404, f"Responsavel {dados.responsavel_id} nao cadastrado")
            if resp["tipo"] != ETipoAutor.humano.value:
                raise HTTPException(422, "Responsavel de uma IA tem que ser autor do tipo 'humano'")
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO autores (tipo, nome, responsavel_id, criado_em) VALUES (?,?,?,?)",
                    (dados.tipo.value, dados.nome, dados.responsavel_id, agora()),
                )
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Ja existe autor com o nome '{dados.nome}'") from None
        return {"id": cursor.lastrowid, **dados.model_dump(mode="json")}
    finally:
        conn.close()


@router.get("/autores", dependencies=[Depends(exigir_token)])
def listar_autores() -> list[dict[str, Any]]:
    conn = conectar()
    try:
        linhas = conn.execute(
            """SELECT a.id, a.tipo, a.nome, a.responsavel_id, r.nome AS responsavel, a.criado_em
                 FROM autores a LEFT JOIN autores r ON r.id = a.responsavel_id
                ORDER BY a.id"""
        ).fetchall()
        return [dict(linha) for linha in linhas]
    finally:
        conn.close()
