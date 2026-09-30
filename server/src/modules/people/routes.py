import sqlite3
from typing import Any

from fastapi import APIRouter, Depends

from src.modules.people import service
from src.modules.people.models import PersonPatch, PessoaIn
from src.shared.auth import exigir_admin, pessoa_atual
from src.shared.db import conectar

router = APIRouter()


@router.post("/people", status_code=201, dependencies=[Depends(exigir_admin)])
def create_person(dados: PessoaIn) -> dict[str, Any]:
    """Cadastra a pessoa, sem token. Emitir token é `POST /people/{id}/token`."""
    conn = conectar()
    try:
        return service.create_person(conn, dados)
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


@router.patch("/people/{person_id}", dependencies=[Depends(exigir_admin)])
def patch_person(person_id: int, dados: PersonPatch) -> dict[str, Any]:
    conn = conectar()
    try:
        return service.patch_person(conn, person_id, dados)
    finally:
        conn.close()


@router.delete("/people/{person_id}", status_code=204, dependencies=[Depends(exigir_admin)])
def delete_person(person_id: int) -> None:
    conn = conectar()
    try:
        service.delete_person(conn, person_id)
    finally:
        conn.close()


@router.post("/people/{person_id}/token", dependencies=[Depends(exigir_admin)])
def generate_token(person_id: int) -> dict[str, Any]:
    """Emite um token novo - primeiro de quem ainda não tem, ou reemissão de
    quem perdeu o anterior. O texto puro aparece só nesta resposta - o banco
    guarda o hash, e emitir de novo invalida o anterior."""
    conn = conectar()
    try:
        return service.generate_token(conn, person_id)
    finally:
        conn.close()
