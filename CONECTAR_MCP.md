# Conectar ao sync-agents

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

**3. Seu app de IA**: Claude Code ou Codex.

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

---

## Passo 2 — Ligar no seu app de IA

Troque `http://SERVIDOR:8787` pelo endereço recebido e `SEU-TOKEN` pelo seu token.

### Claude Code

```bash
claude mcp add --scope user sync-agents --env SYNC_AGENTS_URL=http://SERVIDOR:8787 --env SYNC_AGENTS_TOKEN=SEU-TOKEN -- uvx sync-agents-mcp
```

Esse comando configura o Claude Code. Para usar o Claude Desktop, configure o MCP nele separadamente; depois, feche e abra o Claude Desktop novamente para carregar a conexão.

### Codex

No terminal, registre o MCP para o Codex:

```bash
codex mcp add --env SYNC_AGENTS_URL=http://SERVIDOR:8787 --env SYNC_AGENTS_TOKEN=SEU-TOKEN sync-agents -- uvx sync-agents-mcp
```

Feche e abra o Codex novamente para carregar a conexão.

---

## Passo 3 — Conferir

Abra o chat **dentro da pasta do projeto** e peça:

> Roda o `status` do sync-agents.

Se o repositório já tem projeto (alguém já criou ou linkou), deve voltar algo assim:

```
repo:         loja-api
branch:       feat/T-003-login
assino_como:  arthur.macedo
projetos:     [{ slug: loja-api, papel: owner, visibility: public }]
```

Se voltou isso, acabou — está conectado. `projetos` normalmente tem 1 item; se tiver mais de 1, as outras tools vão pedir `project=<slug>` pra saber qual usar.

**Primeira vez neste repositório?** `status` volta dizendo que não há projeto afiliado - não é erro, é esperado. Peça pra IA criar:

> Cria um projeto pra este repositório.

Ela vai perguntar se é `public` (qualquer pessoa vê o projeto e entra sozinha, com `join_project`) ou `private` (só entra quem um owner aceitar) antes de criar. Ser `public` não coloca ninguém no projeto: quem tem o repositório vê o projeto com papel nulo e ainda precisa entrar.

**O projeto já existe, mas você ainda não é membro?** Se for `public`, peça pra IA entrar - não precisa de aprovação:

> Entra no projeto X.

Se for `private`, peça acesso:

> Pede acesso ao projeto X.

Fica pendente até um owner aceitar. Depois de membro, se este repositório ainda não está no projeto, peça pra linkar:

> Linka este repositório ao projeto X.

**Sair ou tirar alguém:** `leave_project` (você sai), `remove_member` e `set_member_role` (só owner). O projeto nunca fica sem owner, e quem foi removido de um projeto `public` pode entrar de novo sozinho: pra manter alguém fora, o projeto precisa ser `private`.
