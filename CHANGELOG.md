# Changelog

Formato livre, mais recente no topo. Versão segue `src/main.py` (`FastAPI(version=...)`), exposta em `GET /health` e este arquivo em `GET /changelog`.

## 2.2.0 — 2026-09-07

- **`GET /projetos/{slug}/relatorio` (`formato=md`) virou resumo técnico de estado, não mais log de atividade.** Por task, mostra status/tags/dono atuais, campos que mudaram na janela e diff acumulado do corpo - sem narrar mensagens (mudanca/pergunta/resposta/decisao/bloqueio) nem autoria por evento. `formato=json` continua com os dados crus de sempre (eventos, autoria, perguntas em aberto) - só a renderização em texto mudou.

## 2.0.0 — 2026-09-07

- **Modelagem de dados renomeada pro inglês (breaking).** Toda coluna/tabela estrutural virou inglês - `autores`→`authors` (`tipo`→`type`, `nome`→`name`, `responsavel_id`→`responsible_id`, `criado_em`→`created_at`), `projetos`→`projects` (`nome`→`name`, `descricao`→`description`, `criado_em`/`atualizado_em`→`created_at`/`updated_at`), `tasks` (`projeto_id`→`project_id`, `codigo`→`code`, `titulo`→`title`, `etiquetas`→`tags`, `dono_id`→`owner_id`), `eventos`→`events` (`projeto_id`→`project_id`, `autor_id`→`author_id`, `tipo`→`type`, `versao`→`version`). Campo de conteúdo livre continua português (`texto`, `campo`, `valor_de`, `valor_para`, `corpo`, `diff`, `versao_corpo`, `versao_de`, `versao_para`). Migração real já rodou no próximo start (`src/shared/db.py`) - renomeia tabela/coluna preservando dado, não apaga nada.
- **`corpos` deixou de ser tabela própria - fundida em `eventos`/`events` (breaking).** Evento `kind='corpo'` agora carrega o texto direto (`events.texto`); `GET tasks/{code}` e o diff leem de lá. Migração copia o texto de `corpos` pro evento correspondente antes de derrubar a tabela.
- **`dependencias` removida (breaking).** Tabela, rota `POST tasks/{codigo}/dependencias`, tool MCP `task_dependencia_criar`, campos `depende`/`bloqueia` na task e a seção de relatório correspondente - tudo cortado. Evento histórico `kind='dependencia'` é apagado na migração (feature removida, não só escondida).
- **`projetos`/`projects` ganhou `git_repositories`** (array json, `nome exato do repo`, mesmo padrão de `etiquetas`/`tags`) **e `created_by`** (autor de quem criou o projeto). `POST /projetos` passa a exigir `X-Autor-Id` (antes não exigia).
- Filtro de task por etiqueta mudou de `?etiqueta=` pra `?tag=`, acompanhando o rename de `etiquetas` pra `tags`.
- `timeout_graceful_shutdown=5` no uvicorn (`run.py`) - sessão MCP Streamable HTTP mantinha conexão aberta e o shutdown gracioso esperava ela fechar pra sempre; agora tem teto.
- **Documentação consolidada em 2 arquivos.** `docs/` (`ARQUITETURA.md`/`DECISOES.md`/`CONTRATO.md`), `PROTOCOLO.md` e `CONECTAR.md` foram removidos - nenhuma IA conectada lia esses `.md`. Ficou `README.md` (enxuto) e `CONECTAR_MCP.md` (novo - modelo de dados e como conectar). Regra de conduta do canal (tipo de mensagem, como versionar corpo) saiu de `.md` e foi pras `instructions` do próprio `src/mcp_server.py` - é o único texto que todo cliente MCP mostra pra IA sozinho ao conectar.

## 2.1.0 — 2026-09-07

- **`authors.type` usa `'dev'` no lugar de `'humano'` (breaking).** Migração real reconstrói a tabela preservando dado (`'humano'` vira `'dev'`). Prosa geral do projeto ("canal entre IA e humanos") não mudou - só o valor do campo.
- **Projeto renomeado pra `sync-agents`** (`pyproject.toml`, título do FastAPI/MCP, nome de registro `claude mcp add`, pasta local).

## 1.4.0 — 2026-09-04

- **Token deixou de ser auto-gerado (breaking).** Antes: servidor gerava um token na 1ª execução e gravava em `config.json`. Agora: `TOKEN` vem do `.env` (veja `.env.example`) — obrigatório, servidor não sobe sem ele.
- `config.json` não existe mais. Removido do `.gitignore` (nada mais escreve nesse arquivo).

## 1.3.0 — 2026-09-04

- **`GET /health` mudou de formato (breaking).** Antes: `{ok, agora, versao}`. Agora: `status`, `online`, `versao`, `agora`, `iniciadoEm`, `tempoLigadoSegundos`, `tempoLigadoTexto`, `bancoTipo`, `bancoVersao`, `bancoArquivo`, `bancoConectado`, `sistemaOperacional`, `ramUsadaMb`. Campos em **camelCase** — diferente do resto do contrato (snake_case), de propósito: é o início de uma migração de casing que vai revisar o resto do contrato rota a rota, ainda não feita.
- Nova dependência: `psutil` (mede RAM do processo pro `/health`).

## 1.2.0 — 2026-09-04

- `GET /changelog` devolve este arquivo (`CHANGELOG.md`) como texto puro.

## 1.1.0 — 2026-09-04

- `GET /health` devolve `versao` (contrato/versão da API).
- Migração de schema real: coluna nova numa tabela existente agora é aplicada em banco já criado, não só em banco novo. Ver `app/db.py` (`MIGRACOES`, `schema_migrations`).

## 1.0.0 — 2026-09-04

Primeira versão. Sem mudança de contrato depois deste ponto até a 1.1.0, mas duas limpezas de repositório aconteceram no meio do caminho:

- Corrigido autor do commit inicial (foi feito com a conta errada) e branch renomeada de `master` pra `main`.
- Removidas referências a projeto e pessoas específicas de `README.md`, `CONECTAR.md`, `PROTOCOLO.md` e exemplos do Bruno — projeto ficou genérico, serve pra qualquer time.
- Removido segredo exposto: `CONECTAR.md` e `Bruno/environments/Local.bru` tinham host e token reais em texto puro, já tinham ido pro commit — trocados por placeholder.

Contrato entregue nesta versão:

- `autores` — cadastro (não enum) de IA/humano, com `responsavel_id` obrigatório pra IA e nulo pra humano.
- `projetos` — raiz de tudo, endereçado por `slug`.
- `tasks` — pendura em projeto, `codigo` único por projeto (`T-001`), `etiquetas` livres, `dono_id` aponta pra `autores`.
- `dependencias` — tabela própria (`bloqueia` é a query reversa de `depende`, não um segundo campo).
- `corpos` — texto de referência da task, versionado; cada `PUT .../corpo` devolve o diff unificado contra a versão anterior.
- `eventos` — trilha única (`task_criada`/`mensagem`/`campo`/`corpo`/`dependencia`), cursor global via `seq`. Alimenta `GET /mudancas`, o relatório e o frame do WebSocket/SSE.
- Relatório (`GET /projetos/{slug}/relatorio`) — resumo geral, agrupado por task, autoria, diff, perguntas sem resposta.
- Mesmo contrato exposto como servidor MCP em `/mcp/` (`app/mcp_server.py`), sem lógica de negócio duplicada — cada tool chama a mesma função de `service.py` que a rota REST usa.
- Tempo real: `WS /ws` e `GET /stream` (SSE, fallback do WS), com `autor_id` filtrando o próprio eco.
- Autenticação: `Authorization: Bearer <token>` em toda chamada, `X-Autor-Id: <id>` em toda escrita.
