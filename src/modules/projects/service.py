import re
import sqlite3
from typing import Any

from src.modules.people import repositorio as people_repositorio
from src.modules.projects import repositorio
from src.modules.projects.models import ProjetoIn, ProjetoPatch, RepoIn
from src.shared.enums import ERequestStatus, ERole, EVisibility
from src.shared.erros import AlreadyExists, Forbidden, Invalid, NotFound


def _slug_de(nome: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-")
    return slug or "projeto"


def _serializar(conn: sqlite3.Connection, projeto: sqlite3.Row) -> dict[str, Any]:
    dados = {k: projeto[k] for k in projeto.keys()}
    dados["repos"] = [dict(r) for r in repositorio.repos_do_projeto(conn, projeto["id"])]
    criador = people_repositorio.find_by_id(conn, projeto["created_by"])
    dados["created_by"] = criador["email"] if criador else None
    return dados


def exigir_acesso(conn: sqlite3.Connection, slug: str, person_id: int) -> sqlite3.Row:
    """Porta única de todo acesso a projeto. Sem membership responde 404, não
    403: quem não é membro não descobre que o projeto existe."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is None:
        raise NotFound(f"Projeto '{slug}' não existe")
    return projeto


def resolve_repo(
    conn: sqlite3.Connection, person_id: int, repo: RepoIn
) -> list[dict[str, Any]]:
    """Troca um repositório git pelos projetos afiliados a ele - pode ser mais
    de 1 (mesmo repositório servindo assuntos diferentes). Nunca cria projeto -
    repo desconhecido é 404 (`create_project` cria explícito, ou um membro de
    projeto existente linka com `POST /projetos/{slug}/repos`).

    Cada projeto devolvido: `team` e quem ainda não é membro entra sozinho;
    `private` devolve com `role: null` - acesso de escrita é por
    `request_access`, não por só ter o repositório.
    """
    projetos = repositorio.find_all_by_root_sha(conn, repo.root_sha)
    if not projetos:
        raise NotFound(
            f"Nenhum projeto afiliado a este repositório ('{repo.name}', sha "
            f"{repo.root_sha[:7]}). Crie um projeto pra ele (`create_project`), ou peça "
            f"pra um membro de um projeto existente rodar POST /projetos/{{slug}}/repos "
            f"com root_sha='{repo.root_sha}' e name='{repo.name}'."
        )

    resultado = []
    with conn:
        for projeto in projetos:
            membership = repositorio.find_membership(conn, projeto["id"], person_id)
            if membership is not None:
                role = membership["role"]
            elif projeto["visibility"] == EVisibility.team.value:
                repositorio.insert_membership(conn, projeto["id"], person_id, ERole.member.value)
                role = ERole.member.value
            else:
                role = None
            resultado.append({**_serializar(conn, projeto), "role": role})
    return resultado


def create_project(conn: sqlite3.Connection, person_id: int, dados: ProjetoIn) -> dict[str, Any]:
    """Cria um projeto e já afilia o repositório informado a ele, quem chamou
    vira owner. O repositório pode já estar afiliado a outro(s) projeto(s) -
    isso só soma mais um vínculo."""
    with conn:
        slug = repositorio.slug_livre(conn, _slug_de(dados.name))
        projeto_id = repositorio.insert(
            conn, slug, dados.name, person_id, dados.description, dados.visibility.value
        )
        repositorio.insert_membership(conn, projeto_id, person_id, ERole.owner.value)
        repositorio.insert_repo(conn, projeto_id, dados.repo.root_sha, dados.repo.name, dados.repo.remote)
    projeto = repositorio.find_by_slug(conn, slug)
    return {**_serializar(conn, projeto), "role": ERole.owner.value}


def vincular_repo(
    conn: sqlite3.Connection, slug: str, person_id: int, repo: RepoIn
) -> dict[str, Any]:
    """Aponta mais um repositório pro projeto. O mesmo repositório pode estar
    em outro(s) projeto(s) também - isso não bloqueia. Vincular um repo que já
    está neste projeto é idempotente."""
    projeto = exigir_acesso(conn, slug, person_id)
    if repositorio.find_repo_link(conn, repo.root_sha, projeto["id"]) is None:
        with conn:
            repositorio.insert_repo(conn, projeto["id"], repo.root_sha, repo.name, repo.remote)
    return _serializar(conn, projeto)


def list_projects(conn: sqlite3.Connection, person_id: int) -> list[dict[str, Any]]:
    """Todo projeto, `team` e `private` - existência é pública. Escrever no
    conteúdo continua exigindo membership (`exigir_acesso`)."""
    return [
        {**_serializar(conn, linha), "role": linha["role"]}
        for linha in repositorio.find_all(conn, person_id)
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


def delete_project(conn: sqlite3.Connection, slug: str) -> None:
    """Apaga o projeto e tudo que pendura nele (repos, membros, pedidos, tasks,
    eventos - `ON DELETE CASCADE`). Só admin - não é ação de owner."""
    projeto = repositorio.find_by_slug(conn, slug)
    with conn:
        repositorio.delete(conn, projeto["id"])


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
    """Owner adiciona alguém ao projeto. É o único jeito de entrar num projeto
    `private`."""
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


def request_access(conn: sqlite3.Connection, slug: str, person_id: int) -> dict[str, Any]:
    """Pede acesso de escrita a um projeto `private`. Fica pendente até um
    owner aceitar ou recusar (`list_requests`/aceitar/recusar)."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is not None:
        raise AlreadyExists("Você já é membro deste projeto")
    if repositorio.find_pending_request(conn, projeto["id"], person_id) is not None:
        raise AlreadyExists("Já existe um pedido seu pendente pra este projeto")
    with conn:
        request_id = repositorio.insert_request(conn, projeto["id"], person_id)
    return {"id": request_id, "projeto": slug, "status": ERequestStatus.pending.value}


def list_requests(conn: sqlite3.Connection, slug: str, person_id: int) -> list[dict[str, Any]]:
    projeto = exigir_acesso(conn, slug, person_id)
    _exigir_owner(conn, projeto["id"], person_id)
    return [dict(linha) for linha in repositorio.pending_requests_do_projeto(conn, projeto["id"])]


def _resolver_request(
    conn: sqlite3.Connection, slug: str, person_id: int, request_id: int, aceitar: bool
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    _exigir_owner(conn, projeto["id"], person_id)
    pedido = repositorio.find_request(conn, projeto["id"], request_id)
    if pedido is None or pedido["status"] != ERequestStatus.pending.value:
        raise NotFound(f"Pedido {request_id} não existe ou já foi resolvido")
    status = ERequestStatus.accepted.value if aceitar else ERequestStatus.rejected.value
    with conn:
        repositorio.resolve_request(conn, request_id, status)
        if aceitar:
            repositorio.insert_membership(conn, projeto["id"], pedido["person_id"], ERole.member.value)
    return {"id": request_id, "status": status}


def approve_request(
    conn: sqlite3.Connection, slug: str, person_id: int, request_id: int
) -> dict[str, Any]:
    return _resolver_request(conn, slug, person_id, request_id, aceitar=True)


def reject_request(
    conn: sqlite3.Connection, slug: str, person_id: int, request_id: int
) -> dict[str, Any]:
    return _resolver_request(conn, slug, person_id, request_id, aceitar=False)
