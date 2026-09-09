"""Bridge MCP local do sync-agents.

Roda como processo na máquina de quem conecta, herda o cwd do chat e resolve
sozinho três coisas que antes eram digitadas na mão:

- **escopo**: o repositório do cwd define o projeto. Nenhuma tool recebe `slug`,
  então nenhum agente escreve no projeto errado nem enxerga o assunto de outro.
- **identidade**: quem assina é a pessoa dona do token (`SYNC_AGENTS_TOKEN`); o
  `git config user.email` só serve pra conferir que o token é da máquina certa.
- **ferramenta**: qual IA está falando sai do `clientInfo` do handshake MCP.

Fora de um repositório git o canal não existe - as tools respondem instruindo a
abrir o chat dentro do repo, e nada é escrito.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from src.bridge import git_context
from src.bridge.api import Api, ErroApi
from src.bridge.git_context import ContextoRepo, descobrir
from src.shared.enums import EStatusProject, EStatusTask, ETypeMessage, EVisibility

INSTRUCOES = (
    "SYNC-AGENTS - canal de alinhamento entre pessoas (e as IAs delas) no mesmo "
    "projeto, a partir de máquinas diferentes.\n\n"
    ""
    "ESCOPO\n"
    "Você já está dentro de um projeto: o repositório git desta sessão define "
    "qual, e não existe tool que mude isso nem que liste projeto de outra "
    "gente. Nenhuma tool recebe nome de projeto - se você quer falar de outro "
    "projeto, é outra sessão, aberta dentro do repositório dele. Chame "
    "`status` pra ver onde você está.\n\n"
    ""
    "IDENTIDADE\n"
    "Quem assina é a pessoa dona do token desta máquina, e a ferramenta que "
    "escreveu (claude/codex/cursor...) vai junto automaticamente. Não existe "
    "cadastro de IA e não dá pra assinar como outra pessoa.\n\n"
    ""
    "MODELO\n"
    "- task (`create_task`/`list_tasks`/`read_task`/`update_task`): unidade de "
    "assunto, endereçada por code (T-001, gerado sozinho se omitido). "
    "title/status/tags/owner_id + um corpo versionado.\n"
    "- corpo (`read_task`/`update_body`/`read_diff`): texto de referência da "
    "task. Cada atualização vira uma versão e o servidor calcula o diff.\n"
    "- evento: trilha do que aconteceu, com branch e commit de onde saiu. "
    "`read_changes(desde=<cursor>)` mostra o que mudou; `read_report` resume o "
    "estado atual.\n\n"
    ""
    "TIPO DE MENSAGEM (`send_message`)\n"
    "- mudanca: 'fiz/mudei isso'.\n"
    "- pergunta: precisa de resposta do outro lado - fica na lista de perguntas "
    "abertas do relatório até ser respondida. Use quando travou de verdade.\n"
    "- resposta: responde a última pergunta da task e tira ela da lista.\n"
    "- decisao: ficou decidido assim. Use isto, não prosa dentro do corpo, pra "
    "a decisão ficar rastreável a quem e quando.\n"
    "- bloqueio: não dá pra seguir, e por quê.\n\n"
    ""
    "CONDUTA\n"
    "1. Não reescreva o corpo do outro lado sem avisar - se discorda, mande "
    "pergunta ou bloqueio primeiro.\n"
    "2. Antes de responder, leia a task inteira (`read_task`), não só o resumo "
    "de um evento.\n"
    "3. Uma task por assunto. Virou outro assunto, é task nova.\n"
    "4. status reflete estado real, não intenção - 'feito' é feito e "
    "verificado.\n"
    "5. `update_body` leva sempre o texto COMPLETO da task, nunca um "
    "fragmento.\n"
    "6. Toda resposta de tool traz `novidades` quando o outro lado escreveu "
    "algo desde a sua última chamada - você não precisa perguntar se mudou "
    "alguma coisa, e ninguém precisa te mandar sincronizar."
)

mcp = MCPServer("Sync Agents", instructions=INSTRUCOES)


def _repo_declarado() -> Path | None:
    if "--repo" in sys.argv:
        return Path(sys.argv[sys.argv.index("--repo") + 1])
    declarado = os.environ.get("SYNC_AGENTS_REPO")
    return Path(declarado) if declarado else None


class Sessao:
    """Estado do bridge nesta sessão: repo, projeto resolvido e cursor de eventos."""

    def __init__(self) -> None:
        # O normal é herdar o cwd do chat (Claude Code, Cursor, VS Code, tudo que
        # roda dentro de um projeto aberto). Cliente que não tem projeto aberto -
        # Claude Desktop, por exemplo - aponta o repositório em SYNC_AGENTS_REPO
        # ou em `--repo <caminho>`, e aí cada registro atende um repositório.
        self.repo: ContextoRepo | None = descobrir(_repo_declarado())
        self.base_url = os.environ.get("SYNC_AGENTS_URL", "http://127.0.0.1:8787")
        self.token = os.environ.get("SYNC_AGENTS_TOKEN")
        self.api: Api | None = None
        self.projeto: dict[str, Any] | None = None
        self.cursor = 0

    def erro_de_ambiente(self) -> str | None:
        if self.repo is None:
            return (
                "Esta sessão não está dentro de um repositório git com pelo menos 1 commit - "
                "o canal só existe dentro de um repo. Abra o chat na pasta do projeto, ou "
                "aponte o repositório em SYNC_AGENTS_REPO (ou `--repo <caminho>`) se o seu "
                "cliente não abre projeto."
            )
        if not self.token:
            return (
                "SYNC_AGENTS_TOKEN não está no ambiente. Peça um token pessoal a quem "
                "administra o servidor (POST /people) e registre o MCP com ele."
            )
        return None

    def conectar(self, ctx: Context) -> None:
        """Resolve o projeto do repositório na primeira chamada da sessão."""
        if self.projeto is not None:
            return
        self.api = Api(self.base_url, self.token, self.repo, _agent_do_cliente(ctx))
        self.projeto = self.api.request(
            "POST",
            "/repos/resolve",
            {
                "root_sha": self.repo.root_sha,
                "name": self.repo.name,
                "remote": self.repo.remote,
            },
        )

    @property
    def slug(self) -> str:
        return self.projeto["slug"]


SESSAO = Sessao()


def _agent_do_cliente(ctx: Context) -> str:
    """Nome que o cliente MCP se dá no handshake ('claude-code', 'codex'...).
    O servidor normaliza; aqui só repassa o que veio."""
    try:
        return ctx.session.client_params.client_info.name
    except AttributeError:
        return "outro"


def _novidades(sessao: Sessao) -> list[str]:
    """O que o outro lado escreveu desde a última chamada de tool. Vai anexado em
    toda resposta - é o que dispensa alguém pedir 'sincroniza no sync'."""
    resposta = sessao.api.request(
        "GET",
        f"/projetos/{sessao.slug}/mudancas",
        query={"desde": sessao.cursor, "limite": 20, "de_outros": True},
    )
    sessao.cursor = resposta["cursor"]
    return [e["resumo"] for e in resposta["eventos"] if e.get("resumo")]


def _chamar(ctx: Context, acao) -> Any:
    """Envelope comum de toda tool: valida ambiente, resolve o projeto, executa e
    anexa as novidades do outro lado."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        SESSAO.conectar(ctx)
        resultado = acao(SESSAO.api, SESSAO.slug)
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}

    # Buscar novidades é acessório e fica fora do try acima de propósito: se ele
    # falhasse junto, uma escrita que deu certo voltaria como erro e o agente
    # tentaria de novo - gravando duas vezes.
    try:
        novidades = _novidades(SESSAO)
    except ErroApi:
        novidades = []
    # Formato sempre igual: objeto na raiz. Lista crua viraria um content block
    # por item no protocolo MCP, e aí o cliente não tem onde ler as novidades.
    envelope = resultado if isinstance(resultado, dict) else {"resultado": resultado}
    return {**envelope, "novidades": novidades} if novidades else envelope


# ---------- contexto ---------- #


@mcp.tool()
def status(ctx: Context) -> dict[str, Any]:
    """Onde você está: repositório, projeto, quem assina e o cursor de eventos."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        SESSAO.conectar(ctx)
        eu = SESSAO.api.request("GET", "/me")
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}
    return {
        "projeto": SESSAO.projeto["slug"],
        "projeto_name": SESSAO.projeto["name"],
        "visibility": SESSAO.projeto["visibility"],
        "papel": SESSAO.projeto["role"],
        "repo": SESSAO.repo.name,
        "branch": SESSAO.repo.branch,
        "commit": SESSAO.repo.commit_sha,
        "assino_como": eu["alias"],
        "agent": _agent_do_cliente(ctx),
        "cursor": SESSAO.cursor,
    }


# ---------- tasks ---------- #


@mcp.tool()
def list_tasks(
    ctx: Context, status: EStatusTask | None = None, tag: str | None = None
) -> Any:
    """Lista as tasks do projeto desta sessão, com filtro opcional por status e tag."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "GET", f"/projetos/{slug}/tasks", query={"status": status, "tag": tag}
        ),
    )


@mcp.tool()
def read_task(ctx: Context, code: str, com_corpo: bool = True) -> Any:
    """Lê 1 task por code, com o corpo atual e a trilha completa de eventos dela."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "GET", f"/projetos/{slug}/tasks/{code}", query={"com_corpo": com_corpo}
        ),
    )


@mcp.tool()
def create_task(
    ctx: Context,
    title: str,
    code: str | None = None,
    status: EStatusTask = EStatusTask.ideia,
    tags: list[str] | None = None,
    owner_id: int | None = None,
    corpo: str | None = None,
) -> Any:
    """Cria uma task. `code` (T-001) é gerado se omitido; `corpo` vira a v1."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "POST",
            f"/projetos/{slug}/tasks",
            {
                "title": title,
                "code": code,
                "status": status.value,
                "tags": tags or [],
                "owner_id": owner_id,
                "corpo": corpo,
            },
        ),
    )


@mcp.tool()
def update_task(
    ctx: Context,
    code: str,
    title: str | None = None,
    status: EStatusTask | None = None,
    tags: list[str] | None = None,
    owner_id: int | None = None,
) -> Any:
    """Atualiza campos da task. Gera 1 evento por campo que de fato mudou."""
    corpo = {
        "title": title,
        "status": status.value if status else None,
        "tags": tags,
        "owner_id": owner_id,
    }
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "PATCH",
            f"/projetos/{slug}/tasks/{code}",
            {k: v for k, v in corpo.items() if v is not None},
        ),
    )


# ---------- conversa ---------- #


@mcp.tool()
def send_message(ctx: Context, code: str, type: ETypeMessage, texto: str) -> Any:
    """Manda uma mensagem na task (mudanca/pergunta/resposta/decisao/bloqueio).
    Não muda estado, só registra - e chega no outro lado em tempo real."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "POST",
            f"/projetos/{slug}/tasks/{code}/mensagens",
            {"type": type.value, "texto": texto},
        ),
    )


@mcp.tool()
def update_body(ctx: Context, code: str, texto: str) -> Any:
    """Grava uma versão nova do corpo da task e devolve o diff contra a anterior.
    Mande sempre o texto completo, nunca um fragmento."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "PUT", f"/projetos/{slug}/tasks/{code}/corpo", {"texto": texto}
        ),
    )


@mcp.tool()
def publish_diff(
    ctx: Context,
    code: str,
    base: str | None = None,
    resumo: str | None = None,
    pedir_revisao: bool = False,
) -> Any:
    """Publica na task o que voce mudou no codigo: arquivos tocados e o patch,
    entre `base` e o commit atual do repo. O diff e calculado aqui, voce nao
    precisa montar nada.

    `base` omitido usa o head do ultimo diff publicado nesta task; se nao houver
    nenhum, usa o ponto em que a branch atual saiu da principal.
    `pedir_revisao=True` registra tambem uma pergunta na task, entao o diff
    aparece nas perguntas em aberto do relatorio ate alguem responder.
    """

    def acao(api: Api, slug: str) -> Any:
        partida = base or _base_do_ultimo_diff(api, slug, code) or git_context.base_padrao(
            SESSAO.repo.raiz
        )
        if not partida:
            return {
                "erro": (
                    "Nao deu pra descobrir de onde comparar - passe `base` com o sha "
                    "do commit a partir do qual voce quer o diff."
                )
            }
        return api.request(
            "POST",
            f"/projetos/{slug}/tasks/{code}/diffs",
            {
                "base_sha": partida,
                "arquivos": git_context.arquivos_alterados(SESSAO.repo.raiz, partida),
                "patch": git_context.patch(SESSAO.repo.raiz, partida),
                "resumo": resumo,
                "pedir_revisao": pedir_revisao,
            },
        )

    return _chamar(ctx, acao)


def _base_do_ultimo_diff(api: Api, slug: str, code: str) -> str | None:
    """Head do ultimo diff publicado na task - e dali que o proximo continua."""
    publicados = api.request("GET", f"/projetos/{slug}/tasks/{code}/diffs")
    return publicados[-1]["payload"]["head_sha"] if publicados else None


@mcp.tool()
def list_diffs(ctx: Context, code: str) -> Any:
    """Os diffs de codigo ja publicados numa task, sem o patch."""
    return _chamar(
        ctx, lambda api, slug: api.request("GET", f"/projetos/{slug}/tasks/{code}/diffs")
    )


@mcp.tool()
def read_diff(ctx: Context, code: str, desde: int = 0) -> Any:
    """Diff unificado do corpo da task, da versão `desde` até a mais recente."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "GET", f"/projetos/{slug}/tasks/{code}/diff", query={"desde": desde}
        ),
    )


# ---------- eventos ---------- #


@mcp.tool()
def read_changes(ctx: Context, desde: int | None = None, limite: int = 200) -> Any:
    """O que mudou no projeto desde um cursor. Omitindo `desde`, continua de onde
    esta sessão parou."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "GET",
            f"/projetos/{slug}/mudancas",
            query={"desde": SESSAO.cursor if desde is None else desde, "limite": limite},
        ),
    )


@mcp.tool()
def read_report(
    ctx: Context,
    desde: int = 0,
    formato: Literal["md", "json"] = "md",
    com_diff: bool = True,
) -> Any:
    """Resumo técnico do estado do projeto: status por task, campos alterados,
    diff de corpo e onde no git aquilo aconteceu."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "GET",
            f"/projetos/{slug}/relatorio",
            query={"desde": desde, "formato": formato, "com_diff": com_diff},
        ),
    )


# ---------- projeto e acesso ---------- #


@mcp.tool()
def update_project(
    ctx: Context,
    name: str | None = None,
    description: str | None = None,
    status: EStatusProject | None = None,
    visibility: EVisibility | None = None,
) -> Any:
    """Atualiza o projeto desta sessão. `visibility='private'` fecha o projeto:
    a partir daí só entra quem um owner adicionar (só owner pode mudar isso)."""
    corpo = {
        "name": name,
        "description": description,
        "status": status.value if status else None,
        "visibility": visibility.value if visibility else None,
    }
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "PATCH", f"/projetos/{slug}", {k: v for k, v in corpo.items() if v is not None}
        ),
    )


@mcp.tool()
def list_members(ctx: Context) -> Any:
    """Quem tem acesso a este projeto."""
    return _chamar(ctx, lambda api, slug: api.request("GET", f"/projetos/{slug}/membros"))


@mcp.tool()
def add_member(ctx: Context, email: str) -> Any:
    """Dá acesso a este projeto pra alguém já cadastrado no servidor. Só owner."""
    return _chamar(
        ctx,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/membros", {"email": email}),
    )


@mcp.tool()
def link_repo(ctx: Context) -> Any:
    """Aponta o repositório desta sessão pro mesmo projeto de outro repo - use
    quando frontend e backend são repos separados do mesmo trabalho. Rode a
    partir do repo que ainda não está vinculado, tendo acesso ao projeto."""
    return _chamar(
        ctx,
        lambda api, slug: api.request(
            "POST",
            f"/projetos/{slug}/repos",
            {
                "root_sha": SESSAO.repo.root_sha,
                "name": SESSAO.repo.name,
                "remote": SESSAO.repo.remote,
            },
        ),
    )


def main() -> None:
    problema = SESSAO.erro_de_ambiente()
    if problema:
        # stderr, não stdout: stdout é o canal do protocolo MCP.
        print(f"sync-agents: {problema}", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
