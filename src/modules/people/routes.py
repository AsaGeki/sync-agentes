import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.people import service
from src.modules.people.models import PessoaIn
from src.shared.auth import exigir_admin, pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.post("/people", status_code=201, dependencies=[Depends(exigir_admin)])
def emit_token(dados: PessoaIn) -> dict[str, Any]:
    """Cadastra a pessoa e devolve o token pessoal dela. O token aparece só
    nesta resposta; chamar de novo com o mesmo email emite outro e invalida o
    anterior."""
    conn = conectar()
    try:
        return service.emit_token(conn, dados)
    finally:
        conn.close()


# Lista com o email de todo mundo é de administração. Quem só quer saber quem
# está num projeto usa GET /projetos/{slug}/membros.
@router.get("/people", dependencies=[Depends(exigir_admin)])
def list_people() -> list[dict[str, Any]]:
    conn = conectar()
    try:
        return service.list_people(conn)
    finally:
        conn.close()


@router.get("/me")
def me(pessoa: sqlite3.Row = Depends(pessoa_atual)) -> dict[str, Any]:
    return {
        "id": pessoa["id"],
        "email": pessoa["email"],
        "alias": pessoa["alias"],
        "name": pessoa["name"],
    }
