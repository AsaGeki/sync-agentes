# Changelog

Formato livre, mais recente no topo. Versao segue `app/main.py` (`FastAPI(version=...)`), exposta em `GET /health` e este arquivo em `GET /changelog`.

## 1.2.0 — 2026-09-04

- `GET /changelog` devolve este arquivo (`CHANGELOG.md`) como texto puro.

## 1.1.0 — 2026-09-04

- `GET /health` devolve `versao` (contrato/versao da API).
- Migracao de schema real: coluna nova numa tabela existente agora e aplicada em banco ja criado, nao so em banco novo. Ver `app/db.py` (`MIGRACOES`, `schema_migrations`).

## 1.0.0 — 2026-09-04

Primeira versao. Sem mudanca de contrato depois deste ponto ate a 1.1.0, mas duas limpezas de repositorio aconteceram no meio do caminho:

- Corrigido autor do commit inicial (foi feito com a conta errada) e branch renomeada de `master` pra `main`.
- Removidas referencias a projeto e pessoas especificas de `README.md`, `CONECTAR.md`, `PROTOCOLO.md` e exemplos do Bruno — projeto ficou generico, serve pra qualquer time.
- Removido segredo exposto: `CONECTAR.md` e `Bruno/environments/Local.bru` tinham host e token reais em texto puro, ja tinham ido pro commit — trocados por placeholder.

Contrato entregue nesta versao:

- `autores` — cadastro (nao enum) de IA/humano, com `responsavel_id` obrigatorio pra IA e nulo pra humano.
- `projetos` — raiz de tudo, endereçado por `slug`.
- `tasks` — pendura em projeto, `codigo` unico por projeto (`T-001`), `etiquetas` livres, `dono_id` aponta pra `autores`.
- `dependencias` — tabela propria (`bloqueia` e a query reversa de `depende`, nao um segundo campo).
- `corpos` — texto de referencia da task, versionado; cada `PUT .../corpo` devolve o diff unificado contra a versao anterior.
- `eventos` — trilha unica (`task_criada`/`mensagem`/`campo`/`corpo`/`dependencia`), cursor global via `seq`. Alimenta `GET /mudancas`, o relatorio e o frame do WebSocket/SSE.
- Relatorio (`GET /projetos/{slug}/relatorio`) — resumo geral, agrupado por task, autoria, diff, perguntas sem resposta.
- Mesmo contrato exposto como servidor MCP em `/mcp/` (`app/mcp_server.py`), sem logica de negocio duplicada — cada tool chama a mesma funcao de `service.py` que a rota REST usa.
- Tempo real: `WS /ws` e `GET /stream` (SSE, fallback do WS), com `autor_id` filtrando o proprio eco.
- Autenticacao: `Authorization: Bearer <token>` em toda chamada, `X-Autor-Id: <id>` em toda escrita.
