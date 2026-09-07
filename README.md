# sync-agents

API local de sincronização entre agentes — IAs e humanos — trabalhando no mesmo projeto a partir de máquinas diferentes.

Serve pra qualquer projeto: `projetos` é a raiz, `tasks` pendura em projeto, toda escrita fica registrada numa trilha única de eventos.

Quer conectar sua IA a um projeto? Veja [CONECTAR_MCP.md](CONECTAR_MCP.md) — modelo de dados, bootstrap de identidade, registro do MCP, tempo real.

## Como rodar

Dependências: **FastAPI + uvicorn + python-dotenv, declaradas em `pyproject.toml`** (`uv.lock` fixa as versões) — nada instalado global, nada de venv pra manter. O `uv` resolve e baixa em cache na primeira execução (`uv run`).

Host, porta e token vêm do `.env` (veja `.env.example`) — `HOST` e `PORT` têm default (`127.0.0.1`/`8787`), `TOKEN` é obrigatório: o servidor não sobe sem ele (`RuntimeError` no start).

Só nesta máquina (padrão, seguro):

```bash
pwsh -File <caminho-do-projeto>\run.ps1
```

Exposto na rede, pro outro lado alcançar:

```bash
pwsh -File <caminho-do-projeto>\run.ps1 -Bind 0.0.0.0 -Porta 8787
```

`/docs` (Swagger) navega o contrato REST inteiro. `GET /health` devolve a versão atual; `GET /changelog` devolve o [`CHANGELOG.md`](CHANGELOG.md) — toda mudança de contrato bumpa versão e ganha entrada lá.

### Segurança — pendente, e é de quem administra o servidor

1. **Regra de firewall de entrada** na porta 8787 — configuração de sistema, não foi feita.
2. **Escopo de acesso**: `0.0.0.0` abre pra qualquer um na rede local. Restringir ao IP do outro lado é o recomendado.
3. **Token por canal privado**: `.env` nunca vai pra commit (já está no `.gitignore`).
4. **Identidade não é autenticada por autor** — token é compartilhado, autor vem no header `X-Autor-Id`. Quem tem o token pode escrever assinando como qualquer autor. Aceitável em rede interna; token-por-autor é o caminho se um dia precisar de garantia.

## Estado atual

`src/` dividido por domínio (`src/modules/{autores,projetos,tasks,eventos}`, cada um em 3 camadas — `repositorio.py`/`service.py`/`routes.py`) mais `src/shared/` (db, auth, config, enums, erros de domínio) e `src/mcp_server.py` expondo o mesmo contrato como tools MCP em `/mcp/`, sem lógica duplicada entre REST e MCP. Verificação é manual (sem suíte de teste automatizada por ora) — `uv run ruff check src run.py` + smoke test ponta a ponta contra banco temporário antes de qualquer mudança de schema tocar o `sync.db` real.

Não feito: regra de firewall/escopo de acesso (item de infra, ver acima); suíte de teste automatizada.
