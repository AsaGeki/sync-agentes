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


def serializar(
    conn: sqlite3.Connection,
    task: sqlite3.Row,
    leitura: dict[str, int] | None = None,
) -> dict[str, Any]:
    """`leitura` vem de `repositorio.leitura_do_projeto` e acrescenta quantos
    eventos de outra pessoa estão por ler nesta task."""
    corpo = repositorio.ultimo_corpo(conn, task["id"])
    deps = repositorio.dependencies(conn, task["id"])
    dados = {
        "code": task["code"],
        "title": task["title"],
        "status": task["status"],
        "tags": json.loads(task["tags"]),
        "owner": repositorio.owner_name(conn, task["owner_id"]),
        "owner_id": task["owner_id"],
        "versao_corpo": corpo["version"] if corpo else 0,
        "dependencies": [d["code"] for d in deps],
        "dependencias_pendentes": [d["code"] for d in deps if d["status"] != EStatusTask.feito.value],
        "created_at": task["created_at"],
        "updated_at": task["updated_at"],
    }
    if leitura is not None:
        dados["nao_lidos"] = leitura["nao_lidos"]
        if leitura["ultimo_nao_lido"]:
            evento = eventos_service.hidratar(conn, leitura["ultimo_nao_lido"])
            dados["ultimo_nao_lido"] = eventos_service.envelope(evento)
    return dados


def _checar_dependencias_prontas(conn: sqlite3.Connection, task: sqlite3.Row, novo_status: str) -> None:
    """Task só fecha quando toda dependência já estiver 'feito' - senão o
    outro lado marca terminado algo que ainda depende de trabalho pendente."""
    if novo_status != EStatusTask.feito.value:
        return
    pendentes = [
        d["code"] for d in repositorio.dependencies(conn, task["id"]) if d["status"] != EStatusTask.feito.value
    ]
    if pendentes:
        raise Conflict(
            f"Task depende de {', '.join(pendentes)}, que ainda não está 'feito' - "
            "não dá pra marcar esta como 'feito' antes."
        )


def _resolver_dependencias(
    conn: sqlite3.Connection, projeto_id: int, task_id: int | None, codes: list[str]
) -> list[int]:
    """Troca codes por ids, recusando o que fecharia ciclo. Ciclo trava as duas
    pontas em 'feito' pra sempre, então é barrado antes de gravar. `task_id`
    None é task ainda não criada - não há como ela já estar no grafo."""
    ids: list[int] = []
    for code in codes:
        alvo = repositorio.find_by_code(conn, projeto_id, code)
        if task_id is not None:
            if alvo["id"] == task_id:
                raise Invalid("Task não pode depender dela mesma")
            if repositorio.alcanca(conn, alvo["id"], task_id):
                raise Conflict(
                    f"Dependência de '{alvo['code']}' fecharia um ciclo - ela já depende "
                    "desta task, direta ou indiretamente."
                )
        ids.append(alvo["id"])
    return ids


def _reabrir_dependentes(
    conn: sqlite3.Connection,
    projeto_id: int,
    task_id: int,
    author_id: int,
    ctx: ContextoGit,
) -> list[int]:
    """Task saiu de 'feito': quem dependia dela e já estava 'feito' volta pra
    'parcial', em cascata. Sem isso a dependente segue dizendo 'feito' apoiada
    em trabalho que voltou a ser pendente."""
    sequencias: list[int] = []
    fila = [task_id]
    vistos: set[int] = set()
    while fila:
        atual = fila.pop()
        if atual in vistos:
            continue
        vistos.add(atual)
        for dependente in repositorio.dependentes(conn, atual):
            if dependente["status"] != EStatusTask.feito.value:
                continue
            repositorio.update_campo(
                conn, dependente["id"], "status", EStatusTask.parcial.value
            )
            sequencias.append(
                eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto_id,
                    task_id=dependente["id"],
                    author_id=author_id,
                    kind=EKindEvent.task_field_changed.value,
                    campo="status",
                    valor_de=EStatusTask.feito.value,
                    valor_para=EStatusTask.parcial.value,
                )
            )
            fila.append(dependente["id"])
    return sequencias


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
    # Dois lados criando ao mesmo tempo chegam no mesmo número. Se ele foi gerado
    # aqui, tenta o seguinte; se veio de quem chamou, o conflito é resposta.
    depends_on_ids = _resolver_dependencias(conn, projeto["id"], None, dados.dependencies)
    numero_pedido = None
    if dados.code is not None:
        numero_pedido = repositorio.numero_do_code(dados.code)
        if numero_pedido is None:
            raise Invalid(f"'{dados.code}' não é um code de task - o formato é T-007")
    for tentativa in range(TENTATIVAS_DE_CODIGO):
        numero = numero_pedido or repositorio.proximo_numero(conn, projeto["id"])
        code = repositorio.montar_code(numero, dados.title)
        try:
            with conn:
                task_id = repositorio.insert(conn, projeto["id"], code, dados)
                if depends_on_ids:
                    repositorio.insert_dependencies(conn, task_id, depends_on_ids)
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
    q: str | None = None,
    nao_lidas: bool = False,
) -> list[dict[str, Any]]:
    projeto = exigir_acesso(conn, slug, person_id)
    leitura = repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
    linhas = repositorio.find_all(conn, projeto["id"], status)
    if q:
        casam = repositorio.ids_que_casam(conn, projeto["id"], q)
        linhas = [linha for linha in linhas if linha["id"] in casam]
    if nao_lidas:
        linhas = [linha for linha in linhas if leitura.get(linha["id"], {}).get("nao_lidos")]
    tasks = [serializar(conn, linha, leitura.get(linha["id"])) for linha in linhas]
    if tag is not None:
        tasks = [t for t in tasks if tag in t["tags"]]
    return tasks


LIMITE_NAO_LIDOS = 20


def nao_lidos(
    conn: sqlite3.Connection, slug: str, person_id: int, limite: int = LIMITE_NAO_LIDOS
) -> list[dict[str, Any]]:
    """Uma linha curta por task com evento ainda não lido, da mais recente pra
    mais antiga. É o que o bridge cola em toda resposta de tool - ler isto não
    marca nada, só `read_task` marca.

    Corta em `limite` tasks: isto viaja em toda resposta, e quem quer a lista
    inteira chama `list_tasks(nao_lidas=True)`."""
    projeto = exigir_acesso(conn, slug, person_id)
    leitura = repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
    pendentes = []
    for task in repositorio.find_all(conn, projeto["id"], None):
        marca = leitura.get(task["id"])
        if not marca or not marca["nao_lidos"]:
            continue
        evento = eventos_service.hidratar(conn, marca["ultimo_nao_lido"])
        pendentes.append(
            {
                "code": task["code"],
                "title": task["title"],
                "status": task["status"],
                "nao_lidos": marca["nao_lidos"],
                "ultimo": eventos_service.resumir(evento),
                "_seq": marca["ultimo_nao_lido"],
            }
        )
    pendentes.sort(key=lambda pendente: pendente["_seq"], reverse=True)
    for pendente in pendentes:
        del pendente["_seq"]
    return pendentes[:limite]


def read_task(
    conn: sqlite3.Connection, slug: str, person_id: int, code: str, com_corpo: bool
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    task = repositorio.find_by_code(conn, projeto["id"], code)
    leitura = repositorio.leitura_do_projeto(conn, projeto["id"], person_id).get(task["id"])
    dados = serializar(conn, task, leitura)
    if com_corpo:
        corpo = repositorio.ultimo_corpo(conn, task["id"])
        dados["corpo"] = corpo["texto"] if corpo else None
    dados["eventos"] = eventos_service.eventos_da_task(conn, task["id"])
    # Abrir a task é o que marca lido: daqui pra frente ela só volta a aparecer
    # em `nao_lidas` se o outro lado escrever de novo.
    with conn:
        repositorio.marcar_lida(
            conn, task["id"], person_id, repositorio.ultimo_seq(conn, task["id"])
        )
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

    # `dependencies` não é coluna de `tasks` - sai daqui antes do laço de campos
    # e vira linha em `task_dependencies`.
    novas_dependencias = mudancas.pop("dependencies", None)
    depends_on_ids: list[int] = []
    if novas_dependencias is not None:
        depends_on_ids = _resolver_dependencias(
            conn, projeto["id"], task["id"], novas_dependencias
        )

    sequencias: list[int] = []
    with conn:
        if novas_dependencias is not None:
            antes_deps = [d["code"] for d in repositorio.dependencies(conn, task["id"])]
            repositorio.delete_dependencies(conn, task["id"])
            repositorio.insert_dependencies(conn, task["id"], depends_on_ids)
            depois_deps = [d["code"] for d in repositorio.dependencies(conn, task["id"])]
            if antes_deps != depois_deps:
                sequencias.append(
                    eventos_service.registrar(
                        conn,
                        ctx,
                        project_id=projeto["id"],
                        task_id=task["id"],
                        author_id=author_id,
                        kind=EKindEvent.task_field_changed.value,
                        campo="dependencies",
                        valor_de=", ".join(antes_deps) or None,
                        valor_para=", ".join(depois_deps) or None,
                    )
                )

        # Depois de gravar as dependências novas: fechar a task no mesmo patch
        # que as trocou tem que valer contra as novas, não contra as antigas.
        if "status" in mudancas:
            _checar_dependencias_prontas(conn, task, mudancas["status"])

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

        saiu_de_feito = task["status"] == EStatusTask.feito.value and mudancas.get(
            "status", task["status"]
        ) != EStatusTask.feito.value
        if saiu_de_feito:
            sequencias += _reabrir_dependentes(
                conn, projeto["id"], task["id"], author_id, ctx
            )

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
