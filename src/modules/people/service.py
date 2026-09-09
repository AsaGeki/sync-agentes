import hashlib
import secrets
import sqlite3
from typing import Any

from src.modules.people import repositorio
from src.modules.people.models import PessoaIn


def hash_token(token: str) -> str:
    """Token é gerado por `secrets` (256 bits), não escolhido por humano - SHA-256
    direto basta, KDF com salt aqui só protegeria contra dicionário, que não
    existe nesse espaço de busca."""
    return hashlib.sha256(token.encode()).hexdigest()


def alias_de(email: str) -> str:
    """Assinatura curta da pessoa: a parte local do email do git
    (`arthur.macedo@empresa.com` -> `arthur.macedo`)."""
    return email.split("@")[0].lower()


def emit_token(conn: sqlite3.Connection, dados: PessoaIn) -> dict[str, Any]:
    """Cadastra a pessoa (ou reaproveita quem já existe com esse email) e emite
    um token novo pra ela. O token em texto puro só existe nesta resposta - o
    banco guarda o hash; emitir de novo invalida o anterior."""
    token = secrets.token_urlsafe(32)
    alias = alias_de(dados.email)
    existente = repositorio.find_by_email(conn, dados.email)
    with conn:
        if existente is None:
            person_id = repositorio.insert(
                conn, dados.email, alias, dados.name, hash_token(token)
            )
        else:
            person_id = existente["id"]
            repositorio.update_token(conn, person_id, dados.name, hash_token(token))
    return {
        "id": person_id,
        "email": dados.email.lower(),
        "alias": alias,
        "name": dados.name,
        "token": token,
        "novo": existente is None,
    }


def list_people(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {**dict(linha), "tem_token": bool(linha["tem_token"])}
        for linha in repositorio.find_all(conn)
    ]
