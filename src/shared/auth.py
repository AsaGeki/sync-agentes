"""Autenticação por token pessoal.

Token não é mais compartilhado: cada pessoa tem o seu, emitido por `POST /people`
(protegido pelo `ADMIN_TOKEN` do `.env`). Quem assina um evento é a pessoa dona do
token que veio no `Authorization` - não um header que o cliente escolhe. A
ferramenta usada (`X-Agent`) e o ponto do git (`X-Git-Branch`/`X-Git-Commit`) são
metadado do evento, não identidade.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

from fastapi import Header

from src.modules.people import repositorio as people_repositorio
from src.modules.people.service import hash_token
from src.shared.config import ADMIN_TOKEN
from src.shared.db import conectar
from src.shared.enums import EAgent
from src.shared.erros import Unauthorized


@dataclass(frozen=True)
class ContextoGit:
    """De onde a escrita saiu. Preenchido pelo bridge a partir do repo do chat."""

    agent: EAgent = EAgent.outro
    branch: str | None = None
    commit_sha: str | None = None


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Token ausente ou malformado")
    return authorization[7:].strip()


def validate_admin(authorization: str | None) -> None:
    if not secrets.compare_digest(_bearer(authorization), ADMIN_TOKEN):
        raise Unauthorized("Token de administração inválido")


def resolve_person(authorization: str | None) -> sqlite3.Row:
    token_hash = hash_token(_bearer(authorization))
    conn = conectar()
    try:
        pessoa = people_repositorio.find_by_token_hash(conn, token_hash)
    finally:
        conn.close()
    if pessoa is None:
        raise Unauthorized("Token não corresponde a nenhuma pessoa cadastrada")
    return pessoa


def exigir_admin(authorization: str | None = Header(None)) -> None:
    validate_admin(authorization)


def pessoa_atual(authorization: str | None = Header(None)) -> sqlite3.Row:
    return resolve_person(authorization)


def contexto_git(
    x_agent: str | None = Header(None, alias="X-Agent"),
    x_git_branch: str | None = Header(None, alias="X-Git-Branch"),
    x_git_commit: str | None = Header(None, alias="X-Git-Commit"),
) -> ContextoGit:
    return ContextoGit(
        agent=normalizar_agent(x_agent),
        branch=x_git_branch,
        commit_sha=x_git_commit,
    )


def normalizar_agent(bruto: str | None) -> EAgent:
    """Casa o nome que o cliente MCP se dá (`clientInfo.name`: 'claude-code',
    'Codex CLI', 'cursor-vscode'...) com um valor conhecido. Nome não
    reconhecido vira 'outro' - o evento continua válido, só não sabemos a
    ferramenta."""
    if not bruto:
        return EAgent.outro
    texto = bruto.lower()
    for agent in (EAgent.claude, EAgent.codex, EAgent.cursor, EAgent.copilot):
        if agent.value in texto:
            return agent
    return EAgent.outro
