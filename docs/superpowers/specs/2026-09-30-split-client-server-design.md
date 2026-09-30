# Separar cliente MCP e servidor em dois pacotes

## Objetivo

Hoje quem conecta a IA ao sync-agents roda `uvx --from git+https://github.com/AsaGeki/sync-agentes sync-agents-mcp`. O `uv` clona o repositório inteiro, monta um wheel de `src/` (servidor, web, migrações, htmx) e só então instala `mcp`. A primeira conexão costuma estourar timeout, o cliente recebe código que não usa, e sem tag na URL todo mundo segue o HEAD da `main`.

Depois desta mudança:

- o cliente MCP é um pacote próprio, `sync-agents-mcp`, publicado no PyPI, sem nenhum código do servidor;
- o comando de instalação vira `uvx sync-agents-mcp` (versão fixável com `uvx sync-agents-mcp==X.Y.Z`);
- cliente e servidor continuam no mesmo repositório, como dois pacotes de um workspace `uv`.

Sucesso: instalar o cliente não traz o servidor, uma versão nova só chega a quem atualiza de propósito, e o servidor sobe e responde como antes.

## Decisões

- **Distribuição:** PyPI. O repositório é público e o nome `sync-agents-mcp` estava livre na consulta de 2026-09-30.
- **Layout simétrico:** `client/` e `server/` na raiz, ambos membros de um workspace `uv`.
- **Enums:** os 4 enums que o cliente usa moram no cliente; o servidor os reexporta. Fonte única no repositório.
- **Sem publicação automática pela IA:** o workflow existe, mas a tag e o upload são de quem mantém o projeto.
- **Sem shim de compatibilidade** para o comando antigo com `git+https`.

## 1. Estrutura

```
/                        raiz do workspace uv (pyproject virtual, uv.lock, .venv)
├─ client/               pacote publicado: sync-agents-mcp
│  ├─ pyproject.toml
│  ├─ README.md
│  └─ src/sync_agents_mcp/{__init__,server,api,git_context,enums}.py
├─ server/               FastAPI, não publicado
│  ├─ pyproject.toml
│  ├─ src/  scripts/  run.py  run.ps1  .env.example  CHANGELOG.md
│  └─ sync.db*           (ignorado pelo git)
├─ .github/workflows/publicar-cliente.yml
├─ Bruno/  docs/  CONECTAR_MCP.md  README.md
```

`src/bridge/*` vira `client/src/sync_agents_mcp/*` e os imports `src.bridge.x` viram `sync_agents_mcp.x`. Isso também elimina o pacote top-level `src` que o wheel do cliente instalava.

`Bruno/`, `docs/`, `CONECTAR_MCP.md`, `README.md` e `MODELO_INDICADORES.md` ficam na raiz: documentam o repositório todo, não só um pacote.

## 2. Cliente (`sync-agents-mcp`)

- Depende só de `mcp>=2.1.1`. Versão própria, independente da versão do servidor, começando em `0.1.0`.
- Build com `hatchling`, `packages = ["src/sync_agents_mcp"]`, entry point `sync-agents-mcp = "sync_agents_mcp.server:main"`.
- Ganha `enums.py` com `EStatusProject`, `EStatusTask`, `ETypeMessage` e `EVisibility`, movidos sem alteração de `src/shared/enums.py`.
- Ganha `README.md` curto, que é a página do PyPI: o que é, como rodar, variáveis de ambiente, link para `CONECTAR_MCP.md`.

## 3. Servidor (`sync-agents-server`)

- `src/` → `server/src/`; `scripts/`, `run.py`, `run.ps1`, `.env.example` e `CHANGELOG.md` vão junto.
- Continua sendo um pacote (`hatchling`, `packages = ["src"]`), porque os scripts de migração fazem `from src...` e dependem de `src` estar instalado.
- As dependências do antigo grupo `server` passam para `[project].dependencies`, mais `sync-agents-mcp` com `[tool.uv.sources] sync-agents-mcp = { workspace = true }`.
- `server/src/shared/enums.py` mantém `EAgent`, `ERole`, `ERequestStatus` e `EKindEvent` e reexporta os 4 movidos com `from sync_agents_mcp.enums import ...`. Nenhum outro arquivo do servidor muda de import.
- `BASE_DIR` (`src/shared/db.py`, três `parent` acima do arquivo) passa a resolver para `server/` sem alteração de código. `sync.db`, `sync.db.bak-*` e `CHANGELOG.md` (lido por `GET /changelog`) são procurados ali. O `.env` continua sendo achado porque `load_dotenv()` sobe a árvore de pastas.
- `FastAPI(version=...)` sobe para `3.3.0` e o CHANGELOG do servidor ganha a entrada correspondente.

## 4. Workspace

O `pyproject.toml` da raiz não tem `[project]`: declara `[tool.uv.workspace] members = ["client", "server"]`, o grupo `dev` (ruff) e a configuração do ruff, com `src = ["server", "client/src"]` para o isort classificar `src` e `sync_agents_mcp` como first-party. Um único `uv.lock` na raiz.

`uv run run.py` executado dentro de `server/` continua funcionando, porque o `uv` resolve o membro do workspace pela pasta atual.

## 5. Publicação

`.github/workflows/publicar-cliente.yml`, disparado por tag `client-v*`:

1. confere que a tag bate com a versão do `client/pyproject.toml`;
2. `uv build --package sync-agents-mcp`;
3. publica com `pypa/gh-action-pypi-publish` via Trusted Publishing (job com `environment: pypi` e `id-token: write`, sem token guardado).

Passo manual, uma vez, feito por quem mantém o PyPI: cadastrar um *pending publisher* para `sync-agents-mcp` (owner `AsaGeki`, repositório `sync-agentes`, workflow `publicar-cliente.yml`, environment `pypi`). O passo a passo fica em `docs/PUBLICAR_CLIENTE.md`, fora da página do PyPI.

Para lançar uma versão: subir a versão em `client/pyproject.toml`, commitar, criar a tag `client-vX.Y.Z` e dar push da tag.

## 6. Documentação

- `CONECTAR_MCP.md`: todo `uvx --from git+... sync-agents-mcp` vira `uvx sync-agents-mcp`; o `pip install` aponta o pacote do PyPI; a nota da primeira conexão lenta passa a falar do download a frio do pacote; seção nova para quem já registrou o comando antigo (remover e registrar de novo) e como atualizar (`uvx sync-agents-mcp@latest`) ou fixar versão.
- `README.md`: estrutura de pastas e como rodar o servidor a partir de `server/`.
- `.gitignore`: `dist/`.

## 7. Migração

Servidor (feita por quem opera, com o servidor parado):

1. mover `sync.db*` e `.env` da raiz para `server/`. Sem mover o `sync.db`, o servidor cria um banco vazio em `server/`;
2. subir de novo com `pwsh -File server/run.ps1`.

Clientes: quem registrou o comando `git+https` continua funcionando enquanto o cache do `uv` durar. Depois disso quebra, porque a raiz do repositório deixa de expor o script `sync-agents-mcp`. Cada pessoa registra o MCP de novo, uma vez, com o comando novo. O comando novo só funciona depois da primeira publicação no PyPI.

## Fora de escopo

- Testes automatizados.
- Pacote separado só para o contrato (enums/schemas).
- Publicar o servidor.
- Acoplar a versão do cliente à do servidor.
- Shim de compatibilidade para o comando antigo.
