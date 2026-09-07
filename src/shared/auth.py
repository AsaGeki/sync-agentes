from __future__ import annotations

import secrets
import sqlite3

from fastapi import Header

from src.modules.authors import repositorio as autores_repositorio
from src.shared.config import TOKEN
from src.shared.db import conectar
from src.shared.erros import MissingRequirement, NotFound, Unauthorized


def validate_token(authorization: str | None) -> None:
    esperado = f"Bearer {TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, esperado):
        raise Unauthorized("Token ausente ou inválido")


def resolve_author(autor_id: int | None) -> sqlite3.Row:
    if autor_id is None:
        raise MissingRequirement("autor_id obrigatório em qualquer escrita")
    conn = conectar()
    try:
        autor = autores_repositorio.find_by_id(conn, autor_id)
    finally:
        conn.close()
    if autor is None:
        raise NotFound(f"Autor {autor_id} não cadastrado")
    return autor


def exigir_token(authorization: str | None = Header(None)) -> None:
    validate_token(authorization)


def autor_atual(x_autor_id: int | None = Header(None, alias="X-Autor-Id")) -> sqlite3.Row:
    return resolve_author(x_autor_id)
