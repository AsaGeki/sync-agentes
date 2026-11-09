import re
import sqlite3
import unicodedata
from typing import Any

from src.modules.events import service as eventos_service
from src.modules.events.bus import publish
from src.modules.people import repositorio as people_repositorio
from src.modules.projects import repositorio
from src.modules.projects.models import ProjetoIn, ProjetoPatch, RepoIn
from src.modules.tasks import repositorio as tasks_repositorio
from src.shared.auth import ContextoGit
from src.shared.enums import EKindEvent, ERequestStatus, ERole, EStatusProject, EVisibility
from src.shared.erros import AlreadyExists, Conflict, Forbidden, Invalid, NotFound


def _slug_de(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")
    return slug or "projeto"


def _serializar(conn: sqlite3.Connection, projeto: sqlite3.Row) -> dict[str, Any]:
    dados = {k: projeto[k] for k in projeto.keys()}
    dados["repos"] = [dict(r) for r in repositorio.repos_do_projeto(conn, projeto["id"])]
    criador = people_repositorio.find_by_id(conn, projeto["created_by"])
    dados["created_by"] = criador["email"] if criador else None
    return dados


def _serializar_com_role(conn: sqlite3.Connection, projeto: sqlite3.Row, role: str | None) -> dict[str, Any]:
    """Igual `_serializar`, mas pra resposta que pode ir pra quem não é membro
    (`role: null`) - repositórios vinculados e quem criou são conteúdo, não
    existência, então somem pra quem não tem acesso."""
    dados = _serializar(conn, projeto)
    if role is None:
        dados.pop("repos", None)
        dados.pop("created_by", None)
    dados["role"] = role
    return dados


def exigir_acesso(conn: sqlite3.Connection, slug: str, person_id: int) -> sqlite3.Row:
    """Porta única de todo acesso a projeto. Sem membership responde 404, não
    403: quem não é membro não descobre que o projeto existe."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is None:
        raise NotFound(f"Projeto '{slug}' não existe")
    return projeto


def exigir_escrita(conn: sqlite3.Connection, slug: str, person_id: int) -> sqlite3.Row:
    """`exigir_acesso` para quem vai escrever: projeto arquivado só se lê."""
    projeto = exigir_acesso(conn, slug, person_id)
    if projeto["status"] == EStatusProject.arquivado:
        raise Conflict(
            f"Projeto '{slug}' está arquivado e só aceita leitura - "
            "reative com update_project(status='ativo') antes de escrever."
        )
    return projeto


def resolve_repo(
    conn: sqlite3.Connection, person_id: int, repo: RepoIn
) -> list[dict[str, Any]]:
    """Troca um repositório git pelos projetos afiliados a ele - pode ser mais
    de 1 (mesmo repositório servindo assuntos diferentes). Nunca cria projeto -
    repo desconhecido é 404 (`create_project` cria explícito, ou um membro de
    projeto existente linka com `POST /projetos/{slug}/repos`).

    Cada projeto devolvido leva o `role` da pessoa, ou `null` se ela ainda não é
    membro: ter o repositório não adiciona ninguém. Em projeto `public` entra-se
    com `join_project`; em `private`, com `request_access` e aceite de um owner.
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
    for projeto in projetos:
        membership = repositorio.find_membership(conn, projeto["id"], person_id)
        role = membership["role"] if membership is not None else None
        resultado.append(_serializar_com_role(conn, projeto, role))
    return resultado


def join_project(conn: sqlite3.Connection, slug: str, person_id: int) -> dict[str, Any]:
    """Entra num projeto `public` sem aprovação. Ser público é poder ver e entrar,
    não participar automaticamente. Em `private` a entrada é por `request_access`."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is not None:
        raise AlreadyExists("Você já é membro deste projeto")
    if projeto["visibility"] == EVisibility.private:
        raise Forbidden(
            f"O projeto '{slug}' é private: peça acesso com request_access e espere um owner aceitar."
        )
    with conn:
        repositorio.insert_membership(conn, projeto["id"], person_id, ERole.member.value)
    return {**_serializar(conn, projeto), "role": ERole.member.value}


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
    """Aponta mais um repositório pro projeto. Exige já ser membro: entrar é
    `join_project` (public) ou `request_access` (private), e vincular não
    adiciona ninguém. O mesmo repositório pode estar em outro(s) projeto(s) -
    isso não bloqueia. Vincular um repo que já está neste projeto é idempotente."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is None:
        if projeto["visibility"] == EVisibility.private:
            raise NotFound(f"Projeto '{slug}' não existe")
        raise Forbidden(f"Entre no projeto '{slug}' com join_project antes de vincular um repositório.")
    with conn:
        if repositorio.find_repo_link(conn, repo.root_sha, projeto["id"]) is None:
            repositorio.insert_repo(conn, projeto["id"], repo.root_sha, repo.name, repo.remote)
    return _serializar(conn, projeto)


def list_projects(conn: sqlite3.Connection, person_id: int) -> list[dict[str, Any]]:
    """Todo projeto, `public` e `private` - existência é pública. Repositórios
    vinculados e quem criou só aparecem pra quem é membro; ler/escrever o
    conteúdo (tasks, eventos) continua exigindo membership (`exigir_acesso`)."""
    return [
        _serializar_com_role(conn, linha, linha["role"])
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
    return _inserir_membro(conn, projeto, email)


def admin_add_member(conn: sqlite3.Connection, slug: str, email: str) -> dict[str, Any]:
    """Mesmo que `add_member`, sem exigir owner - acesso só pelo admin."""
    return _inserir_membro(conn, repositorio.find_by_slug(conn, slug), email)


def _inserir_membro(conn: sqlite3.Connection, projeto: sqlite3.Row, email: str) -> dict[str, Any]:
    convidado = people_repositorio.find_by_email(conn, email)
    if convidado is None:
        raise NotFound(f"Ninguém cadastrado com o email '{email}'")
    with conn:
        repositorio.insert_membership(
            conn, projeto["id"], convidado["id"], ERole.member.value
        )
    return {"projeto": projeto["slug"], "email": convidado["email"], "role": ERole.member.value}


def _exigir_outro_owner(conn: sqlite3.Connection, projeto_id: int, alvo: sqlite3.Row) -> None:
    """O projeto não fica sem owner: quem só tem esse owner perde o controle de
    membros e de visibilidade."""
    if alvo["role"] == ERole.owner and repositorio.contar_owners(conn, projeto_id) <= 1:
        raise Conflict(
            "Esta pessoa é a única owner do projeto - promova outro membro a owner antes."
        )


def remove_member(
    conn: sqlite3.Connection,
    slug: str,
    person_id: int,
    alvo_id: int,
    ctx: ContextoGit,
) -> dict[str, Any]:
    """Owner tira um membro; qualquer membro tira a si mesmo (sair do projeto).
    As tasks que eram dele ficam sem dono, com um evento em cada, porque dono
    precisa ser membro."""
    projeto = exigir_acesso(conn, slug, person_id)
    return _remover_membro(conn, projeto, alvo_id, ctx, ator_id=person_id)


def admin_remove_member(
    conn: sqlite3.Connection, slug: str, alvo_id: int, ctx: ContextoGit
) -> dict[str, Any]:
    """Mesmo que `remove_member`, sem exigir owner - acesso só pelo admin. Os
    eventos das tasks soltas saem assinados pela própria pessoa removida."""
    return _remover_membro(conn, repositorio.find_by_slug(conn, slug), alvo_id, ctx, ator_id=None)


def _remover_membro(
    conn: sqlite3.Connection,
    projeto: sqlite3.Row,
    alvo_id: int,
    ctx: ContextoGit,
    ator_id: int | None,
) -> dict[str, Any]:
    slug = projeto["slug"]
    autor_id = ator_id if ator_id is not None else alvo_id
    sequencias: list[int] = []
    soltas: list[str] = []
    with conn:
        # Lock de escrita antes de contar owners: duas saídas ao mesmo tempo não
        # podem deixar o projeto sem nenhum.
        conn.execute("BEGIN IMMEDIATE")
        if ator_id is not None and alvo_id != ator_id:
            _exigir_owner(conn, projeto["id"], ator_id)
        alvo = repositorio.find_membership(conn, projeto["id"], alvo_id)
        if alvo is None:
            raise NotFound(f"Pessoa {alvo_id} não é membro deste projeto")
        _exigir_outro_owner(conn, projeto["id"], alvo)
        for task in tasks_repositorio.tasks_do_dono(conn, projeto["id"], alvo_id):
            tasks_repositorio.update_campo(conn, task["id"], "owner_id", None)
            soltas.append(task["code"])
            sequencias.append(
                eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto["id"],
                    task_id=task["id"],
                    author_id=autor_id,
                    kind=EKindEvent.task_field_changed.value,
                    campo="owner_id",
                    valor_de=str(alvo_id),
                    valor_para=None,
                )
            )
        repositorio.delete_membership(conn, projeto["id"], alvo_id)
    for seq in sequencias:
        publish(slug, eventos_service.hidratar(conn, seq))
    removido = people_repositorio.find_by_id(conn, alvo_id)
    return {
        "projeto": slug,
        "removido": {"id": alvo_id, "email": removido["email"]},
        "tasks_sem_dono": soltas,
    }


def leave_project(
    conn: sqlite3.Connection, slug: str, person_id: int, ctx: ContextoGit
) -> dict[str, Any]:
    return remove_member(conn, slug, person_id, person_id, ctx)


def set_member_role(
    conn: sqlite3.Connection, slug: str, person_id: int, alvo_id: int, role: ERole
) -> dict[str, Any]:
    """Owner promove ou rebaixa um membro. Rebaixar o único owner é recusado."""
    projeto = exigir_acesso(conn, slug, person_id)
    return _trocar_papel(conn, projeto, alvo_id, role, ator_id=person_id)


def admin_set_member_role(
    conn: sqlite3.Connection, slug: str, alvo_id: int, role: ERole
) -> dict[str, Any]:
    """Mesmo que `set_member_role`, sem exigir owner - acesso só pelo admin."""
    return _trocar_papel(conn, repositorio.find_by_slug(conn, slug), alvo_id, role, ator_id=None)


def _trocar_papel(
    conn: sqlite3.Connection,
    projeto: sqlite3.Row,
    alvo_id: int,
    role: ERole,
    ator_id: int | None,
) -> dict[str, Any]:
    slug = projeto["slug"]
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if ator_id is not None:
            _exigir_owner(conn, projeto["id"], ator_id)
        alvo = repositorio.find_membership(conn, projeto["id"], alvo_id)
        if alvo is None:
            raise NotFound(f"Pessoa {alvo_id} não é membro deste projeto")
        if alvo["role"] != role:
            if role != ERole.owner:
                _exigir_outro_owner(conn, projeto["id"], alvo)
            repositorio.update_role(conn, projeto["id"], alvo_id, role.value)
    pessoa = people_repositorio.find_by_id(conn, alvo_id)
    return {"projeto": slug, "id": alvo_id, "email": pessoa["email"], "role": role.value}


def request_access(conn: sqlite3.Connection, slug: str, person_id: int) -> dict[str, Any]:
    """Pede acesso de escrita a um projeto `private`. Fica pendente até um
    owner aceitar ou recusar (`list_requests`/aceitar/recusar)."""
    projeto = repositorio.find_by_slug(conn, slug)
    if repositorio.find_membership(conn, projeto["id"], person_id) is not None:
        raise AlreadyExists("Você já é membro deste projeto")
    if projeto["visibility"] == EVisibility.public:
        raise Invalid(f"O projeto '{slug}' é public: não precisa de pedido, entre com join_project.")
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
    return _aplicar_request(conn, projeto, request_id, aceitar)


def admin_resolver_request(
    conn: sqlite3.Connection, slug: str, request_id: int, aceitar: bool
) -> dict[str, Any]:
    """Mesmo que aceitar/recusar pedido, sem exigir owner - acesso só pelo admin."""
    return _aplicar_request(conn, repositorio.find_by_slug(conn, slug), request_id, aceitar)


def _aplicar_request(
    conn: sqlite3.Connection, projeto: sqlite3.Row, request_id: int, aceitar: bool
) -> dict[str, Any]:
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
