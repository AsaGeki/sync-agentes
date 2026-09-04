"""Autenticacao e identidade: token unico (TOKEN no .env) + autor do header
`X-Autor-Id`.

`validar_token`/`resolver_autor` sao a logica pura, sem nada de FastAPI -
reaproveitada tanto pelas rotas REST (`exigir_token`/`autor_atual`, que so
leem o `Header()` e convertem o erro pra `HTTPException`) quanto pelas tools
MCP (`app/mcp_server.py`), que leem o mesmo header de outro jeito (via
`ctx.headers` em vez de injecao do FastAPI).
"""

from __future__ import annotations

import secrets
import sqlite3

from fastapi import Header, HTTPException

from app.config import TOKEN
from app.db import conectar


def validar_token(authorization: str | None) -> None:
    esperado = f"Bearer {TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, esperado):
        raise PermissionError("Token ausente ou invalido")


def resolver_autor(autor_id: int | None) -> sqlite3.Row:
    if autor_id is None:
        raise ValueError("autor_id obrigatorio em qualquer escrita")
    conn = conectar()
    try:
        autor = conn.execute("SELECT * FROM autores WHERE id = ?", (autor_id,)).fetchone()
    finally:
        conn.close()
    if autor is None:
        raise LookupError(f"Autor {autor_id} nao cadastrado")
    return autor


def exigir_token(authorization: str | None = Header(None)) -> None:
    try:
        validar_token(authorization)
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc


def autor_atual(x_autor_id: int | None = Header(None, alias="X-Autor-Id")) -> sqlite3.Row:
    try:
        return resolver_autor(x_autor_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
