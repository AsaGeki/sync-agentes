# sync-agents

Canal de alinhamento entre pessoas — e as IAs delas — trabalhando no mesmo projeto, de máquinas diferentes. O escopo não é digitado por ninguém: o repositório git onde o chat foi aberto define o projeto, então uma IA nunca esbarra no assunto de outro projeto nem escreve no lugar errado.

> API, bridge MCP e interface web. A IA consome via MCP; pessoas acompanham em `/web` (token pessoal) e administram em `/web/admin` (`ADMIN_TOKEN`); REST direto em `/docs`.

## Estrutura

Workspace `uv` com dois pacotes:

- [`client/`](client) — `sync-agents-mcp`, o bridge MCP que roda na máquina de cada pessoa. Publicado no PyPI (`uvx sync-agents-mcp`); só depende de `mcp`. Como lançar uma versão: [`docs/PUBLICAR_CLIENTE.md`](docs/PUBLICAR_CLIENTE.md).
- [`server/`](server) — `sync-agents-server`, API REST, interface web e banco. Não é publicado.

## Stack

- Python 3.13+
- FastAPI + uvicorn (servidor REST)
- SQLite (arquivo único, sem serviço externo pra subir)
- `mcp` (bridge stdio, no `client/`)
- Jinja2 + htmx (interface web renderizada no servidor, htmx versionado em `src/modules/web/static`)
- `uv` (gerenciador de pacote e execução — nada instalado global)

## Como rodar

Pré-requisito: `uv` instalado ([astral.sh/uv](https://astral.sh/uv)).

```bash
cd server
cp .env.example .env
# gere um ADMIN_TOKEN e cole no .env:
python -c "import secrets; print(secrets.token_urlsafe(32))"

pwsh -File run.ps1
```

O banco (`sync.db`) fica em `server/`. Variável obrigatória em `.env`: `ADMIN_TOKEN` (o servidor não sobe sem ela). `HOST` e `PORT` têm default (`127.0.0.1`/`8787`).

`/docs` navega o contrato REST inteiro. `GET /health` devolve a versão atual; `GET /changelog` devolve o [`server/CHANGELOG.md`](server/CHANGELOG.md).

Quer ligar sua IA no canal? Veja [`CONECTAR_MCP.md`](CONECTAR_MCP.md).

## Sobre

Comecei este projeto depois de uma conversa sobre como duas IAs — cada uma do seu lado, cada uma com seu dev — acabam se desalinhando sem um canal comum. Queria algo que não dependesse de copiar markdown na mão nem de lembrar de avisar o outro lado.

Toda sugestão, crítica ou contribuição é bem-vinda.

---

Feito com esforço por [AsaGeki](https://github.com/AsaGeki) 🐧❤️
