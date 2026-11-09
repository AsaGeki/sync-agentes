# Revisão de regras e contratos do sync-agents

Data: 09/11/2026. Escopo: `server/src` (tasks, projects, people, events, auth, db, main) e `client/src/sync_agents_mcp` (bridge MCP).

**Como foi feito:** leitura do código e sondas descartáveis contra um SQLite temporário (nada tocou o `sync.db`). Cada achado diz se foi **confirmado em execução** ou só **lido no código**.

**Corrigidos em 09/11/2026:** M7 (visibilidade `public`/`private` e entrada explícita), A1, A2, A3, M1, M2 (recusa com 409), M3, M4, M5, M8, M9, M6 (`project=` só vale para projeto afiliado ao repositório; `request_access` é a exceção), M10, M12 (projeto `arquivado` só aceita leitura; `pausado` e `concluido` seguem informativos), M11 (parcial: `versao_corpo` sem carregar o texto e `nao_lidos` só hidrata as tasks que mostra; `list_tasks` segue sem paginação), M13 (tool `read_feature`; `delete_feature` fica só no REST). Os textos abaixo descrevem o problema como ele era.

## Alta

### A1. Bridge carimba branch e commit congelados no início da sessão — *lido no código*
`Sessao.__init__` chama `descobrir()` uma vez (`server.py:158`) e o `Api` guarda esse `ContextoRepo`. Os headers `X-Git-Branch`/`X-Git-Commit` e o campo `commit` do `status` nunca mais mudam.
- Todo evento gravado depois de um commit ou troca de branch leva o ponto de git errado.
- `publish_diff` calcula `base..HEAD` na hora, mas o servidor grava como `head_sha` o commit do header (o antigo). O próximo `publish_diff` usa esse `head_sha` como base (`_base_do_ultimo_diff`), então os diffs seguintes ficam sobrepostos ou vazios.
- **Correção:** reler branch e commit a cada chamada (dois `git rev-parse`).

### A2. O retry do bridge não cobre o caso para o qual existe — *confirmado em execução*
`Api.request` só trata `URLError`. Conexão derrubada depois do envio (a resposta perdida) levanta `ConnectionAbortedError`/`RemoteDisconnected` direto do `getresponse()`, fora do `try`. Sonda: servidor que recebe e derruba → **1 tentativa**, exceção crua, a tool falha. Timeout de leitura também escapa. GET nunca repete.
- **Correção:** tratar `OSError`/`TimeoutError`/`http.client.HTTPException` no laço de retry e converter o esgotamento em `ErroApi`.

### A3. Idempotência por `X-Operation-Id` tem dois furos — *confirmado em execução*
O middleware (`main.py:77`) responde do cache antes de qualquer outra coisa e a chave é só token + operation id.
1. **Requisição diferente, mesmo id:** `POST /tasks {"title":"Um"}` seguido de `POST /tasks {"title":"Dois diferente"}` com o mesmo id devolve a task "Um" nas duas. A segunda escrita some sem erro.
2. **Replay passa por cima da autenticação:** depois de reemitir o token, a chamada nova sem id dá `401`, mas a repetição com o id e o token antigo dá `201` com o corpo gravado.
- **Correção:** guardar método, caminho e hash do corpo junto da operação e responder 422 quando divergem; validar o token antes de consultar o cache. Muda a tabela `operations`.

## Média

### M1. `create_task` devolve cursor errado e não publica o corpo — *confirmado em execução*
Com `corpo`, o `cursor` devolvido é o do `task.created` (sonda: `1`, último seq real `2`). Quem continua de `read_changes(desde=cursor)` relê o evento do corpo. O evento `body.updated` também não vai para o SSE (`service.py:272`). **Correção:** devolver o último seq e publicar os dois.

### M2. Invariante "feito exige dependências resolvidas" pode ser quebrada — *confirmado em execução*
`update_task(dependencies=[B])` numa task já `feito`, com B em `ideia`, retorna 200 e deixa a task `feito` com `dependencias_pendentes: ['T-003-b']`. A checagem só roda quando `status` está no patch. **Decidir:** recusar (409) ou devolver a task para `parcial` com evento.

### M3. `update_task` valida fora da transação — *lido no código*
A task é lida e as regras (dono, ciclo, status anterior) são checadas antes do `with conn:`, que só abre a transação no primeiro `UPDATE`. Dois PATCH concorrentes gravam `valor_de` errado no evento (ambos viram "do mesmo estado") e dois PATCH de dependência que juntos fecham um ciclo passam. `update_corpo` já resolve isso com `BEGIN IMMEDIATE`; o mesmo vale aqui, relendo a task dentro.

### M4. Rotas `async` chamam SQLite bloqueante no event loop — *lido no código*
Escritas (`async def`) e o middleware de idempotência usam `sqlite3` direto. Com `BEGIN IMMEDIATE` em contenção, o loop inteiro, SSE incluso, fica parado até o timeout de 5 s do driver. Opções: serviço síncrono (roda no threadpool) com `publish` feito à parte, ou `run_in_threadpool`.

### M5. `update_body` sobrescreve sem avisar por padrão — *lido no código*
`versao_base` é opcional. A IA que esquece de mandar apaga o texto do outro lado, e o texto é sempre completo. **Sugestão:** o bridge guardar o `versao_corpo` do último `read_task` por task e mandá-lo sozinho, ou exigir o parâmetro.

### M6. O escopo "o repositório define o projeto" é só um conselho — *lido no código*
Com `project=<slug>` explícito, `_chamar` usa `api_avulsa` e age em qualquer projeto em que a pessoa seja membro, mesmo sem o repositório afiliado. O README promete que a IA "nunca esbarra no assunto de outro projeto". **Decidir:** validar `project` contra `SESSAO.projetos` (exceto `request_access`/`link_repo`) ou ajustar o texto.

### M7. Entrar em projeto `team` exige só conhecer o `root_sha` — *lido no código*
O hash do commit raiz é o mesmo em todo clone e fork, e `resolve_repo` adiciona a pessoa como member sem outra prova. Está documentado como intenção ("quem tem o repositório entra sozinho"); vale confirmar que basta, principalmente se algum repositório for público.

### M8. `read_body_diff` aceita versão inexistente — *confirmado em execução*
`desde=99` devolve o corpo inteiro como diff rotulado `v99 -> v1`. O serviço aceita `ate`, mas a rota e a tool não expõem. **Correção:** 404/422 para versão que não existe.

### M9. `PATCH` aceita título vazio — *confirmado em execução*
Create recusa `""` (422), o patch grava `''` e o code mantém o slug antigo. Falta `min_length` em `TaskPatch.title`; o slug defasado após renomear é decisão a documentar (o número é a identidade).

### M10. Token não-ASCII no header vira 500 — *confirmado em execução*
`secrets.compare_digest(str, str)` levanta `TypeError` com caractere fora de ASCII (`auth.py:41`). Comparar em bytes devolve o 401 correto.

### M11. Custo de leitura cresce com o projeto — *lido no código*
- `serializar` faz cerca de 5 consultas por task, e `ultimo_corpo` carrega o texto inteiro só para ler a versão (`MAX(version)` resolve).
- `nao_lidos` roda em **toda** resposta de tool e varre todas as tasks do projeto, mais um `hidratar` por task não lida.
- `list_tasks` não pagina e devolve tudo para dentro do contexto da IA.

### M12. Status do projeto não tem efeito — *lido no código*
`update_project` aceita `ativo`/`pausado`/`concluido`/`arquivado`, mas nenhuma regra o consulta: projeto `arquivado` aceita tasks, mensagens e diffs normalmente (só a exportação lê o valor). Ou o status passa a bloquear escrita, ou deixa de existir.

### M13. As `instructions` do bridge citam tool que não existe — *lido no código*
O texto manda usar `read_feature` (`server.py:100`), mas o bridge só expõe `create_feature`, `list_features` e `update_feature`. O REST tem leitura e exclusão de feature (`GET`/`DELETE /features/{code}`) que nenhuma tool alcança.

## Baixa

*Corrigidos em 09/11/2026: `request_access` em projeto `team` (agora 422, orientando `link_repo`), `publish_diff` com falha do git (agora devolve erro em vez de publicar "0 arquivo(s)"), chaves vazias de `INSCRITOS` no SSE e `FeaturePatch.title` vazio. Seguem abertos o SSE sem `id:`/replay e os `CHECK` de `status`/`kind`.*

- `request_access` em projeto `team` cria um pedido pendente sem sentido (confirmado: 201). Deveria orientar a usar `link_repo`.
- SSE sem `id:`/replay: `QueueFull` descarta sem avisar, `INSCRITOS` acumula chave por slug e só funciona com 1 processo. A recuperação é `/mudancas`; vale dizer isso no contrato.
- Bridge: `_git` devolve `None` em timeout ou erro, e `publish_diff` publica então "0 arquivo(s)" sem avisar; o patch inteiro sobe e só o servidor trunca em 100 mil caracteres.
- `CHECK` de `status` e `kind` obriga recriar a tabela (com `DROP TABLE`) a cada valor novo; já aconteceu duas vezes.
- A exportação para o Project Tasks MCP existe no código e no working tree, mas não consta no `CHANGELOG` nem na versão (continua 3.6.0).

## O que está bem

Ciclo de dependência barrado antes de gravar, dono validado como membro, número de task único por índice, backup antes de migração, marca de leitura que só avança, 404 em vez de 403 para quem não é membro e criação concorrente de task com retry de número.

## Cobertura de testes

A suíte cobre cancelada, dono, features/eventos e o envelope de não lidos. **Sem teste** para idempotência, diffs, membros e pedidos de acesso, autenticação e o retry do cliente.
