# Servidor compartilhado (1 processo, N IAs): quem fixa Authorization/X-Autor-Id
# é cada cliente MCP na hora de registrar (`claude mcp add ... --header`), não
# o servidor - autenticação acontece por chamada, lendo o mesmo header que o
# REST lê via `Header()` do FastAPI (ver `src/shared/auth.py`).

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from src.modules.authors import service as autores_service
from src.modules.authors.models import AutorIn
from src.modules.events import service as eventos_service
from src.modules.events.relatorio import montar_relatorio, relatorio_markdown
from src.modules.projects import repositorio as projetos_repositorio
from src.modules.projects import service as projetos_service
from src.modules.projects.models import ProjetoIn, ProjetoPatch
from src.modules.tasks import service as tasks_service
from src.modules.tasks.models import CorpoIn, MensagemIn, TaskIn, TaskPatch
from src.shared.auth import resolve_author, validate_token
from src.shared.db import conectar
from src.shared.enums import EStatusProject, EStatusTask, ETypeAuthor, ETypeMessage

mcp = MCPServer(
    "Sync Agents",
    instructions=(
        "SYNC-AGENTES - canal de alinhamento entre agentes de IA e humanos, por "
        "projeto e task. Pensado pra 2 lados (2 pessoas, cada uma com sua IA) "
        "trabalhando na mesma coisa de máquinas diferentes: as duas IAs leem e "
        "escrevem pelas mesmas tools e recebem a mudança do outro lado em tempo "
        "real, sem depender de arquivo markdown passado na mão. Este texto é a "
        "única fonte de instrução operacional do canal - não existe .md do "
        "projeto com regra de conduta, elas moram aqui porque é o que você "
        "efetivamente lê ao conectar.\n\n"
        ""
        "IDENTIDADE\n"
        "Você já sabe quem você é - o autor foi fixado no header X-Autor-Id na "
        "hora em que este servidor MCP foi registrado (`claude mcp add ... "
        "--header X-Autor-Id`). Nenhuma tool pede id de autor como parâmetro "
        "nem aceita você escrever assinando como outro autor. Se list_authors "
        "não mostrar seu nome, quem está configurando a conexão precisa rodar "
        "create_author (dev primeiro, IA depois apontando responsible_id pro "
        "dev) e refazer o registro do MCP com o id novo - não dá pra "
        "resolver isso de dentro de uma sessão já conectada.\n\n"
        ""
        "MODELO DE DADOS (resumo - use as tools pra ver o dado de verdade)\n"
        "- projeto (`create_project`/`list_projects`/`update_project`): raiz, "
        "endereçado por slug. name/description/git_repositories (lista de repo "
        "git)/status. created_by é automático (vem do seu X-Autor-Id) - "
        "create_project exige que você tenha autor.\n"
        "- task (`create_task`/`list_tasks`/`read_task`/`update_task`): pendura "
        "em projeto, endereçada por code (T-001, único no projeto, gerado "
        "sozinho se omitido). title/status/tags/owner_id (pode ser IA ou dev) "
        "+ um corpo versionado.\n"
        "- corpo (dentro de create_task/read_task/update_task_corpo/"
        "read_task_diff): texto de referência da task, não é um campo solto - "
        "cada atualização vira uma versão nova e o servidor calcula o diff "
        "contra a anterior sozinho.\n"
        "- evento (dentro de read_task/read_project_mudancas/"
        "read_project_relatorio): trilha única de tudo que aconteceu numa task "
        "(criada, mensagem, campo mudou, corpo novo). Não existe dependência "
        "formal entre tasks (foi removido do modelo) - se precisar registrar "
        "que uma task depende de outra, isso vira mensagem ou fica escrito no "
        "próprio corpo, não uma tool separada.\n\n"
        ""
        "NOMENCLATURA DE CAMPO - IMPORTANTE PRA CHAMAR AS TOOLS CERTO\n"
        "Campo estrutural (id, tipo, nome, data, quem-é-dono) é em inglês: "
        "type, name, status, created_at, owner_id, responsible_id, code, "
        "title, tags. Campo de conteúdo livre (o que alguém escreveu) continua "
        "português: texto, corpo, diff, versao, campo, valor_de, valor_para. "
        "As duas coisas aparecem juntas na mesma tool (ex: create_task recebe "
        "`title`/`tags` em inglês e `corpo` em português) - não é "
        "inconsistência, é o critério: estrutura vira inglês, prosa fica "
        "português.\n\n"
        ""
        "TIPO DE MENSAGEM (create_task_message), quando usar cada um:\n"
        "- mudanca: 'fiz/mudei isso'.\n"
        "- pergunta: precisa de resposta do outro lado ou de um humano - entra "
        "na lista de 'perguntas sem resposta' do relatório até ser respondida. "
        "Só use quando realmente travou, não pra conversa fiada.\n"
        "- resposta: responde a última pergunta daquela task - é o que tira ela "
        "da lista de abertas.\n"
        "- decisao: ficou decidido assim - use isto, não prosa dentro do corpo, "
        "pra decisão ficar rastreável a autor e horário.\n"
        "- bloqueio: não dá pra seguir, e por quê.\n\n"
        ""
        "REGRAS DE CONDUTA\n"
        "1. Não reescreva o corpo do outro lado sem avisar. Se discorda, manda "
        "pergunta ou bloqueio primeiro. Corpo é versionado, mas discussão por "
        "sobrescrita é ruim de ler no diff.\n"
        "2. Antes de responder, leia a task inteira (read_task) - não responda "
        "só pelo resumo de um evento isolado ou de um frame de tempo real, que "
        "é só uma linha resumida.\n"
        "3. Uma task por assunto. Se a conversa numa task virou outro assunto, "
        "crie task nova (não existe tool de dependência formal entre tasks - "
        "ver Modelo de dados acima).\n"
        "4. status reflete o estado real, não a intenção - 'feito' é feito e "
        "verificado; 'bloqueado' exige owner_id dev, senão ninguém sabe de "
        "quem cobrar.\n"
        "5. update_task_corpo sempre leva o texto COMPLETO da task, nunca "
        "um fragmento - o que você manda vira a versão íntegra.\n"
        "6. Pra saber o que mudou desde a última vez que você olhou, use "
        "read_project_mudancas(desde=<ultimo cursor>) ou read_project_relatorio "
        "pro resumo técnico do estado atual (status, campos alterados, diff de "
        "corpo) - não releia todas as tasks uma por uma."
    ),
)


def _context_token(ctx: Context) -> None:
    validate_token((ctx.headers or {}).get("authorization"))


def _context_author(ctx: Context) -> sqlite3.Row:
    bruto = (ctx.headers or {}).get("x-autor-id")
    autor_id = int(bruto) if bruto is not None else None
    return resolve_author(autor_id)


# ---------- autores ---------- #


@mcp.tool()
def create_author(
    ctx: Context, type: ETypeAuthor, name: str, responsible_id: int | None = None
) -> dict[str, Any]:
    """Cadastra um autor. 'ia' exige responsible_id de um autor 'dev' já
    cadastrado; 'dev' não tem responsible_id."""
    _context_token(ctx)
    conn = conectar()
    try:
        dados = AutorIn(type=type, name=name, responsible_id=responsible_id)
        return autores_service.create_author(conn, dados)
    finally:
        conn.close()


@mcp.tool()
def list_authors(ctx: Context) -> list[dict[str, Any]]:
    """Lista todos os autores cadastrados (IA e dev)."""
    _context_token(ctx)
    conn = conectar()
    try:
        return autores_service.list_authors(conn)
    finally:
        conn.close()


# ---------- projetos ---------- #


@mcp.tool()
def create_project(
    ctx: Context,
    slug: str,
    name: str,
    description: str | None = None,
    git_repositories: list[str] | None = None,
    status: EStatusProject = EStatusProject.ativo,
) -> dict[str, Any]:
    """Cria um projeto. `slug` casa com ^[a-z0-9][a-z0-9-]*$ e é usado pra
    endereçar tudo dentro dele. `created_by` vem do X-Autor-Id de quem chama."""
    _context_token(ctx)
    autor = _context_author(ctx)
    conn = conectar()
    try:
        dados = ProjetoIn(
            slug=slug,
            name=name,
            description=description,
            git_repositories=git_repositories or [],
            status=status,
        )
        return projetos_service.create_project(conn, dados, autor["id"])
    finally:
        conn.close()


@mcp.tool()
def list_projects(ctx: Context) -> list[dict[str, Any]]:
    """Lista projetos, com contagem de tasks e o cursor atual de eventos de cada um."""
    _context_token(ctx)
    conn = conectar()
    try:
        return projetos_service.list_projects(conn)
    finally:
        conn.close()


@mcp.tool()
def update_project(
    ctx: Context,
    slug: str,
    name: str | None = None,
    description: str | None = None,
    git_repositories: list[str] | None = None,
    status: EStatusProject | None = None,
) -> dict[str, Any]:
    """Atualiza campos de um projeto existente. Só os campos informados mudam."""
    _context_token(ctx)
    conn = conectar()
    try:
        dados = ProjetoPatch(
            name=name, description=description, git_repositories=git_repositories, status=status
        )
        return projetos_service.update_project(conn, slug, dados)
    finally:
        conn.close()


# ---------- tasks ---------- #


@mcp.tool()
async def create_task(
    ctx: Context,
    slug: str,
    title: str,
    code: str | None = None,
    status: EStatusTask = EStatusTask.ideia,
    tags: list[str] | None = None,
    owner_id: int | None = None,
    corpo: str | None = None,
) -> dict[str, Any]:
    """Cria uma task no projeto. `code` (ex: T-001) é gerado automático se
    omitido. `corpo`, se enviado, já vira a v1."""
    _context_token(ctx)
    autor = _context_author(ctx)
    conn = conectar()
    try:
        dados = TaskIn(
            title=title,
            code=code,
            status=status,
            tags=tags or [],
            owner_id=owner_id,
            corpo=corpo,
        )
        return await tasks_service.create_task(conn, slug, autor["id"], dados)
    finally:
        conn.close()


@mcp.tool()
def list_tasks(
    ctx: Context, slug: str, status: EStatusTask | None = None, tag: str | None = None
) -> list[dict[str, Any]]:
    """Lista tasks do projeto, com filtro opcional por status e/ou tag."""
    _context_token(ctx)
    conn = conectar()
    try:
        return tasks_service.list_tasks(conn, slug, status, tag)
    finally:
        conn.close()


@mcp.tool()
def read_task(ctx: Context, slug: str, code: str, com_corpo: bool = True) -> dict[str, Any]:
    """Lê 1 task por code, com corpo atual e a trilha completa de eventos dela."""
    _context_token(ctx)
    conn = conectar()
    try:
        return tasks_service.read_task(conn, slug, code, com_corpo)
    finally:
        conn.close()


@mcp.tool()
async def update_task(
    ctx: Context,
    slug: str,
    code: str,
    title: str | None = None,
    status: EStatusTask | None = None,
    tags: list[str] | None = None,
    owner_id: int | None = None,
) -> dict[str, Any]:
    """Atualiza campos da task (title/status/tags/owner). Gera 1 evento
    por campo que de fato mudou."""
    _context_token(ctx)
    autor = _context_author(ctx)
    conn = conectar()
    try:
        dados = TaskPatch(title=title, status=status, tags=tags, owner_id=owner_id)
        return await tasks_service.update_task(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


# ---------- conversa ---------- #


@mcp.tool()
async def create_task_message(
    ctx: Context, slug: str, code: str, type: ETypeMessage, texto: str
) -> dict[str, Any]:
    """Manda uma mensagem na task (mudanca/pergunta/resposta/decisao/bloqueio)
    - não muda estado, só registra."""
    _context_token(ctx)
    autor = _context_author(ctx)
    conn = conectar()
    try:
        dados = MensagemIn(type=type, texto=texto)
        return await tasks_service.create_message(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


@mcp.tool()
async def update_task_corpo(ctx: Context, slug: str, code: str, texto: str) -> dict[str, Any]:
    """Grava uma versão nova do corpo da task e devolve o diff contra a
    anterior. Mande sempre o texto completo, nunca um fragmento."""
    _context_token(ctx)
    autor = _context_author(ctx)
    conn = conectar()
    try:
        dados = CorpoIn(texto=texto)
        return await tasks_service.update_corpo(conn, slug, code, autor["id"], dados)
    finally:
        conn.close()


@mcp.tool()
def read_task_diff(ctx: Context, slug: str, code: str, desde: int = 0) -> dict[str, Any]:
    """Diff unificado do corpo da task, da versão `desde` até a mais recente."""
    _context_token(ctx)
    conn = conectar()
    try:
        return tasks_service.read_diff(conn, slug, code, desde)
    finally:
        conn.close()


# ---------- eventos ---------- #


@mcp.tool()
def read_project_mudancas(
    ctx: Context, slug: str, desde: int = 0, limite: int = 200
) -> dict[str, Any]:
    """O que mudou no projeto desde o cursor `desde` (use o `cursor` da
    última resposta na próxima chamada)."""
    _context_token(ctx)
    conn = conectar()
    try:
        projeto = projetos_repositorio.find_by_slug(conn, slug)
        return {
            "projeto": slug,
            **eventos_service.mudancas_do_projeto(conn, projeto["id"], desde, limite),
        }
    finally:
        conn.close()


@mcp.tool()
def read_project_relatorio(
    ctx: Context,
    slug: str,
    desde: int = 0,
    formato: Literal["md", "json"] = "md",
    com_diff: bool = True,
) -> dict[str, Any] | str:
    """Relatório consolidado do projeto (resumo geral, estado atual por task,
    diffs). `formato=md` é técnico e sem narração de mensagens - pra ver
    autoria/conversa por evento, use `formato=json`."""
    _context_token(ctx)
    conn = conectar()
    try:
        rel = montar_relatorio(conn, slug, desde)
        if formato == "json":
            return rel
        return relatorio_markdown(conn, rel, com_diff)
    finally:
        conn.close()
