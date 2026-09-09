import re
import sqlite3
from typing import Any

from src.modules.people import repositorio as people_repositorio
from src.modules.projects import repositorio
from src.modules.projects.models import ProjetoPatch, RepoIn
from src.shared.enums import ERole, EVisibility
from src.shared.erros import Forbidden, Invalid, NotFound


def _slug_de(nome: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")
    return slug or "projeto"


def _serializar(conn: sqlite3.Connection, projeto: sqlite3.Row) -> dict[str, Any]:
    dados = {k: projeto[k] for k in projeto.keys()}
    dados["repos"] = [dict(r) for r in repositorio.repos_do_projeto(conn, projeto["id"])]
    return dados


def exigir_acesso(conn: sqlite3.Connection, slug: str, person_id: int) -> sqlite3.Row:
    """Porta única de todo acesso a projeto. Sem membership o projeto responde
    404, não 403 - quem não é membro de um projeto privado não deve nem
    descobrir que ele existe."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is None:
        raise NotFound(f"Projeto '{slug}' não existe")
    return projeto


def resolve_repo(
    conn: sqlite3.Connection, person_id: int, repo: RepoIn
) -> dict[str, Any]:
    """Troca um repositório git pelo projeto correspondente - é o que amarra o
    canal ao repo onde o chat foi aberto.

    Repo desconhecido cria o projeto e faz de quem chamou o owner. Repo já
    vinculado devolve o projeto; se a pessoa ainda não é membro, entra sozinha
    quando o projeto é `team` e é barrada quando é `private`.
    """
    projeto = repositorio.find_by_root_sha(conn, repo.root_sha)
    if projeto is None:
        with conn:
            slug = repositorio.slug_livre(conn, _slug_de(repo.name))
            projeto_id = repositorio.insert(conn, slug, repo.name, person_id)
            repositorio.insert_membership(conn, projeto_id, person_id, ERole.owner.value)
            repositorio.insert_repo(conn, projeto_id, repo.root_sha, repo.name, repo.remote)
        projeto = repositorio.find_by_slug(conn, slug)
        return {**_serializar(conn, projeto), "role": ERole.owner.value, "criado": True}

    membership = repositorio.find_membership(conn, projeto["id"], person_id)
    if membership is None:
        if projeto["visibility"] == EVisibility.private.value:
            raise Forbidden(
                f"Projeto '{projeto['slug']}' é privado - peça a um owner pra te adicionar"
            )
        with conn:
            repositorio.insert_membership(conn, projeto["id"], person_id, ERole.member.value)
        role = ERole.member.value
    else:
        role = membership["role"]
    return {**_serializar(conn, projeto), "role": role, "criado": False}


def vincular_repo(
    conn: sqlite3.Connection, slug: str, person_id: int, repo: RepoIn
) -> dict[str, Any]:
    """Aponta mais um repositório pro mesmo projeto (frontend e backend no mesmo
    canal). Repo já vinculado a outro projeto é recusado."""
    projeto = exigir_acesso(conn, slug, person_id)
    dono = repositorio.find_by_root_sha(conn, repo.root_sha)
    if dono is not None and dono["id"] != projeto["id"]:
        raise Invalid(f"Esse repositório já pertence ao projeto '{dono['slug']}'")
    if dono is None:
        with conn:
            repositorio.insert_repo(conn, projeto["id"], repo.root_sha, repo.name, repo.remote)
    return _serializar(conn, projeto)


def list_projects(conn: sqlite3.Connection, person_id: int) -> list[dict[str, Any]]:
    return [
        {**_serializar(conn, linha), "role": linha["role"]}
        for linha in repositorio.find_all_de(conn, person_id)
    ]


def update_project(
    conn: sqlite3.Connection, slug: str, person_id: int, dados: ProjetoPatch
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    mudancas = dados.model_dump(mode="json", exclude_none=True)
    if not mudancas:
        raise Invalid("Nada pra atualizar")
    if "visibility" in mudancas:
        _exigir_owner(conn, projeto["id"], person_id)
    with conn:
        repositorio.update_campos(conn, projeto["id"], mudancas)
    return _serializar(conn, repositorio.find_by_slug(conn, slug))


def _exigir_owner(conn: sqlite3.Connection, projeto_id: int, person_id: int) -> None:
    membership = repositorio.find_membership(conn, projeto_id, person_id)
    if membership is None or membership["role"] != ERole.owner.value:
        raise Forbidden("Só um owner do projeto pode fazer isso")


def list_members(conn: sqlite3.Connection, slug: str, person_id: int) -> list[dict[str, Any]]:
    projeto = exigir_acesso(conn, slug, person_id)
    return [dict(linha) for linha in repositorio.membros_do_projeto(conn, projeto["id"])]


def add_member(
    conn: sqlite3.Connection, slug: str, person_id: int, email: str
) -> dict[str, Any]:
    """Owner adiciona alguém ao projeto - é assim que se entra num projeto
    `private`, que não aceita auto-join."""
    projeto = exigir_acesso(conn, slug, person_id)
    _exigir_owner(conn, projeto["id"], person_id)
    convidado = people_repositorio.find_by_email(conn, email)
    if convidado is None:
        raise NotFound(f"Ninguém cadastrado com o email '{email}'")
    with conn:
        repositorio.insert_membership(
            conn, projeto["id"], convidado["id"], ERole.member.value
        )
    return {"projeto": slug, "email": convidado["email"], "role": ERole.member.value}
