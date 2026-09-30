# Changelog

Formato livre, mais recente no topo. Versão segue `src/main.py` (`FastAPI(version=...)`), exposta em `GET /health` e este arquivo em `GET /changelog`.

## 3.3.0 — 2026-09-30

Sem mudança de API, de contrato REST nem de tools MCP.

- **Cliente MCP separado do servidor e publicado no PyPI (`sync-agents-mcp`).** O repositório virou um workspace `uv` com `client/` (o bridge, só depende de `mcp`) e `server/` (API, web, banco). O comando de instalação passou de `uvx --from git+https://github.com/AsaGeki/sync-agentes sync-agents-mcp` pra `uvx sync-agents-mcp`, sem clonar o repositório nem baixar código do servidor. Quem já tinha registrado o comando antigo refaz uma vez (`CONECTAR_MCP.md`). O cliente tem versão própria (`client/pyproject.toml`) e é lançado por tag `client-v*` (`docs/PUBLICAR_CLIENTE.md`).
- **Servidor mudou de pasta.** `src/`, `scripts/`, `run.py`, `run.ps1`, `.env.example` e este arquivo moraram na raiz; agora estão em `server/`. O `sync.db` (e os `sync.db.bak-*`) passam a ser procurados em `server/`: quem opera o servidor move os arquivos e o `.env` pra lá antes de subir, senão um banco vazio é criado. `pwsh -File server/run.ps1` sobe como antes.
- Os enums que o cliente usa (`EStatusProject`, `EStatusTask`, `ETypeMessage`, `EVisibility`) passaram a morar em `sync_agents_mcp.enums`; `src/shared/enums.py` os reexporta, então o resto do servidor não mudou.
- O grupo de dependências `server` sumiu: as dependências do servidor estão em `server/pyproject.toml`.

## 3.2.0 — 2026-09-29

- **Interface web em `/web`** (Jinja2 + htmx, renderizada no servidor, sem build de JS). `/` redireciona pra lá. REST, MCP e `/docs` não mudaram.
- **Login por token colado.** `/web/login` recebe o token pessoal e grava o cookie `sa_pessoa`; `/web/admin/login` recebe o `ADMIN_TOKEN` e grava `sa_admin`. Os dois são `httpOnly` + `SameSite=Strict` e independentes. Em HTTP puro o cookie trafega em claro, mesmo risco do header `Authorization` do bridge.
- **Área da pessoa:** cards dos projetos de que ela é membro (progresso, tasks bloqueadas/aguardando decisão, perguntas abertas, não lidos); painel do projeto (tasks por status, progresso por feature, o que precisa de atenção, membros, gráfico de eventos por dia nas últimas 8 semanas por pessoa ou por ferramenta); lista de tasks com filtros; task com corpo, linha do tempo, diffs e diff do corpo por versão.
- **Escrita pela web:** mensagem na task e edição de status, dono, feature e tags. Assina a pessoa do cookie com `agent='human'`.
- **A web não marca nada como lido.** O não lido existe pra IA saber o que ainda não viu: a tela mostra os contadores ("não lidos pela sua IA") mas abrir a task por ela não mexe neles. Só `read_task` (MCP/REST) marca.
- **Tempo real na web:** `GET /web/stream` (SSE autenticado pelo cookie, um canal por pessoa com todos os projetos dela) avisa a página, que rebusca o trecho afetado. As abas dividem uma conexão só via `SharedWorker`: o navegador limita 6 conexões HTTP/1.1 por host, e uma conexão por aba travava quem abria várias. Diferente do `/stream`, não corta o próprio eco: a IA da pessoa escreve assinando como ela e isso precisa aparecer na tela.
- **Mudança de regra: admin lê conteúdo de projeto (só pela web).** `/web/admin/p/{slug}` mostra painel, tasks e task de qualquer projeto em modo leitura, sem contar nem marcar lido. Admin também adiciona membro e aceita/recusa pedido de acesso de qualquer projeto sem ser owner, além de gerenciar people/tokens e apagar projeto. Nenhuma rota REST nova.
- Services ganharam núcleos sem checagem de acesso, reusados pela leitura de admin: `tasks.service.filtrar_tasks`, `tasks.service.montar_task`, `projects.service.admin_add_member`, `projects.service.admin_resolver_request`. `relatorio.perguntas_abertas` saiu de `montar_relatorio` pra ser reusada pelo painel. `task_diff` aceita `ate` (diff entre duas versões do corpo).
- Corpo e mensagens aparecem renderizados como markdown (`markdown-it-py`, CommonMark + tabela + tachado). HTML cru no texto é escapado.
- No gráfico por pessoa, cada pessoa tem cor própria (até 8, a paleta inteira), fixa pela ordem em que escreveu pela primeira vez no projeto. Só a partir da 9ª pessoa vira "outros".
- Layout da web: barra lateral fixa com os projetos (e não lidos de cada um) e as seções do projeto aberto, área de trabalho em largura total e navegação por `hx-boost`.
- Task em duas colunas: corpo recolhível, conversa e campo de resposta à esquerda; propriedades editáveis, dependências, participantes e diffs à direita. Na conversa, mensagens seguidas do mesmo autor (janela de 10 min) viram um cartão só com avatar, ferramenta e tipo colorido; pergunta sem resposta fica marcada; mudanças de campo e de corpo aparecem como linhas compactas com separador por dia; texto longo fica recolhido com "mostrar tudo". O tipo da mensagem é escolhido em botões e `Ctrl+Enter` envia.
- Tasks ganharam visão em quadro por status; a lista mostra o code curto (`T-023`), o dono com avatar e a hora relativa.
- Painel em grade: atenção e gráfico na coluna principal; status (barra empilhada), features e membros na lateral.
- Links dentro de trechos que se atualizam sozinhos (lista, quadro, painel, conversa) não herdam mais `hx-select`/`hx-swap` do trecho: antes, abrir uma task por eles deixava a tela vazia.
- Dependências novas no grupo `server`: `jinja2`, `python-multipart` e `markdown-it-py`.

## 3.1.0 — 2026-09-29

- **Feature: agrupador opcional de tasks (`projeto → feature → task`).** Tabela `features` com code `F-003-slug` (mesma regra do code de task), título e descrição. `tasks.feature_id` é opcional - task avulsa continua sendo o caso normal, e nada trava por causa de feature. O status da feature não é gravado: sai das tasks dela (sem task ou tudo `ideia` → `ideia`; tudo `feito` → `feito`; alguma `bloqueado` → `bloqueado`; senão `parcial`), junto com o progresso `feito/total`.
- **REST:** `POST/GET /projetos/{slug}/features`, `GET/PATCH/DELETE /projetos/{slug}/features/{code}`. Apagar feature deixa as tasks dela avulsas. `GET .../tasks` ganhou `feature=<code>` e `sem_feature=true`; `POST`/`PATCH` de task aceitam `feature` (`""` no PATCH tira a task da feature).
- **MCP:** tools novas `create_feature`, `list_features`, `update_feature`; `feature` em `create_task`/`update_task`/`list_tasks`. Exclusão de feature fica só no REST.
- **Eventos:** kinds novos `feature.created`, `feature.field_changed`, `feature.deleted`; coluna `events.feature_id`. O envelope ganhou `feature` (code da feature do evento, ou da feature atual da task). Mover task de feature é `task.field_changed` com `campo='feature'`. Migração recria `events` preservando todo evento e o `seq`.
- **`X-Operation-Id` vale também em `DELETE`.** Repetir um DELETE com o mesmo id devolve a resposta gravada em vez de 404.
- **Valor de campo longo não quebra mais o `resumo`** nem o relatório: `valor_de`/`valor_para` aparecem pela primeira linha, cortada em 80 caracteres.
- **Relatório:** markdown agrupa as tasks por feature (grupo "Sem feature" no fim) e lista status/progresso de cada feature no resumo geral; JSON ganhou `features`, `por_feature` e `features_apagadas`.

## 3.0.0 — 2026-09-09

Reescrita do modelo de identidade e de escopo. Migração real roda no próximo start e preserva todo o dado (`src/shared/migracao_v3.py`).

- **O repositório git passou a ser o escopo (breaking).** `projects` é endereçado pelo sha do commit raiz do repo (`project_repos`), não mais por um `slug` que alguém digita. `POST /repos/resolve` troca um repositório pelo projeto dele: repo desconhecido cria o projeto, repo conhecido devolve o projeto e entra como membro. Um projeto aceita mais de um repositório (`POST /projetos/{slug}/repos`) - frontend e backend no mesmo canal. `projects.git_repositories` (lista de nome de repo em texto) foi removido; o vínculo real nasce na primeira conexão a partir do repo.
- **`authors` virou `people` (breaking).** Autor do tipo `ia` não existe mais como entidade: quem assina é sempre uma pessoa, e a ferramenta que escreveu virou o campo `events.agent` (`claude`/`codex`/`cursor`/`copilot`/`human`/`outro`). Some `type`, `responsible_id`, o enum `ETypeAuthor` e o cadastro em 2 passos. Pessoa tem `email` (chave) e `alias` (parte antes do `@`, é como a assinatura aparece). Na migração, os eventos assinados por uma IA passam pro dev responsável dela com `agent='outro'`; a pessoa nasce com email placeholder `<nome>@local.invalid` e sem token, até o administrador emitir um.
- **Token deixou de ser compartilhado (breaking).** `TOKEN` no `.env` virou `ADMIN_TOKEN` e agora só emite e lista pessoa - não abre projeto nenhum. Cada pessoa tem o próprio token (`POST /people`, devolve em texto puro uma vez só; o banco guarda o hash). `X-Autor-Id` não existe mais: quem assina é o dono do token, então não dá pra escrever assinando como outra pessoa.
- **Acesso por projeto (`memberships`).** `GET /projetos` devolve só os projetos em que você é membro, e projeto onde você não é membro responde 404, não 403 - quem não é membro não descobre que ele existe. `visibility='team'` (padrão) deixa quem tem o repositório entrar sozinho; `visibility='private'` só entra por convite de um owner (`POST /projetos/{slug}/membros`). Só owner muda `visibility`.
- **Tipo de evento virou `<entidade>.<fato>` e o evento ganhou envelope fixo (breaking).** `kind` passou de `task_criada`/`mensagem`/`campo`/`corpo` pra `task.created`/`message.created`/`task.field_changed`/`body.updated`, mais o novo `diff.published`; a migração converte o histórico. Todo evento sai no mesmo formato em `/mudancas`, no relatório, na leitura de task e no tempo real: `{seq, kind, created_at, project, task, actor:{person,name,agent}, git:{branch,commit}, payload, resumo}`. `payload` carrega só o que é daquele `kind`, e o que é volumoso (corpo inteiro, patch) só vai na leitura de 1 task, não na listagem.
- **Diff de código publicado numa task (`POST /projetos/{slug}/tasks/{code}/diffs`).** Registra quais arquivos mudaram entre `base_sha` e o commit de quem publica, com o patch junto (teto de 100 KB, marca `truncado`). `pedir_revisao` registra também uma pergunta na task - o diff entra nas perguntas em aberto do relatório em vez de exigir uma máquina de estado de review. `GET .../diffs` lista os diffs de uma task sem o patch. Colunas novas em `events`: `base_sha` e `arquivos`. A tool `publish_diff` do bridge calcula tudo do git local: base padrão é o head do último diff da task e, na falta dele, o ponto onde a branch atual saiu da principal.
- **Evento carimba de onde saiu.** `agent`, `branch` e `commit_sha` em todo evento; o relatório markdown ganhou a linha `git:` por task, com as branches tocadas e o intervalo de commit.
- **Bridge MCP local (`sync-agents-mcp`).** O servidor MCP HTTP em `/mcp/` foi removido; no lugar entrou um processo MCP stdio que roda na máquina de quem conecta, herda o cwd do chat e lê o `.git` sozinho. Nenhuma tool recebe nome de projeto, e fora de um repositório git nada é escrito. Toda resposta de tool traz `novidades` com o que o outro lado escreveu desde a última chamada. Tools renomeadas: `create_task_message`→`send_message`, `update_task_corpo`→`update_body`, `read_task_diff`→`read_diff`, `read_project_mudancas`→`read_changes`, `read_project_relatorio`→`read_report`; `create_author`/`list_authors`/`create_project`/`list_projects` saíram, entraram `status`, `list_members`, `add_member`, `link_repo`.
- **`GET /projetos/{slug}/mudancas` ganhou `de_outros`** (corta o próprio eco) e passou a devolver `resumo` pronto em cada evento - a mesma linha que o WebSocket manda, pra cliente não ter que reprocessar o evento.
- **WebSocket/SSE**: autenticam por token pessoal (header `Authorization` ou `?token=`), exigem membership e mandam frame JSON estruturado no lugar de texto solto. O filtro de eco estava quebrado desde a 2.0.0 (comparava `autor_id`, campo renomeado pra `author_id`) - corrigido.
- **`update_body` aceita `versao_base` (opcional).** Informando a versão sobre a qual o texto foi escrito, o servidor recusa com 409 se o outro lado gravou nesse meio tempo, em vez de apagar o texto dele em silêncio. A escrita do corpo passou a abrir a transação com `BEGIN IMMEDIATE`, então dois lados gravando ao mesmo tempo não disputam a mesma versão.
- **Código de task deixou de sair da contagem de tasks.** Vem do maior código já usado, e criação simultânea tenta o seguinte em vez de devolver 409 - antes, dois lados criando ao mesmo tempo faziam um deles falhar.
- **`GET /people` passou a exigir o `ADMIN_TOKEN`.** A lista com o email de todo mundo não é conteúdo de canal; quem quer saber quem está num projeto usa `GET /projetos/{slug}/membros`.
- **`GET .../tasks/{code}/diff` virou `GET .../tasks/{code}/corpo/diff`, e a tool `read_diff` virou `read_body_diff`** - o nome antigo se confundia com o diff de código (`publish_diff`/`list_diffs`), que é outra coisa.
- **`agent` aceita só `claude`, `codex`, `human` e `outro`.** `cursor` e `copilot` saíram: nunca foram observados se identificando, e valor de enum sem uso é chute documentado como fato.
- **`SYNC_AGENTS_REPO` (ou `--repo <caminho>`) aponta o repositório na mão**, pra cliente MCP que não abre pasta de projeto (Claude Desktop). Sem isso, o bridge usa o cwd da sessão, que é o caso de Claude Code, Cursor e VS Code.
- **Dependência do bridge separada da do servidor.** `[project.dependencies]` ficou só com `mcp`; FastAPI/uvicorn/psutil/websockets/python-dotenv foram pro dependency-group `server` (instalado por padrão aqui no repo via `[tool.uv] default-groups`). Quem registra o MCP roda `uvx --from git+<repo> sync-agents-mcp` e não baixa o servidor junto - não precisa clonar nada.
- **`SYNC_AGENTS_DB`** aponta o banco pra outro arquivo, pra rodar smoke test sem encostar no `sync.db` real.

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
