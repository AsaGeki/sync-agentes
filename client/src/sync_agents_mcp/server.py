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
import re
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import Context, MCPServer

from sync_agents_mcp import git_context
from sync_agents_mcp.api import Api, ErroApi
from sync_agents_mcp.enums import EStatusProject, EStatusTask, ETypeMessage, EVisibility
from sync_agents_mcp.git_context import ContextoRepo, descobrir

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
    "lista de candidatos em vez de adivinhar qual. `project` só vale pra "
    "projeto afiliado a este repositório (`link_repo` afilia). Pergunte à pessoa qual "
    "projeto antes de escolher, nunca decida sozinho.\n\n"
    ""
    "PROJETO NOVO OU SEM ACESSO\n"
    "Se `status` não trouxer nenhum projeto pra este repositório: `list_projects` "
    "lista todo projeto que existe no servidor (independe do repositório desta "
    "sessão - existência é pública, mesmo `private`), útil pra achar o slug "
    "certo antes de agir. Repositório sem NENHUM projeto ainda: `create_project` "
    "cria um e já afilia este repositório a ele (funciona mesmo se este "
    "repositório já tiver outro - soma mais um). SEMPRE pergunte à pessoa, "
    "antes de chamar, se o projeto deve ser `public` (qualquer pessoa vê e "
    "entra sozinha, com `join_project`) ou `private` (só entra quem um owner "
    "aceitar) - nunca decida isso sozinho. Ser `public` não coloca ninguém no "
    "projeto: quem tem o repositório vê o projeto com papel nulo e ainda precisa "
    "entrar. Projeto já existe (achou o slug via `list_projects`): se for "
    "`public`, `join_project(project=<slug>)`; se for `private`, "
    "`request_access(project=<slug>)` e espere um owner aceitar (`list_requests` "
    "/ aceitar / recusar, ferramentas do owner). As duas funcionam sem o "
    "repositório desta sessão afiliado a nada. Depois de membro, se este "
    "repositório ainda não está no projeto, `link_repo(project=<slug>)`.\n\n"
    ""
    "MEMBROS\n"
    "`list_members` mostra quem está no projeto. Owner tira alguém com "
    "`remove_member` e troca papel com `set_member_role`; qualquer membro sai "
    "com `leave_project`. As tasks de quem sai ficam sem dono, e o projeto nunca "
    "fica sem owner. Quem foi removido de um projeto `public` pode entrar de "
    "novo sozinho: pra manter alguém fora, o projeto precisa ser `private`.\n\n"
    ""
    "IDENTIDADE\n"
    "Quem assina é a pessoa dona do token desta máquina, e a ferramenta que "
    "escreveu (claude ou codex) vai junto automaticamente. Não existe "
    "cadastro de IA e não dá pra assinar como outra pessoa.\n\n"
    ""
    "MODELO\n"
    "- task (`create_task`/`list_tasks`/`read_task`/`update_task`): unidade de "
    "assunto, endereçada por code. O code é `T-007-slug-do-titulo`: o número "
    "identifica, o slug é pra humano reconhecer sem abrir. Qualquer tool "
    "aceita só o número (`T-007`, `T-7`) ou o code inteiro. "
    "title/status/tags/owner_id + um corpo versionado (`update_task(owner_id=0)` "
    "tira o dono). status: `ideia` (não começou), `em_andamento` (alguém está "
    "fazendo agora - o web mostra quem e por qual ferramenta), `parcial` (tem "
    "parte pronta, ninguém mexendo agora), `feito`, `bloqueado`, "
    "`aguardando_decisao`, `cancelada` (não vai mais ser feita: não trava quem "
    "depende dela e sai do progresso). `dependencies` (codes de outra task) "
    "trava o status 'feito' até elas estarem 'feito' ou 'cancelada', e pode ser "
    "trocada depois por `update_task` - a lista mandada substitui a atual.\n"
    "- feature (`create_feature`/`list_features`/`update_feature`): agrupa "
    "tasks de um mesmo assunto maior, endereçada por code `F-003-slug` (aceita "
    "`F-3`). É opcional: task sem feature é normal, e nada trava por causa de "
    "feature. `create_task(feature=...)` já cria dentro dela; "
    "`update_task(feature=...)` move, e `feature=''` tira. O status da feature "
    "sai das tasks dela, não é setado à mão.\n"
    "- corpo (`read_task`/`update_body`/`read_body_diff`): texto de referência da "
    "task. Cada atualização vira uma versão e o servidor calcula o diff.\n"
    "- evento: trilha do que aconteceu, com branch e commit de onde saiu. "
    "`read_changes(desde=<cursor>)` mostra o que mudou; `read_report` resume o "
    "estado atual.\n\n"
    ""
    "LIDO E NÃO LIDO\n"
    "Toda resposta de tool traz `nao_lidos`: as tasks onde alguém escreveu algo "
    "que você ainda não leu, com a contagem e uma linha do evento mais recente. "
    "Aquilo é só um aviso - o conteúdo está na task. `read_task` é o que marca "
    "lido, e a task só some do `nao_lidos` depois que você abrir ela. Nada "
    "expira sozinho e nada é consumido por você ter chamado outra tool, então "
    "não existe 'perdi a mensagem'.\n"
    "Task com pergunta não lida vem primeiro; se a pergunta não for o evento "
    "mais recente da task, ela vem em `pergunta`. O aviso mostra no máximo 20 "
    "tasks: `nao_lidos_omitidos` diz quantas ficaram de fora. Criar, editar ou "
    "apagar feature vem em `nao_lidos_features`; quem marca lido é "
    "`list_features` (`read_feature` não marca).\n"
    "`list_tasks(nao_lidas=True)` lista só o que está pendente de leitura, sem "
    "o corte de 20; `list_tasks(q='texto')` procura no code, no título e no "
    "corpo. `list_tasks` devolve a linha de triagem de cada task, em páginas de "
    "50 (`total` e `proximo` dizem se há mais): abra a task com `read_task`.\n\n"
    ""
    "TIPO DE MENSAGEM (`send_message`)\n"
    "- mudanca: 'fiz/mudei isso'.\n"
    "- pergunta: precisa de resposta do outro lado - fica na lista de perguntas "
    "abertas do relatório até ser respondida. Use quando travou de verdade.\n"
    "- resposta: fecha a pergunta em aberto mais antiga da task. Duas perguntas "
    "em aberto precisam de duas respostas.\n"
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
    "verificado. Ao começar a mexer numa task, marque `em_andamento`; ao "
    "parar, devolva pra `parcial`, `feito` ou `bloqueado` (ou `cancelada`, se "
    "deixou de valer a pena). Task esquecida em "
    "andamento aparece como parada pra todo mundo.\n"
    "5. `update_body` leva sempre o texto COMPLETO da task, nunca um "
    "fragmento.\n"
    "6. Toda resposta de tool traz `nao_lidos` quando o outro lado escreveu "
    "algo que você ainda não abriu - você não precisa perguntar se mudou "
    "alguma coisa, e ninguém precisa te mandar sincronizar. Viu a task em "
    "`nao_lidos`, abra com `read_task` antes de responder: a linha do aviso é "
    "só o começo do que foi escrito.\n"
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
        # Versão do corpo que esta sessão viu por task (`(slug, número)`), pra
        # `update_body` mandar `versao_base` sem depender de a IA lembrar.
        self.versoes_corpo: dict[tuple[str, int], int] = {}

    def lembrar_versao(self, slug: str, code: str, versao: int | None) -> None:
        chave = _chave_task(slug, code)
        if chave is not None and versao is not None:
            self.versoes_corpo[chave] = versao

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


def _chave_task(slug: str, code: str) -> tuple[str, int] | None:
    """`T-7`, `T-007` e `T-007-slug` são a mesma task."""
    achado = re.match(r"^\s*[Tt]-0*(\d+)", code)
    return (slug, int(achado.group(1))) if achado else None


def _como_entrar(projeto: dict[str, Any]) -> str:
    if projeto["visibility"] == EVisibility.public:
        return "ainda não é membro - entre com join_project"
    return "ainda não é membro - peça com request_access"


def _agent_do_cliente(ctx: Context) -> str:
    """Nome que o cliente MCP se dá no handshake ('claude-code', 'codex'...).
    O servidor normaliza; aqui só repassa o que veio."""
    try:
        return ctx.session.client_params.client_info.name
    except AttributeError:
        return "outro"


def _nao_lidos(api: Api, slug: str) -> dict[str, Any]:
    """As tasks com evento que esta pessoa ainda não leu (`tasks`, cortada pelo
    servidor) e quantas existem antes do corte (`total`). Vai anexado em toda
    resposta - é o que dispensa alguém pedir 'sincroniza no sync'.

    Não consome nada: a task só sai daqui quando `read_task` abrir ela. Por isso
    o que aparece aqui é sempre uma chamada curta, e o conteúdo inteiro do que
    o outro lado escreveu continua disponível."""
    return api.request("GET", f"/projetos/{slug}/nao-lidos")


def _chamar(ctx: Context, project: str | None, acao, exige_afiliado: bool = True) -> Any:
    """Envelope comum de toda tool: valida ambiente, decide qual projeto usar,
    executa e anexa o que está por ler do outro lado.

    `project` explícito precisa ser um dos projetos afiliados ao repositório
    desta sessão: o repositório é o escopo. A exceção é `exige_afiliado=False`
    (`request_access`), que age num projeto cujo repo ainda não foi linkado.
    `project` omitido resolve pelos projetos afiliados (sozinho com exatamente 1)."""
    problema = SESSAO.erro_de_ambiente()
    if problema:
        return {"erro": problema}
    if project is not None and not exige_afiliado:
        slug = project
        api = SESSAO.api_avulsa(ctx)
    else:
        try:
            SESSAO.conectar(ctx)
        except ErroApi as erro:
            return {"erro": erro.detalhe, "status": erro.status}
        if project is not None:
            if project not in [p["slug"] for p in SESSAO.projetos]:
                return {
                    "erro": f"O projeto '{project}' não está afiliado a este repositório. "
                    f"Use link_repo(project='{project}') pra afiliar, ou abra o chat "
                    "no repositório dele.",
                    "projetos": [p["slug"] for p in SESSAO.projetos],
                }
            slug = project
        else:
            slug = SESSAO.resolver_slug()
            if isinstance(slug, dict):
                return slug
        escolhido = next((p for p in SESSAO.projetos if p["slug"] == slug), None)
        if escolhido is not None and escolhido["role"] is None:
            return {"erro": f"Você ainda não é membro de '{slug}': {_como_entrar(escolhido)}."}
        api = SESSAO.api
    try:
        resultado = acao(api, slug)
    except ErroApi as erro:
        return {"erro": erro.detalhe, "status": erro.status}

    # Objeto na raiz sempre: lista crua vira um content block por item no MCP, e
    # `nao_lidos` não teria onde entrar.
    envelope = resultado if isinstance(resultado, dict) else {"resultado": resultado}

    # Fora do try acima: falha aqui não pode transformar escrita bem-sucedida em
    # erro, senão o agente repete a escrita. Mas ela aparece na resposta - sem
    # isso, "não consegui buscar" chegaria como "nada novo".
    try:
        aviso = _nao_lidos(api, slug)
    except ErroApi as erro:
        return {**envelope, "nao_lidos_indisponivel": erro.detalhe}
    resposta = dict(envelope)
    if aviso["tasks"]:
        resposta["nao_lidos"] = aviso["tasks"]
        omitidos = aviso["total"] - len(aviso["tasks"])
        if omitidos:
            resposta["nao_lidos_omitidos"] = omitidos
    if aviso.get("features"):
        resposta["nao_lidos_features"] = aviso["features"]
    return resposta


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
    branch, commit = git_context.ponto_atual(SESSAO.repo.raiz)
    return {
        "repo": SESSAO.repo.name,
        "branch": branch,
        "commit": commit,
        "assino_como": eu["alias"],
        "agent": _agent_do_cliente(ctx),
        "projetos": [
            {
                "slug": p["slug"],
                "name": p["name"],
                "visibility": p["visibility"],
                "papel": p["role"] or _como_entrar(p),
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

    SEMPRE pergunte à pessoa se o projeto deve ser `public` (qualquer um vê e
    entra sozinho com `join_project`) ou `private` (entra quem um owner aceitar)
    antes de chamar - não decida sozinho."""
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
    q: str | None = None,
    nao_lidas: bool = False,
    feature: str | None = None,
    sem_feature: bool = False,
    resumo: bool = True,
    limite: int = 50,
    deslocamento: int = 0,
    project: str | None = None,
) -> Any:
    """Lista as tasks do projeto, em ordem de code. `q` procura no code, no
    título e no corpo. `nao_lidas=True` traz só as que têm evento que você ainda
    não leu. `feature='F-3'` filtra por feature; `sem_feature=True` traz só as
    avulsas.

    Por padrão vem a linha de triagem de cada task (code, título, status, dono,
    feature, tags, `nao_lidos`, `dependencias_pendentes` e `fazendo_agora` quando
    houver): pra ler uma task é `read_task`. `resumo=False` traz a task completa.

    A resposta é uma página: `total` diz quantas tasks passam nos filtros e
    `proximo` é o `deslocamento` pra pedir a seguinte (vazio na última). Se
    `total` for maior que `limite`, há mais - não conclua que uma task não existe
    sem conferir `proximo` ou filtrar com `q`."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "GET",
            f"/projetos/{slug}/tasks",
            query={
                "status": status,
                "tag": tag,
                "q": q,
                "nao_lidas": nao_lidas,
                "feature": feature,
                "sem_feature": sem_feature,
                "resumo": resumo,
                "limite": limite,
                "deslocamento": deslocamento,
            },
        ),
    )


@mcp.tool()
def read_task(ctx: Context, code: str, com_corpo: bool = True, project: str | None = None) -> Any:
    """Lê 1 task, com o corpo atual e a trilha completa de eventos dela. Abrir a
    task marca ela como lida.

    `code` aceita o code inteiro (`T-007-migrar-relatorio`) ou só o número
    (`T-007`, `T-7`)."""

    def acao(api: Api, slug: str) -> Any:
        task = api.request("GET", f"/projetos/{slug}/tasks/{code}", query={"com_corpo": com_corpo})
        SESSAO.lembrar_versao(slug, task["code"], task["versao_corpo"])
        return task

    return _chamar(ctx, project, acao)


@mcp.tool()
def create_task(
    ctx: Context,
    title: str,
    code: str | None = None,
    status: EStatusTask = EStatusTask.ideia,
    tags: list[str] | None = None,
    owner_id: int | None = None,
    corpo: str | None = None,
    dependencies: list[str] | None = None,
    feature: str | None = None,
    project: str | None = None,
) -> Any:
    """Cria uma task. O code sai como `T-007-slug-do-titulo`: o número endereça
    (e resolve sozinho em qualquer tool), o slug é pra gente reconhecer a task
    sem abrir. `code` explícito só define o número. `corpo` vira a v1.

    `dependencies` são codes de outras tasks do mesmo projeto - esta task não
    pode ir pra status 'feito' enquanto elas não estiverem.

    `feature` (code `F-3`) cria a task dentro da feature; omitido, a task fica
    avulsa."""

    def acao(api: Api, slug: str) -> Any:
        task = api.request(
            "POST",
            f"/projetos/{slug}/tasks",
            {
                "title": title,
                "code": code,
                "status": status.value,
                "tags": tags or [],
                "owner_id": owner_id,
                "corpo": corpo,
                "dependencies": dependencies or [],
                "feature": feature,
            },
        )
        SESSAO.lembrar_versao(slug, task["code"], task["versao_corpo"])
        return task

    return _chamar(ctx, project, acao)


@mcp.tool()
def update_task(
    ctx: Context,
    code: str,
    title: str | None = None,
    status: EStatusTask | None = None,
    tags: list[str] | None = None,
    owner_id: int | None = None,
    dependencies: list[str] | None = None,
    feature: str | None = None,
    project: str | None = None,
) -> Any:
    """Atualiza campos da task. Gera 1 evento por campo que de fato mudou.

    `dependencies` é a lista completa, não incremental - o que você mandar
    substitui as dependências atuais, e `[]` remove todas. Dependência que
    fecharia ciclo é recusada.

    Tirar uma task de 'feito' ou 'cancelada' pra um status aberto devolve pra
    'parcial', em cascata, quem dependia dela e já estava fechado.

    `owner_id=0` tira o dono; omitir `owner_id` não mexe nele.

    `status='cancelada'` diz que a task não vai mais ser feita: quem depende
    dela pode fechar e ela sai do total do progresso.

    `status='em_andamento'` avisa o outro lado que você está nela agora; o
    servidor guarda quem e por qual ferramenta. Ao parar, volte pra 'parcial',
    'feito' ou 'bloqueado'.

    `feature` move a task pra outra feature; `feature=''` tira ela da feature."""
    corpo = {
        "title": title,
        "status": status.value if status else None,
        "tags": tags,
        "owner_id": owner_id,
        "dependencies": dependencies,
        "feature": feature,
    }
    enviado = {k: v for k, v in corpo.items() if v is not None}
    if owner_id == 0:
        enviado["owner_id"] = None
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("PATCH", f"/projetos/{slug}/tasks/{code}", enviado),
    )


# ---------- features ---------- #


@mcp.tool()
def create_feature(
    ctx: Context, title: str, description: str | None = None, project: str | None = None
) -> Any:
    """Cria uma feature: agrupador de tasks de um mesmo assunto maior. O code
    sai como `F-003-slug-do-titulo`. Feature é opcional - só crie quando houver
    mais de uma task no mesmo assunto."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "POST", f"/projetos/{slug}/features", {"title": title, "description": description}
        ),
    )


@mcp.tool()
def list_features(ctx: Context, project: str | None = None) -> Any:
    """Lista as features do projeto com o status derivado das tasks (ideia,
    em_andamento, parcial, bloqueado, feito) e o progresso `feito/total`, sem
    contar as tasks canceladas. As tasks de uma feature saem em
    `list_tasks(feature='F-3')`.

    Marca como lido o que mudou nas features (`nao_lidos_features`)."""
    return _chamar(
        ctx, project, lambda api, slug: api.request("GET", f"/projetos/{slug}/features")
    )


@mcp.tool()
def read_feature(ctx: Context, code: str, project: str | None = None) -> Any:
    """Lê 1 feature: descrição, status derivado e progresso. Não marca como lido
    o que mudou nas features (isso é do `list_features`)."""
    return _chamar(
        ctx, project, lambda api, slug: api.request("GET", f"/projetos/{slug}/features/{code}")
    )


@mcp.tool()
def update_feature(
    ctx: Context,
    code: str,
    title: str | None = None,
    description: str | None = None,
    project: str | None = None,
) -> Any:
    """Atualiza título ou descrição da feature. Status não se atualiza aqui:
    ele sai das tasks."""
    corpo = {"title": title, "description": description}
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "PATCH",
            f"/projetos/{slug}/features/{code}",
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

    O servidor recusa (409) se o outro lado tiver gravado depois da versão que
    você leu, em vez de apagar o que ele escreveu: nesse caso releia a task com
    `read_task`. A versão vem do último `read_task` (ou `update_body`) desta
    sessão; `versao_base` só é preciso pra usar outra, e uma task que você nunca
    abriu grava sem essa checagem."""

    def acao(api: Api, slug: str) -> Any:
        chave = _chave_task(slug, code)
        base = versao_base if versao_base is not None else SESSAO.versoes_corpo.get(chave)
        gravado = api.request(
            "PUT",
            f"/projetos/{slug}/tasks/{code}/corpo",
            {"texto": texto, "versao_base": base},
        )
        SESSAO.lembrar_versao(slug, code, gravado["versao"])
        return gravado

    return _chamar(ctx, project, acao)


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
        arquivos = git_context.arquivos_alterados(SESSAO.repo.raiz, partida)
        if arquivos is None:
            return {
                "erro": (
                    f"O git não conseguiu comparar {partida[:7]} com o commit atual "
                    "(commit inexistente neste clone ou git demorou demais) - nada foi publicado."
                )
            }
        return api.request(
            "POST",
            f"/projetos/{slug}/tasks/{code}/diffs",
            {
                "base_sha": partida,
                "arquivos": arquivos,
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
    """A trilha de eventos do projeto inteiro desde um cursor, incluindo os seus.
    Omitindo `desde`, continua de onde esta tool parou nesta sessão.

    Para saber o que falta ler é `nao_lidos`/`list_tasks(nao_lidas=True)`, que
    não dependem de cursor nem da sessão: aqui o cursor anda, e ele vive só
    enquanto este processo estiver de pé."""

    def acao(api: Api, slug: str) -> Any:
        resposta = api.request(
            "GET",
            f"/projetos/{slug}/mudancas",
            query={
                "desde": SESSAO.cursores.get(slug, 0) if desde is None else desde,
                "limite": limite,
            },
        )
        SESSAO.cursores[slug] = resposta["cursor"]
        return resposta

    return _chamar(ctx, project, acao)


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
def remove_member(ctx: Context, person_id: int, project: str | None = None) -> Any:
    """Tira alguém do projeto (`person_id` vem de `list_members`). Só owner. As
    tasks que eram da pessoa ficam sem dono. O projeto nunca fica sem owner:
    quem é o único owner precisa promover outro antes.

    Num projeto `public` a pessoa removida pode entrar de novo sozinha
    (`join_project`); pra manter alguém fora, o projeto precisa ser `private`."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("DELETE", f"/projetos/{slug}/membros/{person_id}"),
    )


@mcp.tool()
def set_member_role(
    ctx: Context, person_id: int, role: Literal["owner", "member"], project: str | None = None
) -> Any:
    """Promove a owner ou rebaixa a member (`person_id` vem de `list_members`).
    Só owner. Rebaixar o único owner é recusado."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request(
            "PATCH", f"/projetos/{slug}/membros/{person_id}", {"role": role}
        ),
    )


@mcp.tool()
def leave_project(ctx: Context, project: str | None = None) -> Any:
    """Você sai do projeto. As tasks que eram suas ficam sem dono. O único owner
    não pode sair: promova outro membro antes (`set_member_role`). Num projeto
    `public` você pode entrar de novo quando quiser (`join_project`)."""
    return _chamar(
        ctx, project, lambda api, slug: api.request("POST", f"/projetos/{slug}/sair")
    )


@mcp.tool()
def join_project(ctx: Context, project: str) -> Any:
    """Entra num projeto `public` sem precisar de aprovação (`project` é o slug,
    de `list_projects`). Ser público é poder ver e entrar: ninguém vira membro
    sozinho só por ter o repositório. Em projeto `private` use `request_access`."""
    resultado = _chamar(
        ctx,
        project,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/entrar"),
        exige_afiliado=False,
    )
    SESSAO.projetos = None  # o papel mudou: re-resolve no próximo conectar()
    return resultado


@mcp.tool()
def request_access(ctx: Context, project: str | None = None) -> Any:
    """Pede acesso de escrita a um projeto `private` que você ainda não é
    membro. Fica pendente até um owner aceitar ou recusar (`list_requests` e
    as tools de aceitar/recusar, do owner)."""
    return _chamar(
        ctx,
        project,
        lambda api, slug: api.request("POST", f"/projetos/{slug}/pedidos"),
        exige_afiliado=False,
    )


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

    Só quem já é membro consegue linkar: entre antes com `join_project`
    (`public`) ou `request_access` (`private`)."""
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
