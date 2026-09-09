import difflib
import json
import sqlite3
from typing import Any

from src.modules.events import service as eventos_service
from src.modules.events.bus import publish
from src.modules.projects.service import exigir_acesso
from src.modules.tasks import repositorio
from src.modules.tasks.models import CorpoIn, DiffIn, MensagemIn, TaskIn, TaskPatch
from src.shared.auth import ContextoGit
from src.shared.enums import EKindEvent, EStatusTask, ETypeMessage
from src.shared.erros import AlreadyExists, Conflict, Invalid, MissingRequirement

TENTATIVAS_DE_CODIGO = 5


def serializar(conn: sqlite3.Connection, task: sqlite3.Row) -> dict[str, Any]:
    corpo = repositorio.ultimo_corpo(conn, task["id"])
    return {
        "code": task["code"],
        "title": task["title"],
        "status": task["status"],
        "tags": json.loads(task["tags"]),
        "owner": repositorio.owner_name(conn, task["owner_id"]),
        "owner_id": task["owner_id"],
        "versao_corpo": corpo["version"] if corpo else 0,
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }


def _make_diff(antes: str, depois: str, rotulo_antes: str, rotulo_depois: str) -> str:
    linhas = difflib.unified_diff(
        antes.splitlines(keepends=True),
        depois.splitlines(keepends=True),
        fromfile=rotulo_antes,
        tofile=rotulo_depois,
        n=3,
    )
    return "".join(linhas)


def _gravar_corpo_evento(
    conn: sqlite3.Connection,
    task: sqlite3.Row,
    texto: str,
    author_id: int,
    project_id: int,
    ctx: ContextoGit,
) -> tuple[int, int, str]:
    """Grava o corpo como evento `body.updated` e devolve (seq, versao, diff
    contra a anterior). Publicar no tempo real é com o chamador: `create_task`
    só publica o `task.created`, `update_corpo` publica após commitar."""
    anterior = repositorio.ultimo_corpo(conn, task["id"])
    versao = (anterior["version"] if anterior else 0) + 1
    diff = _make_diff(
        anterior["texto"] if anterior else "",
        texto,
        f"{task['code']} v{anterior['version'] if anterior else 0}",
        f"{task['code']} v{versao}",
    )
    seq = eventos_service.registrar(
        conn,
        ctx,
        project_id=project_id,
        task_id=task["id"],
        author_id=author_id,
        kind=EKindEvent.body_updated.value,
        version=versao,
        texto=texto,
    )
    return seq, versao, diff


def task_diff(conn: sqlite3.Connection, task_id: int, code: str, desde: int) -> dict[str, Any]:
    versoes = repositorio.todos_corpos(conn, task_id)
    if not versoes:
        return {"code": code, "versao_de": 0, "versao_para": 0, "diff": ""}
    antes = next((v["texto"] for v in versoes if v["version"] == desde), "")
    ultima = versoes[-1]
    return {
        "code": code,
        "versao_de": desde,
        "versao_para": ultima["version"],
        "diff": _make_diff(
            antes, ultima["texto"], f"{code} v{desde}", f"{code} v{ultima['version']}"
        ),
    }


async def create_task(
    conn: sqlite3.Connection, slug: str, author_id: int, ctx: ContextoGit, dados: TaskIn
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    # Dois lados criando ao mesmo tempo chegam no mesmo código. Se ele foi gerado
    # aqui, tenta o seguinte; se veio de quem chamou, o conflito é resposta.
    for tentativa in range(TENTATIVAS_DE_CODIGO):
        code = dados.code or repositorio.proximo_codigo(conn, projeto["id"])
        try:
            with conn:
                task_id = repositorio.insert(conn, projeto["id"], code, dados)
                seq = eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto["id"],
                    task_id=task_id,
                    author_id=author_id,
                    kind=EKindEvent.task_created.value,
                    texto=dados.title,
                )
                task = repositorio.find_by_id(conn, task_id)
                if dados.corpo is not None:
                    _gravar_corpo_evento(conn, task, dados.corpo, author_id, projeto["id"], ctx)
            break
        except sqlite3.IntegrityError:
            if dados.code or tentativa == TENTATIVAS_DE_CODIGO - 1:
                raise AlreadyExists(f"Task '{code}' já existe neste projeto") from None
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, **serializar(conn, task)}


def list_tasks(
    conn: sqlite3.Connection,
    slug: str,
    person_id: int,
    status: EStatusTask | None,
    tag: str | None,
) -> list[dict[str, Any]]:
    projeto = exigir_acesso(conn, slug, person_id)
    tasks = [serializar(conn, t) for t in repositorio.find_all(conn, projeto["id"], status)]
    if tag is not None:
        tasks = [t for t in tasks if tag in t["tags"]]
    return tasks


def read_task(
    conn: sqlite3.Connection, slug: str, person_id: int, code: str, com_corpo: bool
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    dados = serializar(conn, task)
    if com_corpo:
        corpo = repositorio.ultimo_corpo(conn, task["id"])
        dados["corpo"] = corpo["texto"] if corpo else None
    dados["eventos"] = eventos_service.eventos_da_task(conn, task["id"])
    return dados


async def update_task(
    conn: sqlite3.Connection,
    slug: str,
    code: str,
    author_id: int,
    ctx: ContextoGit,
    dados: TaskPatch,
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    mudancas = dados.model_dump(mode="json", exclude_none=True)
    if not mudancas:
        raise Invalid("Nada pra atualizar")
    sequencias: list[int] = []
    with conn:
        for campo, valor in mudancas.items():
            antes = task[campo]
            novo = json.dumps(valor, ensure_ascii=False) if campo == "tags" else valor
            if str(antes) == str(novo):
                continue
            repositorio.update_campo(conn, task["id"], campo, novo)
            sequencias.append(
                eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto["id"],
                    task_id=task["id"],
                    author_id=author_id,
                    kind=EKindEvent.task_field_changed.value,
                    campo=campo,
                    valor_de=None if antes is None else str(antes),
                    valor_para=None if novo is None else str(novo),
                )
            )
        repositorio.tocar(conn, task["id"])
    for seq in sequencias:
        await publish(slug, eventos_service.hidratar(conn, seq))
    atual = repositorio.find_by_code(conn, projeto["id"], code)
    return {"cursor": sequencias[-1] if sequencias else None, **serializar(conn, atual)}


async def create_message(
    conn: sqlite3.Connection,
    slug: str,
    code: str,
    author_id: int,
    ctx: ContextoGit,
    dados: MensagemIn,
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    with conn:
        seq = eventos_service.registrar(
            conn,
            ctx,
            project_id=projeto["id"],
            task_id=task["id"],
            author_id=author_id,
            kind=EKindEvent.message_created.value,
            type=dados.type.value,
            texto=dados.texto,
        )
    evento = eventos_service.hidratar(conn, seq)
    await publish(slug, evento)
    return {"cursor": seq, **eventos_service.envelope(evento, com_texto=True)}


async def update_corpo(
    conn: sqlite3.Connection,
    slug: str,
    code: str,
    author_id: int,
    ctx: ContextoGit,
    dados: CorpoIn,
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    with conn:
        # Lock de escrita já na abertura: sem ele, os dois lados leem a mesma
        # versão atual e tentam gravar a seguinte.
        conn.execute("BEGIN IMMEDIATE")
        atual = repositorio.ultimo_corpo(conn, task["id"])
        versao_atual = atual["version"] if atual else 0
        if dados.versao_base is not None and dados.versao_base != versao_atual:
            raise Conflict(
                f"O corpo desta task está na v{versao_atual}, não na v{dados.versao_base} "
                "que você leu - releia a task antes de gravar, senão você apaga o que o "
                "outro lado escreveu."
            )
        seq, versao, diff = _gravar_corpo_evento(
            conn, task, dados.texto, author_id, projeto["id"], ctx
        )
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, "code": code, "versao": versao, "diff": diff}


# Teto do patch guardado por diff. Acima disso o texto é cortado e o evento
# marca `truncado`.
LIMITE_PATCH = 100_000


async def publish_diff(
    conn: sqlite3.Connection,
    slug: str,
    code: str,
    author_id: int,
    ctx: ContextoGit,
    dados: DiffIn,
) -> dict[str, Any]:
    """Publica um diff de código na task: quais arquivos mudaram entre `base_sha`
    e o commit de quem publica, com o patch junto.

    `pedir_revisao` registra também uma pergunta na task, colocando o diff na
    lista de perguntas em aberto do relatório.
    """
    projeto = exigir_acesso(conn, slug, author_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    if not ctx.commit_sha:
        raise MissingRequirement(
            "Publicar diff exige saber em que commit você está (header X-Git-Commit)"
        )
    if ctx.commit_sha == dados.base_sha:
        raise Invalid("base_sha é o próprio commit atual - não há diff entre eles")

    patch = dados.patch or ""
    truncado = len(patch) > LIMITE_PATCH
    if truncado:
        patch = patch[:LIMITE_PATCH] + "\n... patch truncado ...\n"

    with conn:
        seq = eventos_service.registrar(
            conn,
            ctx,
            project_id=projeto["id"],
            task_id=task["id"],
            author_id=author_id,
            kind=EKindEvent.diff_published.value,
            base_sha=dados.base_sha,
            arquivos=json.dumps(dados.arquivos, ensure_ascii=False),
            texto=patch or None,
        )
        seq_pergunta = None
        if dados.pedir_revisao:
            resumo = dados.resumo or f"{len(dados.arquivos)} arquivo(s) alterado(s)"
            seq_pergunta = eventos_service.registrar(
                conn,
                ctx,
                project_id=projeto["id"],
                task_id=task["id"],
                author_id=author_id,
                kind=EKindEvent.message_created.value,
                type=ETypeMessage.pergunta.value,
                texto=f"Revisão pedida no diff da seq {seq}: {resumo}",
            )

    for publicado in (seq, seq_pergunta):
        if publicado is not None:
            await publish(slug, eventos_service.hidratar(conn, publicado))
    evento = eventos_service.envelope(eventos_service.hidratar(conn, seq))
    return {"cursor": seq_pergunta or seq, "truncado": truncado, **evento}


def list_diffs(
    conn: sqlite3.Connection, slug: str, person_id: int, code: str
) -> list[dict[str, Any]]:
    """Os diffs publicados numa task, do mais antigo pro mais novo, sem o patch.
    O patch vem no evento correspondente em `read_task`."""
    projeto = exigir_acesso(conn, slug, person_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    return [
        eventos_service.envelope(evento)
        for evento in (
            eventos_service.hidratar(conn, seq)
            for seq in repositorio.seqs_de_diff(conn, task["id"])
        )
    ]


def read_diff(
    conn: sqlite3.Connection, slug: str, person_id: int, code: str, desde: int
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    return task_diff(conn, task["id"], code, desde)
