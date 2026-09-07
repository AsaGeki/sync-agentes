import difflib
import json
import sqlite3
from typing import Any

from src.modules.events import service as eventos_service
from src.modules.events.bus import publish
from src.modules.projects import repositorio as projetos_repositorio
from src.modules.tasks import repositorio
from src.modules.tasks.models import CorpoIn, MensagemIn, TaskIn, TaskPatch
from src.shared.enums import EKindEvent, EStatusTask
from src.shared.erros import AlreadyExists, Invalid


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
    conn: sqlite3.Connection, task: sqlite3.Row, texto: str, author_id: int, project_id: int
) -> tuple[int, int, str]:
    """Grava o corpo como evento kind='corpo' e devolve (seq, versao, diff
    contra a anterior). Nao publica - quem decide isso e o chamador:
    `create_task` não publica o corpo inicial em separado (so o
    task_criada), `update_corpo` publica logo depois de commitar."""
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
        project_id=project_id,
        task_id=task["id"],
        author_id=author_id,
        kind=EKindEvent.corpo.value,
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
    conn: sqlite3.Connection, slug: str, author_id: int, dados: TaskIn
) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    code = dados.code or f"T-{repositorio.count(conn, projeto['id']) + 1:03d}"
    try:
        with conn:
            task_id = repositorio.insert(conn, projeto["id"], code, dados)
            seq = eventos_service.registrar(
                conn,
                project_id=projeto["id"],
                task_id=task_id,
                author_id=author_id,
                kind=EKindEvent.task_criada.value,
                texto=dados.title,
            )
            task = repositorio.find_by_id(conn, task_id)
            if dados.corpo is not None:
                _gravar_corpo_evento(conn, task, dados.corpo, author_id, projeto["id"])
    except sqlite3.IntegrityError:
        raise AlreadyExists(f"Task '{code}' já existe neste projeto") from None
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, **serializar(conn, task)}


def list_tasks(
    conn: sqlite3.Connection, slug: str, status: EStatusTask | None, tag: str | None
) -> list[dict[str, Any]]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    tasks = [serializar(conn, t) for t in repositorio.find_all(conn, projeto["id"], status)]
    if tag is not None:
        tasks = [t for t in tasks if tag in t["tags"]]
    return tasks


def read_task(conn: sqlite3.Connection, slug: str, code: str, com_corpo: bool) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    dados = serializar(conn, task)
    if com_corpo:
        corpo = repositorio.ultimo_corpo(conn, task["id"])
        dados["corpo"] = corpo["texto"] if corpo else None
    dados["eventos"] = eventos_service.eventos_da_task(conn, task["id"])
    return dados


async def update_task(
    conn: sqlite3.Connection, slug: str, code: str, author_id: int, dados: TaskPatch
) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
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
                    project_id=projeto["id"],
                    task_id=task["id"],
                    author_id=author_id,
                    kind=EKindEvent.campo.value,
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
    conn: sqlite3.Connection, slug: str, code: str, author_id: int, dados: MensagemIn
) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    with conn:
        seq = eventos_service.registrar(
            conn,
            project_id=projeto["id"],
            task_id=task["id"],
            author_id=author_id,
            kind=EKindEvent.mensagem.value,
            type=dados.type.value,
            texto=dados.texto,
        )
    evento = eventos_service.hidratar(conn, seq)
    await publish(slug, evento)
    return {"cursor": seq, **evento}


async def update_corpo(
    conn: sqlite3.Connection, slug: str, code: str, author_id: int, dados: CorpoIn
) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    with conn:
        seq, versao, diff = _gravar_corpo_evento(conn, task, dados.texto, author_id, projeto["id"])
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, "code": code, "versao": versao, "diff": diff}


def read_diff(conn: sqlite3.Connection, slug: str, code: str, desde: int) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    return task_diff(conn, task["id"], code, desde)
