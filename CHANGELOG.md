# Changelog

Formato livre, mais recente no topo. Versao segue `src/main.py` (`FastAPI(version=...)`), exposta em `GET /health` e este arquivo em `GET /changelog`.

## 2.0.0 — 2026-09-07

- **Modelagem de dados renomeada pro ingles (breaking).** Toda coluna/tabela estrutural virou ingles - `autores`→`authors` (`tipo`→`type`, `nome`→`name`, `responsavel_id`→`responsible_id`, `criado_em`→`created_at`), `projetos`→`projects` (`nome`→`name`, `descricao`→`description`, `criado_em`/`atualizado_em`→`created_at`/`updated_at`), `tasks` (`projeto_id`→`project_id`, `codigo`→`code`, `titulo`→`title`, `etiquetas`→`tags`, `dono_id`→`owner_id`), `eventos`→`events` (`projeto_id`→`project_id`, `autor_id`→`author_id`, `tipo`→`type`, `versao`→`version`). Campo de conteudo livre continua portugues (`texto`, `campo`, `valor_de`, `valor_para`, `corpo`, `diff`, `versao_corpo`, `versao_de`, `versao_para`). Migracao real ja rodou no proximo start (`src/shared/db.py`) - renomeia tabela/coluna preservando dado, nao apaga nada.
- **`corpos` deixou de ser tabela propria - fundida em `eventos`/`events` (breaking).** Evento `kind='corpo'` agora carrega o texto direto (`events.texto`); `GET tasks/{code}` e o diff leem de la. Migracao copia o texto de `corpos` pro evento correspondente antes de derrubar a tabela.
- **`dependencias` removida (breaking).** Tabela, rota `POST tasks/{codigo}/dependencias`, tool MCP `task_dependencia_criar`, campos `depende`/`bloqueia` na task e a secao de relatorio correspondente - tudo cortado. Evento historico `kind='dependencia'` e apagado na migracao (feature removida, nao so escondida).
- **`projetos`/`projects` ganhou `git_repositories`** (array json, `nome exato do repo`, mesmo padrao de `etiquetas`/`tags`) **e `created_by`** (autor de quem criou o projeto). `POST /projetos` passa a exigir `X-Autor-Id` (antes nao exigia).
- Filtro de task por etiqueta mudou de `?etiqueta=` pra `?tag=`, acompanhando o rename de `etiquetas` pra `tags`.
- `timeout_graceful_shutdown=5` no uvicorn (`run.py`) - sessao MCP Streamable HTTP mantinha conexao aberta e o shutdown gracioso esperava ela fechar pra sempre; agora tem teto.
- **Documentacao consolidada em 2 arquivos.** `docs/` (`ARQUITETURA.md`/`DECISOES.md`/`CONTRATO.md`), `PROTOCOLO.md` e `CONECTAR.md` foram removidos - nenhuma IA conectada lia esses `.md`. Ficou `README.md` (enxuto) e `CONECTAR_MCP.md` (novo - modelo de dados e como conectar). Regra de conduta do canal (tipo de mensagem, como versionar corpo) saiu de `.md` e foi pras `instructions` do proprio `src/mcp_server.py` - e o unico texto que todo cliente MCP mostra pra IA sozinho ao conectar.

## 2.1.0 — 2026-09-07

- **`authors.type` usa `'dev'` no lugar de `'humano'` (breaking).** Migracao real reconstroi a tabela preservando dado (`'humano'` vira `'dev'`). Prosa geral do projeto ("canal entre IA e humanos") nao mudou - so o valor do campo.
- **Projeto renomeado pra `sync-agents`** (`pyproject.toml`, titulo do FastAPI/MCP, nome de registro `claude mcp add`, pasta local).

## 1.4.0 — 2026-09-04

- **Token deixou de ser auto-gerado (breaking).** Antes: servidor gerava um token na 1ª execução e gravava em `config.json`. Agora: `TOKEN` vem do `.env` (veja `.env.example`) — obrigatório, servidor não sobe sem ele.
- `config.json` não existe mais. Removido do `.gitignore` (nada mais escreve nesse arquivo).

## 1.3.0 — 2026-09-04

- **`GET /health` mudou de formato (breaking).** Antes: `{ok, agora, versao}`. Agora: `status`, `online`, `versao`, `agora`, `iniciadoEm`, `tempoLigadoSegundos`, `tempoLigadoTexto`, `bancoTipo`, `bancoVersao`, `bancoArquivo`, `bancoConectado`, `sistemaOperacional`, `ramUsadaMb`. Campos em **camelCase** — diferente do resto do contrato (snake_case), de propósito: é o início de uma migração de casing que vai revisar o resto do contrato rota a rota, ainda não feita.
- Nova dependência: `psutil` (mede RAM do processo pro `/health`).

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
