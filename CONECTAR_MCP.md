# Conectar ao sync-agents

Você e outra pessoa estão mexendo no mesmo produto, de máquinas diferentes, cada um com sua IA. O sync-agents é o canal onde os dois lados registram o que está acontecendo — tarefas, decisões, perguntas, o diff do que mudou no código — e cada IA lê e escreve nele direto, sem ninguém copiar markdown na mão.

O que muda pra você depois de conectar: **você abre o chat na pasta do projeto e pronto**. A sua IA já sabe em que projeto está (é o repositório git), já sabe assinar com o seu nome, e já recebe o que o outro lado escreveu. Você não digita nome de projeto, não cria usuário, não fica pedindo "dá uma olhada no sync".

Conectar leva uns 5 minutos e é uma vez só por máquina — vale pra todos os seus projetos.

---

## Antes de começar

Três coisas:

**1. Git instalado, com seu email configurado.** Confira:

```bash
git config --global user.email
```

Se não imprimir nada, configure — é esse email que vira sua assinatura no canal:

```bash
git config --global user.email "seu.nome@empresa.com"
git config --global user.name "Seu Nome"
```

**2. O endereço do servidor e o seu token.** Peça pra quem subiu o servidor (só essa pessoa consegue gerar). Você vai receber duas linhas, mais ou menos assim:

```
servidor: http://192.168.0.42:8787
token:    kR7x2mQp...
```

O token é seu e pessoal — é ele que diz que foi você quem escreveu. Não passe pra ninguém e não commite em lugar nenhum.

**3. Seu app de IA**: Claude Code, Claude Desktop, Cursor, VS Code com Copilot, Codex — qualquer um que aceite MCP.

---

## Passo 1 — Instalar o `uv`

O sync-agents roda na sua máquina como um programinha que lê o `.git` da pasta e conversa com o servidor. O `uv` é o que baixa e roda esse programa sozinho, sem você instalar Python nem manter nada.

Escolha a linha do seu caso e cole no terminal:

**Windows — Prompt de Comando (cmd):**

```bash
winget install --id=astral-sh.uv -e
```

**Windows — PowerShell:**

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS ou Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Feche e reabra o terminal** (o instalador mexe no PATH) e confirme:

```bash
uv --version
```

Se imprimiu uma versão, terminou. Se disser que o comando não existe, reabra o terminal de novo — em Windows às vezes precisa de duas.

> **Já tem Python e prefere não instalar o `uv`?** Funciona também:
> ```bash
> pip install --user git+https://github.com/AsaGeki/sync-agentes
> ```
> Depois, em toda configuração abaixo, troque `uvx` por `sync-agents-mcp` e apague a linha dos `args` que começa com `--from`.

---

## Passo 2 — Ligar no seu app de IA

Ache o seu caso abaixo. Troque **`http://SERVIDOR:8787`** pelo endereço que te passaram e **`SEU-TOKEN`** pelo seu token; o resto vai como está.

### Claude Code (terminal ou extensão de IDE)

Uma linha, e serve pra todos os seus projetos:

```bash
claude mcp add --scope user sync-agents --env SYNC_AGENTS_URL=http://SERVIDOR:8787 --env SYNC_AGENTS_TOKEN=SEU-TOKEN -- uvx --from git+https://github.com/AsaGeki/sync-agentes sync-agents-mcp
```

`--scope user` grava a configuração no seu perfil, fora de qualquer repositório — seu token não corre risco de ir pra um commit.

Depois de rodar, confira com `claude mcp list`. **A primeira checagem costuma falhar** ("Failed to connect" / "Request timed out") - é o `uvx` baixando e compilando o pacote a frio na sua máquina, não um problema de configuração. Roda `claude mcp list` de novo: da segunda vez o pacote já está em cache e conecta rápido.

### Cursor

Crie ou edite `~/.cursor/mcp.json` (no Windows: `C:\Users\SEU-USUARIO\.cursor\mcp.json`):

```json
{
  "mcpServers": {
    "sync-agents": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AsaGeki/sync-agentes", "sync-agents-mcp"],
      "env": {
        "SYNC_AGENTS_URL": "http://SERVIDOR:8787",
        "SYNC_AGENTS_TOKEN": "SEU-TOKEN"
      }
    }
  }
}
```

Reinicie o Cursor.

### VS Code (GitHub Copilot)

Mesmo conteúdo do Cursor, no arquivo `.vscode/mcp.json` dentro do projeto — mas troque `"mcpServers"` por `"servers"`. Como esse arquivo mora no repositório, **não coloque o token ali**: deixe `"SYNC_AGENTS_TOKEN": "${env:SYNC_AGENTS_TOKEN}"` e defina a variável de ambiente na sua máquina.

### Claude Desktop

O Claude Desktop é um chat solto — ele não tem "a pasta do projeto aberta". Então aqui você aponta o repositório na mão, e faz **uma entrada por projeto**.

Edite o arquivo de configuração:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "sync-loja": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AsaGeki/sync-agentes", "sync-agents-mcp"],
      "env": {
        "SYNC_AGENTS_URL": "http://SERVIDOR:8787",
        "SYNC_AGENTS_TOKEN": "SEU-TOKEN",
        "SYNC_AGENTS_REPO": "C:\\Users\\voce\\projetos\\loja-api"
      }
    }
  }
}
```

`SYNC_AGENTS_REPO` é o caminho da pasta do repositório na sua máquina. No Windows, as barras invertidas vão dobradas (`\\`), como no exemplo. Pra um segundo projeto, adicione outra entrada com outro nome (`"sync-portal"`) e outro caminho.

Reinicie o Claude Desktop.

### Outro app

Qualquer cliente MCP serve. Ele precisa executar este comando:

```
uvx --from git+https://github.com/AsaGeki/sync-agentes sync-agents-mcp
```

com as variáveis `SYNC_AGENTS_URL` e `SYNC_AGENTS_TOKEN` no ambiente, e — se o app não abre uma pasta de projeto — também `SYNC_AGENTS_REPO` apontando o repositório.

---

## Passo 3 — Conferir

Abra o chat **dentro da pasta do projeto** e peça:

> Roda o `status` do sync-agents.

Se o repositório já tem projeto (alguém já criou ou linkou), deve voltar algo assim:

```
repo:         loja-api
branch:       feat/T-003-login
assino_como:  arthur.macedo
projetos:     [{ slug: loja-api, papel: owner, visibility: team }]
```

Se voltou isso, acabou — está conectado. `projetos` normalmente tem 1 item; se tiver mais de 1, as outras tools vão pedir `project=<slug>` pra saber qual usar.

**Primeira vez neste repositório?** `status` volta dizendo que não há projeto afiliado - não é erro, é esperado. Peça pra IA criar:

> Cria um projeto pra este repositório.

Ela vai perguntar se é `team` (qualquer um com o repositório entra sozinho) ou `private` (só entra quem um owner aceitar) antes de criar. Se o projeto já existe mas é `private` e você ainda não é membro, peça:

> Pede acesso a este projeto.

Fica pendente até um owner aceitar.

---

## Como isso funciona no dia a dia

Você conversa com a sua IA normalmente. Quando algo interessa ao outro lado, é ela quem registra:

> "Terminei o endpoint de login, avisa o pessoal no sync."

A IA cria ou atualiza a task e publica o diff do que você mudou — arquivos e tudo. Do outro lado, a IA da outra pessoa recebe isso na próxima coisa que ela fizer, sem ninguém pedir.

Vocabulário que vale conhecer, porque é o que aparece no relatório:

| O quê | Pra quê |
|---|---|
| **task** | um assunto. Tem código (`T-001`), status, dono e um texto de referência versionado |
| **mudanca** | "fiz isso" |
| **pergunta** | você travou e precisa do outro lado. Fica listada como pendente até alguém responder |
| **resposta** | destrava a pergunta da task |
| **decisao** | "ficou combinado assim" — é o que você quer poder achar daqui a três meses |
| **bloqueio** | não dá pra seguir, e por quê |
| **diff** | o que mudou no código entre dois commits, publicado na task |

Pra saber onde tudo está:

> "Me dá o relatório do projeto."

Volta um resumo por task: status atual, o que mudou, em que branch e entre quais commits, e o que está esperando resposta.

**Uma regra que importa:** você só toca nos projetos afiliados ao repositório desta sessão — não existe jeito de a IA alcançar o projeto de outro repositório. O comum é 1 projeto por repositório, mas o mesmo repositório pode servir mais de 1 projeto (times diferentes usando o mesmo código pra assuntos diferentes); nesse caso a IA pergunta qual antes de agir.

---

## Deu problema?

| O que aparece | Por quê | O que fazer |
|---|---|---|
| "não está dentro de um repositório git" | o chat foi aberto fora da pasta do projeto, ou o repositório ainda não tem nenhum commit | abra o chat na pasta certa; se o repositório é novo, faça o primeiro commit. No Claude Desktop, confira o caminho em `SYNC_AGENTS_REPO` |
| "SYNC_AGENTS_TOKEN não está no ambiente" | o token não chegou no programa | confira se está escrito certo na configuração e reinicie o app inteiro, não só o chat |
| "Token não corresponde a nenhuma pessoa cadastrada" | token errado, ou foi gerado outro pra você (gerar um novo cancela o anterior) | peça o token atual pra quem administra |
| "Servidor inacessível" | o servidor está desligado, o endereço está errado, ou o firewall está bloqueando | confira abrindo `http://SERVIDOR:8787/health` no navegador. Se não abrir, o problema é do servidor ou da rede, não seu |
| "é privado - peça a um owner pra te adicionar" | o projeto está fechado | peça pra alguém que já está nele te adicionar pelo seu email |
| `uvx` não é reconhecido | terminal aberto antes da instalação do `uv`, ou instalação incompleta | feche e reabra o terminal (e o app de IA). Confira com `uv --version` |
| a IA não sabe que o sync existe | o app não carregou o MCP | reinicie o app; no Claude Code, `claude mcp list` mostra se está registrado |
| tempo real recusado com 403 | token inválido, ou você não é membro desse projeto | confira o token e peça acesso ao projeto se ele for privado |

---

## Referência

Precisa de detalhe? Está tudo aqui.

### O que a IA consegue fazer

`status` (onde estou) · `create_project` · `request_access` · `list_requests` · `approve_request` · `reject_request` · `list_tasks` · `read_task` · `create_task` · `update_task` · `send_message` · `update_body` · `read_body_diff` · `publish_diff` · `list_diffs` · `read_changes` · `read_report` · `list_members` · `add_member` · `update_project` · `link_repo`

Todas aceitam `project` (slug) opcional. Com 1 projeto só afiliado ao repositório, pode omitir. Com mais de 1, é obrigatório — chamar sem devolve a lista de candidatos em vez de adivinhar. Toda resposta traz `novidades` quando o outro lado escreveu algo desde a última chamada — é por isso que ninguém precisa mandar sincronizar.

As regras de conduta do canal (quando usar cada tipo de mensagem, não reescrever o texto do outro lado, mandar o corpo sempre inteiro) vêm nas instruções do próprio servidor MCP: todo cliente mostra isso pra IA assim que ela conecta, então você não precisa repassar nada.

### Modelo de dados

- **`people`** — quem escreve. O email é a chave e a parte antes do `@` vira o `alias` da assinatura. **A IA não é um cadastro**: quem assina é sempre uma pessoa, e a ferramenta usada (claude, codex, cursor) fica no campo `agent` do evento.
- **`projects`** — criado explícito por `create_project` (repositório desconhecido não cria projeto sozinho, devolve 404), ligado ao repositório pelo sha do commit raiz (igual em todo clone, não muda se a pasta for renomeada). A relação é N-pra-N: um projeto pode ter mais de um repositório (`link_repo` junta frontend e backend no mesmo canal) e o mesmo repositório pode estar em mais de um projeto (times diferentes usando o mesmo código pra assuntos diferentes) - nesse caso as tools pedem `project=<slug>`. A lista de projetos (`list_projects`/`GET /projetos`) é pública - todo mundo vê que um projeto existe; ler e escrever o conteúdo dele (tasks, corpo, eventos) continua exigindo membership.
- **`memberships`** — quem tem acesso de escrita, como `owner` ou `member`. Projeto `team` deixa quem tem o repositório entrar sozinho; projeto `private` exige pedido (`request_access`) que um owner aceita ou recusa (`list_requests`/aceitar/recusar).
- **`tasks`** — assunto, endereçado por `code` (`T-001`), com corpo versionado (cada atualização gera diff contra a anterior).
- **`events`** — a trilha de tudo, carimbada com quem, qual ferramenta, qual branch e qual commit. É dela que saem "o que mudou desde X", o relatório e a notificação em tempo real.

Todo evento chega no mesmo formato, seja pela API, pelo tempo real ou pelo relatório:

```json
{
  "seq": 42,
  "kind": "diff.published",
  "created_at": "2026-09-09T14:03:00-03:00",
  "project": "loja-api",
  "task": "T-003",
  "actor": { "person": "arthur.macedo", "name": "Arthur", "agent": "claude" },
  "git": { "branch": "feat/T-003-login", "commit": "d4e5f6a" },
  "payload": { "base_sha": "a1b2c3d", "head_sha": "d4e5f6a", "arquivos": ["src/auth.py"] },
  "resumo": "[loja-api] T-003 · arthur.macedo · claude (feat/T-003-login) · diff a1b2c3d..d4e5f6a: 1 arquivo(s)"
}
```

`kind` é um destes: `task.created`, `task.field_changed`, `body.updated`, `message.created`, `diff.published`. O `agent` é `claude`, `codex`, `human` ou `outro`.

### Sem MCP, ou pra montar uma tela

O mesmo contrato existe como API REST, navegável em `http://SERVIDOR:8787/docs`, com o seu token no cabeçalho `Authorization: Bearer`. Pra acompanhar em tempo real fora de um agente, `GET /stream` (SSE) e `WS /ws` mandam o mesmo envelope acima. `GET /health` diz a versão no ar; `GET /changelog` traz o histórico de mudanças de contrato.
