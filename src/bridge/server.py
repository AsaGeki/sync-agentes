"""Bridge MCP local do sync-agents.

Roda como processo na máquina de quem conecta e resolve três coisas sozinho:

- escopo: o repositório do cwd define quais projetos a sessão pode tocar (pode
  ser mais de 1 - as tools recebem `project` opcional pra desambiguar).
- identidade: quem assina é a pessoa dona do `SYNC_AGENTS_TOKEN`.
- ferramenta: sai do `clientInfo` do handshake MCP.

Fora de um repositório git nada é escrito - as tools respondem pedindo pra abrir
o chat dentro do repositório.
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
    "O repositório git desta sessão define quais projetos você pode tocar - "
    "chame `status` pra ver a lista (o caso comum é 1, mas pode ser mais de 1 "
    "quando o mesmo repositório serve assuntos diferentes). Toda tool de "
    "projeto/task aceita `project` (slug) opcional: com 1 projeto só, pode "
    "omitir. Com mais de 1, é obrigatório - chamar sem `project` devolve a "
    "lista de candidatos em vez de adivinhar qual. Pergunte à pessoa qual "
    "projeto antes de escolher, nunca decida sozinho.\n\n"
    ""
    "PROJETO NOVO OU SEM ACESSO\n"
    "Se `status` não trouxer nenhum projeto pra este repositório: `list_projects` "
    "lista todo projeto que existe no servidor (independe do repositório desta "
    "sessão - existência é pública, mesmo `private`), útil pra achar o slug "
    "certo antes de agir. Repositório sem NENHUM projeto ainda: `create_project` "
    "cria um e já afilia este repositório a ele (funciona mesmo se este "
    "repositório já tiver outro - soma mais um). SEMPRE pergunte à pessoa, "
    "antes de chamar, se o projeto deve ser `team` (qualquer um com o "
    "repositório entra sozinho) ou `private` (só entra quem um owner aceitar) - "
    "nunca decida isso sozinho. Projeto já existe (achou o slug via "
    "`list_projects`) mas o repositório desta sessão ainda não está linkado a "
    "ele: se for `team`, `link_repo(project=<slug>)` direto - linka e já vira "
    "membro no mesmo ato, sem precisar de aprovação de ninguém. Se for "
    "`private`, `link_repo` só funciona se você já for membro - nesse caso use "
    "antes `request_access(project=<slug>)` (funciona mesmo sem o repositório "
    "desta sessão afiliado a nada) e espere um owner aceitar (`list_requests` / "
    "aceitar / recusar, ferramentas do owner) antes de linkar.\n\n"
    ""
    "IDENTIDADE\n"
    "Quem assina é a pessoa dona do token desta máquina, e a ferramenta que "
    "escreveu (claude ou codex) vai junto automaticamente. Não existe "
    "cadastro de IA e não dá pra assinar como outra pessoa.\n\n"
    ""
    "MODELO\n"
    "- task (`create_task`/`list_tasks`/`read_task`/`update_task`): unidade de "
    "assunto, endereçada por code (T-001, gerado sozinho se omitido). "
    "title/status/tags/owner_id + um corpo versionado.\n"
    "- corpo (`read_task`/`update_body`/`read_body_diff`): texto de referência da "
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
    "alguma coisa, e ninguém precisa te mandar sincronizar.\n"
    "7. Versionamento git (se subiu commit, se está commitado, se está em "
    "produção) não é assunto do sync - não comente sobre isso aqui.\n"
    "8. O ambiente de quem está do outro lado é de desenvolvimento (yarn dev, "
    "yarn start ou equivalente) - se você já tem certeza que sua mudança está "
    "rodando, ela já vale pro outro lado. Não mande coisa como 'precisa "
    "esperar fulano rodar de novo' ou 'mudei o código mas ainda não commitei' "
    "- isso é entre você e sua pessoa, não sobe no sync e só gera desconfiança "
    "no agente do outro lado sobre se está funcionando ou não."
)

mcp = MCPServer("Sync Agents", instructions=INSTRUCOES)


def _repo_declarado() -> Path | None:
    if "--repo" in sys.argv:
        return Path(sys.argv[sys.argv.index("--repo") + 1])
    declarado = os.environ.get("SYNC_AGENTS_REPO")
    return Path(declarado) if declarado else None


class Sessao:
    """Estado do bridge nesta sessão: repo, projetos afiliados a ele (pode ser
    mais de 1) e cursor de eventos por projeto."""

    def __init__(self) -> None:
        # Cwd do chat, ou o caminho declarado quando o cliente não abre projeto.
        self.repo: ContextoRepo | None = descobrir(_repo_declarado())
        self.base_url = os.environ.get("SYNC_AGENTS_URL", "http://127.0.0.1:8787")
        self.token = os.environ.get("SYNC_AGENTS_TOKEN")
        self.api: Api | None = None
        self.projetos: list[dict[str, Any]] | None = None
        self.cursores: dict[str, int] = {}

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
        """Resolve os projetos afiliados ao repositório na primeira chamada da
        sessão."""
        if self.projetos is not None:
            return
        self.api = Api(self.base_url, self.token, self.repo, _agent_do_cliente(ctx))
        self.projetos = self.api.request(
            "POST",
            "/repos/resolve",
            {
                "root_sha": self.repo.root_sha,
                "name": self.repo.name,
                "remote": self.repo.remote,
            },
        )

    def resolver_slug(self) -> str | dict[str, Any]:
        """Escolhe entre os projetos afiliados ao repositório desta sessão - só
        funciona sozinho com exatamente 1. Mais de 1 sem `project` explícito
        devolve erro em vez de adivinhar."""
        slugs = [p["slug"] for p in self.projetos]
        if len(slugs) == 1:
            return slugs[0]
        return {
            "erro": "Este repositório está afiliado a mais de 1 projeto - chame de novo "
            "com project=<slug>. Pergunte à pessoa qual, não escolha sozinho.",
            "projetos": slugs,
        }

    def api_avulsa(self, ctx: Context) -> Api:
        """Cliente HTTP sem depender do repositório já estar afiliado a nada -
        pra tool que recebe `project` explícito e atua nele direto (pedir
        acesso a um projeto cujo repo ainda não foi linkado, por exemplo)."""
        if self.api is None:
            self.api = Api(self.base_url, self.token, self.repo, _agent_do_cliente(ctx))
        return self.api


SESSAO = Sessao()


def _agent_do_cliente(ctx: Context) -> str:
    """Nome que o cliente MCP se dá no handshake ('claude-code', 'codex'...).
    O servidor normaliza; aqui só repassa o que veio."""
    try:
        return ctx.session.client_params.client_info.name
    except AttributeError:
        return "outro"


def _novidades(api: Api, slug: str) -> list[str]:
    """O que o outro lado escreveu desde a última chamada de tool neste
    projeto. Vai anexado em toda resposta - é o que dispensa alguém pedir
    'sincroniza no sync'."""
    resposta = api.request(
        "GET",
        f"/projetos/{slug}/mudancas",
        query={"desde": SESSAO.cursores.get(slug, 0), "limite": 20, "de_outros": True},
    )
    SESSAO.cursores[slug] = resposta["cursor"]
    return [e["resumo"] for e in resposta["eventos"] if e.get("resumo")]


def _chamar(ctx: Context, project: str | None, acao) -> Any:
    """Envelope comum de toda tool: valida ambiente, decide qual projeto usar,
    executa e anexa as novidades do outro lado.

    `project` explícito não depende do repositório desta sessão já estar
    afiliado a nada - só o servidor decide se você tem acesso (`exigir_acesso`).
    Isso importa pro primeiro pedido de acesso a um projeto cujo repo ainda não
    foi linkado. `project` omitido resolve pelos projetos afiliados ao
    repositório (funciona sozinho com exatamente 1)."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    if project is not None:
        slug = project
        api = SESSAO.api_avulsa(ctx)
    else:
        try:
            SESSAO.conectar(ctx)
        except ErroApi as erro:
            return {"erro": erro.detalhe, "status": erro.status}
        slug = SESSAO.resolver_slug()
        if isinstance(slug, dict):
            return slug
        api = SESSAO.api
    try:
        resultado = acao(api, slug)
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}

    # Fora do try acima: falha aqui não pode transformar escrita bem-sucedida em
    # erro, senão o agente repete a escrita.
    try:
        novidades = _novidades(api, slug)
    except ErroApi:
        novidades = []
    # Objeto na raiz sempre: lista crua vira um content block por item no MCP, e
    # `novidades` não teria onde entrar.
    envelope = resultado if isinstance(resultado, dict) else {"resultado": resultado}
    return {**envelope, "novidades": novidades} if novidades else envelope


# ---------- contexto ---------- #


@mcp.tool()
def status(ctx: Context) -> dict[str, Any]:
    """Onde você está: repositório e os projetos afiliados a ele (pode ser mais
    de 1 - nesse caso as outras tools pedem `project=<slug>`)."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        SESSAO.conectar(ctx)
        eu = SESSAO.api.request("GET", "/me")
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}
    return {
        "repo": SESSAO.repo.name,
        "branch": SESSAO.repo.branch,
        "commit": SESSAO.repo.commit_sha,
        "assino_como": eu["alias"],
        "agent": _agent_do_cliente(ctx),
        "projetos": [
            {
                "slug": p["slug"],
                "name": p["name"],
                "visibility": p["visibility"],
                "papel": p["role"] or "sem acesso - peça com request_access",
            }
            for p in SESSAO.projetos
        ],
    }


@mcp.tool()
def list_projects(ctx: Context) -> Any:
    """Lista todo projeto que existe no servidor, não só os afiliados a este
    repositório - existência de projeto é pública. Use pra achar o slug de um
    projeto antes de `request_access` ou `link_repo`."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        return SESSAO.api_avulsa(ctx).request("GET", "/projetos")
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}


@mcp.tool()
def create_project(
    ctx: Context, name: str, visibility: EVisibility, description: str | None = None
) -> Any:
    """Cria um projeto novo e afilia o repositório desta sessão a ele. Funciona
    mesmo se este repositório já tiver projeto(s) afiliado(s) - soma mais um,
    não substitui.

    SEMPRE pergunte à pessoa se o projeto deve ser `team` ou `private` antes de
    chamar - não decida sozinho."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        projeto = SESSAO.api_avulsa(ctx).request(
            "POST",
            "/projetos",
            {
                "name": name,
                "description": description,
                "visibility": visibility.value,
                "repo": {
                    "root_sha": SESSAO.repo.root_sha,
                    "name": SESSAO.repo.name,
                    "remote": SESSAO.repo.remote,
                },
            },
        )
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}
    SESSAO.projetos = None  # força re-resolver no próximo conectar()
    return projeto


# ---------- tasks ---------- #


@mcp.tool()
def list_tasks(
    ctx: Context,
    status: EStatusTask | None = None,
    tag: str | None = None,
    project: str | None = None,
) -> Any:
    """Lista as tasks do projeto, com filtro opcional por status e tag."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "GET", f"/projetos/{slug}/tasks", query={"status": status, "tag": tag}
        ),
    )


@mcp.tool()
def read_task(ctx: Context, code: str, com_corpo: bool = True, project: str | None = None) -> Any:
    """Lê 1 task por code, com o corpo atual e a trilha completa de eventos dela."""
    return _chamar(
        ctx,
        project,
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
    project: str | None = None,
) -> Any:
    """Cria uma task. `code` (T-001) é gerado se omitido; `corpo` vira a v1."""
    return _chamar(
        ctx,
        project,
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
    project: str | None = None,
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
        project,
        lambda api, slug: api.request(
            "PATCH",
            f"/projetos/{slug}/tasks/{code}",
            {k: v for k, v in corpo.items() if v is not None},
        ),
    )


# ---------- conversa ---------- #


@mcp.tool()
def send_message(
    ctx: Context, code: str, type: ETypeMessage, texto: str, project: str | None = None
) -> Any:
    """Manda uma mensagem na task (mudanca/pergunta/resposta/decisao/bloqueio).
    Não muda estado, só registra - e chega no outro lado em tempo real."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "POST",
            f"/projetos/{slug}/tasks/{code}/mensagens",
            {"type": type.value, "texto": texto},
        ),
    )


@mcp.tool()
def update_body(
    ctx: Context,
    code: str,
    texto: str,
    versao_base: int | None = None,
    project: str | None = None,
) -> Any:
    """Grava uma versão nova do corpo da task e devolve o diff contra a anterior.
    Mande sempre o texto completo, nunca um fragmento.

    `versao_base` é o `versao_corpo` que veio do `read_task` que você usou pra
    escrever este texto. Informando, o servidor recusa (409) se o outro lado
    tiver gravado nesse meio tempo, em vez de apagar o que ele escreveu."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "PUT",
            f"/projetos/{slug}/tasks/{code}/corpo",
            {"texto": texto, "versao_base": versao_base},
        ),
    )


@mcp.tool()
def publish_diff(
    ctx: Context,
    code: str,
    base: str | None = None,
    resumo: str | None = None,
    pedir_revisao: bool = False,
    project: str | None = None,
) -> Any:
    """Publica na task o que você mudou no código: arquivos tocados e o patch,
    entre `base` e o commit atual do repositório. O diff é calculado aqui.

    `base` omitido usa o head do último diff publicado nesta task; não havendo
    nenhum, o ponto em que a branch atual saiu da principal.
    `pedir_revisao=True` registra também uma pergunta na task, então o diff
    aparece nas perguntas em aberto do relatório até alguém responder.
    """

    def acao(api: Api, slug: str) -> Any:
        partida = base or _base_do_ultimo_diff(api, slug, code) or git_context.base_padrao(
            SESSAO.repo.raiz
        )
        if not partida:
            return {
                "erro": (
                    "Não deu pra descobrir de onde comparar - passe `base` com o sha "
                    "do commit a partir do qual você quer o diff."
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

    return _chamar(ctx, project, acao)


def _base_do_ultimo_diff(api: Api, slug: str, code: str) -> str | None:
    """Head do último diff publicado na task, de onde o próximo continua."""
    publicados = api.request("GET", f"/projetos/{slug}/tasks/{code}/diffs")
    return publicados[-1]["payload"]["head_sha"] if publicados else None


@mcp.tool()
def list_diffs(ctx: Context, code: str, project: str | None = None) -> Any:
    """Os diffs de código já publicados numa task, sem o patch."""
    return _chamar(
        ctx, project, lambda api, slug: api.request("GET", f"/projetos/{slug}/tasks/{code}/diffs")
    )


@mcp.tool()
def read_body_diff(ctx: Context, code: str, desde: int = 0, project: str | None = None) -> Any:
    """Diff do TEXTO da task (o corpo), da versão `desde` até a mais recente.
    Pra diff de código é `list_diffs`/`publish_diff` - são coisas diferentes."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "GET", f"/projetos/{slug}/tasks/{code}/corpo/diff", query={"desde": desde}
        ),
    )


# ---------- eventos ---------- #


@mcp.tool()
def read_changes(
    ctx: Context, desde: int | None = None, limite: int = 200, project: str | None = None
) -> Any:
    """O que mudou no projeto desde um cursor. Omitindo `desde`, continua de onde
    esta sessão parou neste projeto."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "GET",
            f"/projetos/{slug}/mudancas",
            query={
                "desde": SESSAO.cursores.get(slug, 0) if desde is None else desde,
                "limite": limite,
            },
        ),
    )


@mcp.tool()
def read_report(
    ctx: Context,
    desde: int = 0,
    formato: Literal["md", "json"] = "md",
    com_diff: bool = True,
    project: str | None = None,
) -> Any:
    """Resumo técnico do estado do projeto: status por task, campos alterados,
    diff de corpo e onde no git aquilo aconteceu."""
    return _chamar(
        ctx,
        project,
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
    project: str | None = None,
) -> Any:
    """Atualiza o projeto. `visibility='private'` fecha o projeto: a partir daí
    só entra quem um owner adicionar (só owner pode mudar isso)."""
    corpo = {
        "name": name,
        "description": description,
        "status": status.value if status else None,
        "visibility": visibility.value if visibility else None,
    }
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "PATCH", f"/projetos/{slug}", {k: v for k, v in corpo.items() if v is not None}
        ),
    )


@mcp.tool()
def list_members(ctx: Context, project: str | None = None) -> Any:
    """Quem tem acesso a este projeto."""
    return _chamar(ctx, project, lambda api, slug: api.request("GET", f"/projetos/{slug}/membros"))


@mcp.tool()
def add_member(ctx: Context, email: str, project: str | None = None) -> Any:
    """Dá acesso a este projeto pra alguém já cadastrado no servidor. Só owner."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/membros", {"email": email}),
    )


@mcp.tool()
def request_access(ctx: Context, project: str | None = None) -> Any:
    """Pede acesso de escrita a um projeto `private` que você ainda não é
    membro. Fica pendente até um owner aceitar ou recusar (`list_requests` e
    as tools de aceitar/recusar, do owner)."""
    return _chamar(ctx, project, lambda api, slug: api.request("POST", f"/projetos/{slug}/pedidos"))


@mcp.tool()
def list_requests(ctx: Context, project: str | None = None) -> Any:
    """Pedidos de acesso pendentes deste projeto. Só owner."""
    return _chamar(ctx, project, lambda api, slug: api.request("GET", f"/projetos/{slug}/pedidos"))


@mcp.tool()
def approve_request(ctx: Context, request_id: int, project: str | None = None) -> Any:
    """Aceita um pedido de acesso - quem pediu vira member. Só owner."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/pedidos/{request_id}/aceitar"),
    )


@mcp.tool()
def reject_request(ctx: Context, request_id: int, project: str | None = None) -> Any:
    """Recusa um pedido de acesso. Só owner."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/pedidos/{request_id}/recusar"),
    )


@mcp.tool()
def link_repo(ctx: Context, project: str) -> Any:
    """Aponta o repositório desta sessão pro projeto `project` (slug) - use
    quando este repositório ainda não está afiliado a ele (frontend/backend em
    repos separados do mesmo trabalho, ou mais um repo pro mesmo projeto).
    `project` é obrigatório aqui - não há como inferir, é justamente o vínculo
    que ainda não existe.

    Projeto `team`: qualquer pessoa cadastrada linka, e já vira membro nesse
    ato - mesmo espírito de "quem tem o repositório entra sozinho". Projeto
    `private`: só quem já é membro consegue linkar."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    try:
        resultado = SESSAO.api_avulsa(ctx).request(
            "POST",
            f"/projetos/{project}/repos",
            {
                "root_sha": SESSAO.repo.root_sha,
                "name": SESSAO.repo.name,
                "remote": SESSAO.repo.remote,
            },
        )
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}
    SESSAO.projetos = None  # força re-resolver no próximo conectar()
    return resultado


def main() -> None:
    problema = SESSAO.erro_de_ambiente()
    if problema:
        # stderr, não stdout: stdout é o canal do protocolo MCP.
        print(f"sync-agents: {problema}", file=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
