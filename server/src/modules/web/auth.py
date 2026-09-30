"""Sessão da interface web: o próprio token vai num cookie `httpOnly`.

`sa_pessoa` guarda o token pessoal e `sa_admin` o `ADMIN_TOKEN`; são
independentes, dá pra estar nos dois ao mesmo tempo. `SameSite=Strict` é o que
barra escrita disparada de outro site.
"""

import sqlite3

from fastapi import Request, Response

from src.shared.auth import resolve_person, validate_admin
from src.shared.erros import Unauthorized

COOKIE_PESSOA = "sa_pessoa"
COOKIE_ADMIN = "sa_admin"
VALIDADE_COOKIE = 30 * 24 * 3600


def gravar_cookie(resposta: Response, nome: str, token: str) -> None:
    resposta.set_cookie(
        nome, token, max_age=VALIDADE_COOKIE, path="/web", httponly=True, samesite="strict"
    )


def apagar_cookie(resposta: Response, nome: str) -> None:
    resposta.delete_cookie(nome, path="/web", httponly=True, samesite="strict")


def pessoa_web(request: Request) -> sqlite3.Row:
    token = request.cookies.get(COOKIE_PESSOA)
    if not token:
        raise Unauthorized("Faça login com seu token")
    return resolve_person(f"Bearer {token}")


def admin_web(request: Request) -> None:
    token = request.cookies.get(COOKIE_ADMIN)
    if not token:
        raise Unauthorized("Faça login com o token de administração")
    validate_admin(f"Bearer {token}")
