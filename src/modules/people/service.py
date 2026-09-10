import hashlib
import secrets
import sqlite3
from typing import Any

from src.modules.people import repositorio
from src.modules.people.models import PersonPatch, PessoaIn
from src.shared.erros import AlreadyExists, Conflict, Invalid, NotFound


def hash_token(token: str) -> str:
    """SHA-256 direto: o token tem 256 bits de entropia gerada por `secrets`,
    não é senha escolhida por pessoa."""
    return hashlib.sha256(token.encode()).hexdigest()


def alias_de(email: str) -> str:
    """Parte local do email (`arthur.macedo@empresa.com` -> `arthur.macedo`)."""
    return email.split("@")[0].lower()


def create_person(conn: sqlite3.Connection, dados: PessoaIn) -> dict[str, Any]:
    """Cadastra a pessoa sem token - emitir token é ação separada
    (`generate_token`), pra quem ainda não tem."""
    alias = alias_de(dados.email)
    try:
        with conn:
            person_id = repositorio.insert(conn, dados.email, alias, dados.name)
    except sqlite3.IntegrityError:
        raise AlreadyExists(f"Pessoa com email '{dados.email.lower()}' já existe") from None
    return {"id": person_id, "email": dados.email.lower(), "alias": alias, "name": dados.name}


def generate_token(conn: sqlite3.Connection, person_id: int) -> dict[str, Any]:
    """Emite um token novo pra pessoa - primeiro token de quem ainda não tem,
    ou reemissão de quem perdeu o anterior. Invalida o token anterior, se
    havia um."""
    pessoa = repositorio.find_by_id(conn, person_id)
    if pessoa is None:
        raise NotFound(f"Pessoa {person_id} não existe")
    token = secrets.token_urlsafe(32)
    with conn:
        repositorio.update_token(conn, person_id, pessoa["name"], hash_token(token))
    return {
        "id": pessoa["id"],
        "email": pessoa["email"],
        "alias": pessoa["alias"],
        "name": pessoa["name"],
        "token": token,
    }


def list_people(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {**dict(linha), "tem_token": bool(linha["tem_token"])}
        for linha in repositorio.find_all(conn)
    ]


def patch_person(conn: sqlite3.Connection, person_id: int, dados: PersonPatch) -> dict[str, Any]:
    pessoa = repositorio.find_by_id(conn, person_id)
    if pessoa is None:
        raise NotFound(f"Pessoa {person_id} não existe")
    mudancas = dados.model_dump(mode="json", exclude_none=True)
    if not mudancas:
        raise Invalid("Nada pra atualizar")
    if "email" in mudancas:
        mudancas["email"] = mudancas["email"].lower()
        mudancas["alias"] = alias_de(mudancas["email"])
    try:
        with conn:
            repositorio.update_campos(conn, person_id, mudancas)
    except sqlite3.IntegrityError:
        raise AlreadyExists(f"Email '{mudancas.get('email')}' já está em uso") from None
    pessoa = repositorio.find_by_id(conn, person_id)
    return {"id": pessoa["id"], "email": pessoa["email"], "alias": pessoa["alias"], "name": pessoa["name"]}


def delete_person(conn: sqlite3.Connection, person_id: int) -> None:
    if repositorio.find_by_id(conn, person_id) is None:
        raise NotFound(f"Pessoa {person_id} não existe")
    try:
        with conn:
            repositorio.delete(conn, person_id)
    except sqlite3.IntegrityError:
        raise Conflict(
            f"Pessoa {person_id} tem projeto, task ou evento vinculado - não dá pra apagar"
        ) from None
