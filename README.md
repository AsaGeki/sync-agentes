# sync-agents

Canal de alinhamento entre pessoas — e as IAs delas — trabalhando no mesmo projeto de máquinas diferentes.

O escopo não é digitado por ninguém: **o repositório git onde o chat foi aberto define o projeto**. Nenhuma tool recebe nome de projeto, então nenhum agente escreve no lugar errado nem esbarra no assunto de um projeto que não é dele.

Quer conectar sua IA? Veja [CONECTAR_MCP.md](CONECTAR_MCP.md).

## Como funciona

Três coisas saem do git sozinhas, e é isso que faz o resto ser simples:

| Sinal | Vira |
|---|---|
| sha do commit raiz | chave do projeto — igual em todo clone, sobrevive a rename de pasta e troca de remote |
| `git config user.email` | `alias` de quem assina (`arthur.macedo@empresa.com` → `arthur.macedo`) |
| branch e commit atuais | carimbo de todo evento — o relatório amarra a conversa ao código |
| `git diff` entre dois commits | `publish_diff` publica na task os arquivos que mudaram e o patch |
| `clientInfo` do MCP | qual IA escreveu (claude / codex / cursor) |

Duas peças:

- **servidor** (`run.py`) — FastAPI + SQLite, contrato REST inteiro em `/docs`. **Um por time**, numa máquina só.
- **bridge** (`sync-agents-mcp`) — processo MCP local na máquina de cada pessoa, rodado por `uvx` (sem clone, sem instalação). Herda o cwd do chat, lê o `.git` e fala HTTP com o servidor. É o que garante o escopo: o modelo não escolhe projeto porque nenhuma tool aceita projeto.

O bridge depende só de `mcp`; FastAPI, uvicorn e psutil ficam no grupo `server` do `pyproject.toml`, então quem instala o bridge não baixa o servidor junto.

## Identidade e acesso

- **Pessoa, não perfil.** Só existe `people` (email + alias). IA não é um cadastro — é o campo `agent` do evento. Quem assina é sempre uma pessoa real.
- **Token por pessoa.** Cada uma tem o seu, emitido em `POST /people` pelo `ADMIN_TOKEN`. O token de administração só emite e lista pessoa; não abre projeto nenhum.
- **Membership por projeto.** `GET /projetos` devolve só onde você é membro; projeto onde você não é membro responde 404, não 403.
- **`visibility`**: `team` (padrão) deixa quem tem o repositório entrar sozinho — a prova de acesso é ter o clone. `private` só entra por convite de um owner.

## Como rodar

Dependências declaradas em `pyproject.toml` (`uv.lock` fixa as versões); `uv run` resolve e baixa em cache na primeira execução. Nada global, nenhum venv pra manter.

`HOST`, `PORT` e `ADMIN_TOKEN` vêm do `.env` (veja `.env.example`) — os dois primeiros têm default (`127.0.0.1`/`8787`), `ADMIN_TOKEN` é obrigatório: o servidor não sobe sem ele.

Só nesta máquina (padrão, seguro):

```bash
pwsh -File <caminho-do-projeto>\run.ps1
```

Exposto na rede, pro outro lado alcançar:

```bash
pwsh -File <caminho-do-projeto>\run.ps1 -Bind 0.0.0.0 -Porta 8787
```

`/docs` navega o contrato REST inteiro. `GET /health` devolve a versão atual; `GET /changelog` devolve o [`CHANGELOG.md`](CHANGELOG.md) — toda mudança de contrato bumpa versão e ganha entrada lá.

### Emitir o token de uma pessoa

```bash
curl -X POST http://<host>:8787/people \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"email":"arthur.macedo@empresa.com","name":"Arthur"}'
```

O token em texto puro só aparece nessa resposta. Chamar de novo com o mesmo email emite outro e invalida o anterior.

### Segurança — pendente, e é de quem administra o servidor

1. **Regra de firewall de entrada** na porta 8787 — configuração de sistema, não foi feita.
2. **Escopo de acesso**: `0.0.0.0` abre pra qualquer um na rede local. Restringir ao IP do outro lado é o recomendado.
3. **Token por canal privado**: `.env` nunca vai pra commit (já está no `.gitignore`), e token pessoal também não.
4. **`team` confia em quem tem o repositório.** Quem tem um token válido e o sha do commit raiz de um projeto `team` entra nele sozinho. Isso é deliberado — quem tem o clone já tem o código. Assunto que não pode ser assim mora em projeto `private`.

## Estado atual

`src/` dividido por domínio (`src/modules/{people,projects,tasks,events}`, cada um em 3 camadas — `repositorio.py`/`service.py`/`routes.py`), mais `src/shared/` (db, auth, config, enums, erros) e `src/bridge/` (MCP local: contexto git, cliente HTTP, tools).

Todo evento sai no mesmo envelope (`{seq, kind, created_at, project, task, actor, git, payload, resumo}`) na API, no relatório e no tempo real — é o que permite montar tela ou auditoria sem conhecer o interno do banco.

Verificação é manual (sem suíte automatizada por ora): `uv run ruff check src run.py` mais um smoke test ponta a ponta contra banco temporário (`SYNC_AGENTS_DB` aponta o banco pra outro arquivo) antes de qualquer mudança de schema tocar o `sync.db` real.

Não feito: regra de firewall/escopo de acesso (item de infra, ver acima); suíte de teste automatizada.
