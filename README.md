# sync-agentes

API local de sincronização entre agentes — IAs e humanos — trabalhando no mesmo projeto a partir de máquinas diferentes.

Serve pra qualquer projeto, não só gases: `projetos` é a raiz, `tasks` pendura em projeto.

---

## 1. Por que isso existe

O problema original: o projeto de venda de gases tem dois lados — backend (Arthur, com a IA "Especialista") e frontend (Alexandro/"Alex", com a IA "Chefe"). O alinhamento entre os dois acontecia num arquivo markdown gigante (`fbi_back/docs/gases.md`, 643 linhas), passado de mão em mão. Consequências:

- o arquivo não estava versionado, então **não existia diff** — o "Histórico de versões" no topo era changelog escrito à mão;
- decisão, pergunta aberta e pendência de terceiro moravam no mesmo bloco de prosa (§1.4), então nada disso aparecia em nenhum resumo automático;
- ninguém sabia que o outro lado tinha mexido até reler o documento inteiro;
- três documentos anteriores já haviam sido unificados no `gases.md` justamente por dessincronizarem entre si — o mesmo risco continuava.

Alternativas descartadas no caminho até aqui:

| Alternativa | Por que caiu |
|---|---|
| Git (repo compartilhado, PR como conversa) | Diff e autoria vinham de graça, mas o Arthur não quis versionamento nem criar repo só pra isso |
| Pasta de rede compartilhada (SMB), 1 arquivo por mensagem | Simples e sem servidor, mas sem estado consolidado, sem cursor e sem diff calculado |
| `SendMessage` entre sessões Claude Code | Só atravessa a mesma máquina ou sessões cloud da mesma conta. Contas diferentes — não serve |

O que ficou: **mini API na máquina do Arthur, endpoint entregue ao Alex.** As duas IAs escrevem e leem pelos mesmos endpoints, e recebem as mudanças do outro lado em tempo real.

## 2. Requisitos que o relatório tinha que atender

Pedido literal do Arthur, e onde cada item é resolvido:

| Requisito | Onde |
|---|---|
| Resumo geral | seção `## Resumo geral` do `GET /projetos/{slug}/relatorio` |
| Agrupado por tasks | uma seção `## T-00N · título` por task com atividade na janela |
| Identificar quem escreveu | tabela `autores` + `assinatura()` — `Especialista (IA · Arthur)`, `Chefe (IA · Alexandro)`, `Antonio (humano)` |
| Diff por task | tabela `corpos` (versões) + `difflib.unified_diff`, renderizado em bloco ```diff dentro da seção da task |

---

## 3. Como rodar

Dependências: **FastAPI + uvicorn + python-dotenv, declaradas em `pyproject.toml`** (`uv.lock` fixa as versões) — nada instalado global, nada de venv pra manter. O `uv` resolve e baixa em cache na primeira execução (`uv run`).

Host e porta vêm do `.env` (veja `.env.example`), com default `HOST=127.0.0.1` e `PORT=8787`. `run.ps1` aceita `-Bind`/`-Porta` como antes — eles sobrescrevem o `.env` via variável de ambiente antes de chamar `uv run run.py`.

Só nesta máquina (padrão, seguro):

```bash
pwsh -File C:\Users\arthur.macedo\Documents\sync-agentes\run.ps1
```

Exposto na rede, pro Alex alcançar:

```bash
pwsh -File C:\Users\arthur.macedo\Documents\sync-agentes\run.ps1 -Bind 0.0.0.0 -Porta 8787
```

Na primeira execução o servidor **gera o token** e grava em `config.json`. Ele é impresso no start:

```
Banco:  C:\Users\arthur.macedo\Documents\sync-agentes\sync.db
Config: C:\Users\arthur.macedo\Documents\sync-agentes\config.json
Token:  <gerado na primeira execução>
Docs:   http://127.0.0.1:8787/docs
```

`/docs` é o Swagger do FastAPI — as duas IAs conseguem descobrir o contrato inteiro sozinhas por lá.

### Segurança — pendente, e é do Arthur

1. **Regra de firewall de entrada** na porta 8787. É configuração de sistema — o Arthur roda como admin, ou pede pro DevOps. Não foi feita.
2. **Escopo de acesso.** `0.0.0.0` abre pra qualquer um que alcance a máquina na rede corporativa. Restringir ao IP do Alex é o recomendado.
3. **O token vai por canal privado** pro Alex. `config.json` não deve ir pra commit nenhum.
4. **Identidade não é autenticada por autor.** O token é compartilhado e o autor vem no header `X-Autor-Id`, porque o Arthur pediu explicitamente assim ("ele repassa o id do autor que ele está"). Consequência: qualquer um com o token pode escrever assinando como qualquer autor. Aceitável pra alinhamento em rede interna; se um dia precisar de garantia, o caminho é um token por autor.

---

## 4. Modelo de dados

SQLite (`sync.db`), WAL ligado, `foreign_keys = ON`. Seis tabelas.

### `autores` — cadastro, não enum

Começou como enum (`especialista | chefe | arthur | alex`) e o Arthur trocou por cadastro, pra servir a qualquer projeto.

```sql
autores (
  id, tipo TEXT ('ia'|'humano'), nome TEXT UNIQUE,
  responsavel_id INTEGER REFERENCES autores(id), criado_em
)
```

Duas invariantes, garantidas por `CHECK` no banco **e** por validador Pydantic:

- `tipo = 'ia'` → `responsavel_id` **obrigatório** (toda IA tem um humano responsável);
- `tipo = 'humano'` → `responsavel_id` **nulo**.

Mais uma, validada na rota: o responsável de uma IA tem que ser um autor `humano` — IA não responde por IA.

É daqui que sai a autoria do relatório. `Especialista` (IA, responsável Arthur) aparece como `Especialista (IA · Arthur)`.

### `projetos`

```sql
projetos (id, slug TEXT UNIQUE, nome, descricao, status, criado_em, atualizado_em)
```

`status`: `ativo | pausado | concluido | arquivado`. `slug` casa `^[a-z0-9][a-z0-9-]*$` — é ele que aparece na URL.

### `tasks`

```sql
tasks (
  id, projeto_id, codigo TEXT, titulo, status,
  etiquetas TEXT (JSON array), dono_id, criado_em, atualizado_em,
  UNIQUE (projeto_id, codigo)
)
```

- `status`: `ideia | parcial | feito | bloqueado | aguardando_decisao`. Os três primeiros espelham a legenda que o `gases.md` já usava (💡/🟡/✅); `bloqueado` e `aguardando_decisao` são novos — no `gases.md` viviam soltos em prosa, e por isso nunca entravam em contagem nenhuma.
- `codigo` (`T-001`) é único **por projeto**, gerado automático se não vier no POST.
- `etiquetas` é array livre. Substituiu um campo `lado` (`backend|frontend|ambos`) que era específico do projeto de gases — agora `backend`/`frontend` são só etiquetas, e cada projeto define o vocabulário dele.
- `dono_id` aponta pra `autores`, então o dono pode ser IA ou humano (`Antonio`, `Gabriel`, `Clemilson` — as pendências de terceiro do `gases.md` cabem aqui como task `bloqueado` com dono humano).

### `dependencias`

```sql
dependencias (task_id, depende_de_id, PRIMARY KEY (task_id, depende_de_id))
```

Era `bloqueia`/`depende` como dois arrays JSON na task. Virou tabela: **`bloqueia` é a query reversa de `depende`**, não um segundo campo. Não tem como os dois lados discordarem.

### `corpos` — é a base do diff

```sql
corpos (id, task_id, versao, texto, autor_id, criado_em, UNIQUE (task_id, versao))
```

Cada `PUT .../corpo` grava uma versão nova e devolve o diff unificado contra a anterior, já pronto. Nada é sobrescrito.

### `eventos` — trilha única

```sql
eventos (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  projeto_id, task_id, autor_id,
  kind TEXT ('task_criada'|'mensagem'|'campo'|'corpo'|'dependencia'),
  tipo,                    -- ETipoMensagem, só quando kind='mensagem'
  texto,                   -- só quando kind='mensagem'
  campo, valor_de, valor_para,  -- só quando kind='campo'
  versao,                  -- só quando kind='corpo'
  criado_em
)
```

**Decisão central do desenho: uma tabela só, não uma por tipo de evento.** O `seq` autoincrement é o cursor global do projeto, e com isso três coisas diferentes saem da mesma query:

- `GET /projetos/{slug}/mudancas?desde=<seq>` — "o que mudou desde a última vez que eu olhei";
- o relatório (a janela `desde → cursor`);
- o frame do WebSocket.

Mensagem **não** tem tabela própria — é `kind = 'mensagem'`.

`tipo` de mensagem: `mudanca | pergunta | resposta | decisao | bloqueio`. O par `pergunta`/`resposta` não é decorativo: o relatório usa ele pra calcular **pergunta sem resposta** (última `pergunta` da task sem nenhuma `resposta` depois dela).

---

## 5. Contrato HTTP

Toda chamada leva `Authorization: Bearer <token>`. Toda **escrita** leva também `X-Autor-Id: <id>`.

```
GET    /health

POST   /autores                    {tipo, nome, responsavel_id?}
GET    /autores

POST   /projetos                   {slug, nome, descricao?, status?}
GET    /projetos                   inclui contagem de tasks e o cursor atual
PATCH  /projetos/{slug}            {nome?, descricao?, status?}

POST   /projetos/{slug}/tasks      {titulo, codigo?, status?, etiquetas?, dono_id?, corpo?}
GET    /projetos/{slug}/tasks      ?status= &etiqueta=
GET    /projetos/{slug}/tasks/{codigo}          ?com_corpo=true — traz corpo + eventos da task
PATCH  /projetos/{slug}/tasks/{codigo}          {titulo?, status?, etiquetas?, dono_id?}
POST   /projetos/{slug}/tasks/{codigo}/dependencias   {depende_de: "T-001"}

POST   /projetos/{slug}/tasks/{codigo}/mensagens      {tipo, texto}
PUT    /projetos/{slug}/tasks/{codigo}/corpo          {texto}  → devolve {versao, diff}
GET    /projetos/{slug}/tasks/{codigo}/diff           ?desde=<versao>

GET    /projetos/{slug}/mudancas   ?desde=<seq>&limite=200
GET    /projetos/{slug}/relatorio  ?desde=<seq>&formato=md|json&com_diff=true

WS     /ws?projeto=<slug>&token=<token>&autor_id=<id>
GET    /stream?projeto=<slug>&token=<token>&autor_id=<id>     SSE, fallback do WS
```

Notas de comportamento:

- Task é endereçada por `codigo` dentro do projeto (`/projetos/gases/tasks/T-002`), nunca por id numérico global. Sem ambiguidade.
- `PATCH` de task registra **um evento por campo alterado**, com `valor_de` → `valor_para`. Campo cujo valor não mudou de fato não gera evento (o retorno vem com `cursor: null`).
- Toda escrita devolve `cursor` — o `seq` do evento que ela gerou.
- `autor_id` no `/ws` e no `/stream` **filtra o próprio eco**: o agente não é notificado do que ele mesmo escreveu.
- Erro é HTTP status + `detail`, padrão do FastAPI. Não tem envelope próprio.

---

## 5.1 MCP

O mesmo contrato acima também existe como servidor MCP, montado dentro do mesmo FastAPI (mesma porta, mesmo processo) em `/mcp/` — código em [`app/mcp_server.py`](app/mcp_server.py). Serve pra qualquer IA (a do Arthur, a do Alex, e outras que entrarem) usar como tools nativas em vez de montar `curl` na mão.

Cobre o contrato inteiro exceto `/ws`/`/stream` (que são push, não fazem sentido como tool sob demanda) — `autor_criar`, `autor_listar`, `projeto_criar`, `projeto_listar`, `projeto_atualizar`, `task_criar`, `task_listar`, `task_ler`, `task_atualizar`, `task_dependencia_criar`, `task_mensagem_criar`, `task_corpo_atualizar`, `task_diff_ler`, `projeto_mudancas_ler`, `projeto_relatorio_ler`. Cada tool chama a mesma função de `service.py` que a rota REST equivalente já usa — nenhuma lógica de negócio duplicada.

Como o servidor é compartilhado (1 processo, N IAs), `Authorization`/`X-Autor-Id` **não são parâmetro de tool nem config do servidor** — são headers fixados por cada cliente MCP na hora de registrar, exatamente como cada `curl` já leva os seus:

```bash
claude mcp add --scope user --transport http sync-agentes http://<host>:8787/mcp/ \
  --header "Authorization: Bearer <token>" \
  --header "X-Autor-Id: <seu id>"
```

A barra final em `/mcp/` é obrigatória — sem ela o Starlette redireciona (307) e alguns clientes MCP não seguem o redirect. `--scope user` grava em `~/.claude.json`, fora de qualquer repo (o token nunca deve ir pra commit — mesma regra do `config.json`).

---

## 6. Tempo real

O `Monitor` do Claude Code aceita WebSocket nativo. Cada frame vira uma notificação no chat do agente — sem polling, sem cron, sem o agente ter que lembrar de checar:

```
Monitor({
  ws: { url: 'ws://<ip>:8787/ws?projeto=gases&token=<token>&autor_id=<meu-id>' },
  description: 'mudanças do outro lado no projeto gases',
  persistent: true,
})
```

Frame é uma linha só, já legível:

```
[gases] T-001 · Especialista (IA · Arthur) · decisao: Formalizacao fica na OV.
[gases] T-002 · Chefe (IA · Alexandro) · status: parcial -> feito
[gases] T-002 · Especialista (IA · Arthur) · corpo v2
```

Ao receber, o agente busca o detalhe (`GET .../tasks/{codigo}` ou `GET .../mudancas?desde=`) e responde criando mensagem/corpo/patch.

---

## 7. Formato do relatório

`GET /projetos/gases/relatorio?desde=0&formato=md`

```md
# Relatorio — Venda de gases (`gases`)

Gerado em 2026-09-03T18:12:44-03:00 · janela de eventos 0 → 24

## Resumo geral

- **3 tasks**: 1 aguardando decisao · 2 feito
- **14 eventos** na janela
- Quem mexeu: Chefe (IA · Alexandro) 6 · Especialista (IA · Arthur) 8
- **Aguardando decisao:** T-099 (dono: sem dono)
- **Perguntas sem resposta:**
  - T-099 · Chefe (IA · Alexandro): Calendario mostra realizado ou vai pro relatorio?

---

## T-002 · Passagens entre areas   `[feito · backend, frontend · dono Chefe]`

depende de: T-001

### Atividade

- `17:48` **Especialista (IA · Arthur)** · mudanca
    detectarPassagens no UpdateService da OC.
    FATURADO sem gatilho.
- `17:49` **Chefe (IA · Alexandro)** · pergunta
    Qual o shape de movimentacoes[] no GET?
- `17:51` **Especialista (IA · Arthur)** · corpo atualizado (v2)
- `17:52` **Chefe (IA · Alexandro)** · campo `status`: parcial → feito

### Diff do corpo (v1 → v2)

```diff
--- T-002 v1
+++ T-002 v2
-OC_RECEBIDA -> TARA_REGISTRADA -> CARREGADO
+OC_RECEBIDA -> TARA_REGISTRADA -> CARREGADO -> PESAGEM_SAIDA_REGISTRADA -> FATURADO
```
```

Só task **com atividade na janela** entra. `?formato=json` devolve a mesma coisa estruturada, pra IA processar sem parsear markdown.

---

## 8. Estado atual

Feito e verificado:

- `app/` — API completa, dividida por domínio (`autores`, `projetos`, `tasks`, `eventos`) mais `db.py`/`auth.py`/`config.py`/`enums.py` compartilhados e `main.py` montando o FastAPI. Contrato HTTP idêntico ao da versão em arquivo único.
- `run.py` — entrypoint (le `HOST`/`PORT` do `.env` via `app/config.py`, imprime o banner, sobe o uvicorn).
- `run.ps1` — sobe via `uv run run.py`, `-Bind` e `-Porta` como parâmetro (viram variável de ambiente).
- `pyproject.toml` + `uv.lock` — dependências declaradas e travadas.
- `app/mcp_server.py` — mesmo contrato exposto como tools MCP em `/mcp/` (ver §5.1), verificado ponta a ponta com um client MCP real (autor → IA vinculada → projeto → task → diff de corpo → mensagem → patch de status → relatório, e conferido que bate igual via REST).
- `PROTOCOLO.md` — instruções pro agente (é o arquivo que o Alex passa pra IA dele).
- Collection Bruno em `Bruno/` (`bruno.json`, `collection.bru`, `environments/Local.bru`, e uma pasta por domínio — `HEALTH`, `AUTORES`, `PROJETOS`, `TASKS` com `MENSAGENS`/`CORPO`, `EVENTOS`) — todo o contrato REST, testada de ponta a ponta com `bru run`.
- Smoke test de 40 verificações, todas passando: cadastro de autor com as duas invariantes de `responsavel_id`, rejeição de token errado, isolamento entre projetos, código de task duplicado, auto-dependência, dependência reversa (`bloqueia`), diff entre versões, evento por campo no PATCH, cursor, filtro por status e etiqueta, relatório com resumo/autoria/agrupamento/diff, pergunta respondida saindo da lista de abertas, WebSocket entregando com autoria e rejeitando token errado.

Não feito:

- **Regra de firewall e escopo de acesso** — é do Arthur (ver §3).
- **Migração do `gases.md` pra dentro da API.** O `fbi_back/docs/gases.md` continua intacto e é ainda a fonte de verdade do projeto de gases. Ninguém semeou o projeto `gases` nem as tasks. Passo natural seguinte, mas não foi pedido: ler o `gases.md`, criar o projeto, e virar cada item de §1.1/§1.2/§1.3/§1.4 em task com corpo e status.
- **Nada foi commitado.** Esta pasta está fora de qualquer repositório, de propósito.

## 9. Pra retomar em outro chat

O que dizer no chat novo, além de apontar pra este README:

1. A pasta é `C:\Users\arthur.macedo\Documents\sync-agentes`, fora de repo.
2. Ler o pacote `app/` (dividido por domínio — ver seção 8) e `PROTOCOLO.md` antes de mexer.
3. Não existe `tsc`/lint aqui. O gate é o smoke test — se mexer no `app/`, rodar de novo:
   ```bash
   uv run --with httpx2 -- python <caminho>/smoke.py
   ```
   O `smoke.py` vive no scratchpad da sessão original, ou seja: **não sobreviveu.** Se precisar, é reescrevê-lo — ele aponta `app.db.DB_PATH` pra um banco temporário antes de `app.db.iniciar_banco()`, então nunca toca o `sync.db` real.
4. Regras que valeram nesta construção e devem continuar: aprovação explícita antes de mexer em enum/schema; nada de commit ou PR sem pedido; não instalar dependência sem perguntar; acentuação brasileira preservada no texto (o código Python está sem acento por escolha, o markdown e as mensagens ao usuário com acento).
5. Decisões que já foram tomadas e **não** devem ser re-litigadas: git foi descartado pelo Arthur; pasta SMB foi descartada; autor vem por `X-Autor-Id` e não por token; `bloqueia` é query reversa, não campo; evento é tabela única.
