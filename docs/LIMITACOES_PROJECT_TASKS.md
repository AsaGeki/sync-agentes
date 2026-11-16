# Limitações do project-tasks que só se resolvem no código dele

- **Prompt summary:** levantar tasks e features sem dono no project-tasks e anotar as limitações do project-tasks que o sync-agents não consegue contornar, mas que poderiam ser corrigidas editando o código dele (base para um PR).
- **Creation date:** 2026-11-16
- **Change count:** 3
- **Last update date:** 2026-11-16
- **Last prompt summary:** registrar o que foi implementado no sync-agents depois do deploy do PR e as decisões que não mudaram.

Fonte de verdade do project-tasks: repositório `project-tasks-mcp` (pasta irmã `../project-tasks-mcp`; as linhas citadas valem para o commit base `21b95d9`, antes do PR). Os caminhos abaixo são relativos a ele. Números de prod medidos em 2026-11-16 com a credencial de serviço do `.env`, só leitura (`list_records`), comparados ao `sync.db` do sync-agents.

## 1. Tasks e features sem dono

### Medição

| Projeto | Tasks vindas do sync | Sem responsável | Tasks nativas do destino | Sem responsável |
|---|---|---|---|---|
| fbi-crm | 59 | 54 | 409 | 69 (36 `pendente`, 29 `concluida`, 3 `cancelada`, 1 `em_execucao`) |
| avb-one | 269 | 9 | 0 | - |
| sso | 87 | 0 | 93 | 3 (`pendente`) |

Features: **nenhuma** das 42 + 17 + 19 features dos três projetos tem dono, porque o campo não existe (ver 1.3).

### Causas

1. **Origem sem dono (tasks do sync).** `tasks.owner_id` do sync-agents é opcional. No fbi-crm, 55 de 60 tasks não têm dono (criadas por Arthur e Alexandro, quase todas `feito` ou `parcial`); no avb-one, 6 (da Manuca, que recebeu o dono depois). O sync só envia `responsible` quando há dono, então o destino herda o vazio. A IA também cria task sem `owner_id` quando não sabe o id (ver `status` → `person_id`, versão 0.4.1 do cliente).
2. **O project-tasks não define responsável na criação.** `responsible` é opcional em `src/schema.ts:86` e só é preenchido automaticamente na `claim_task` (`src/service.ts:1194`). Task criada à mão ou pelo MCP sem `responsible` fica sem dono até alguém assumir a execução.
3. **Feature não tem dono.** O modelo `Feature` (`src/models.ts:14`) só tem `name`, `objective`, `context` e `acceptance`; `featureData` (`src/schema.ts:82`) idem. Não há como atribuir, filtrar nem mostrar responsável por feature. O sync-agents grava só "Criado por: e-mail" em `context`.

O que o project-tasks já oferece: filtro `sem-responsavel` no workspace (`src/service.ts:1275`) e "Sem responsável" nos dashboards (`src/services/project-dashboard-service.ts:102`). O que falta é evitar que a task nasça sem dono.

### O que dá para fazer só no sync-agents (sem PR no project-tasks)

| Ação | Efeito | Decisão pendente |
|---|---|---|
| **Feito:** exportar `responsible` = autor do evento `task.created` quando a task não tem dono (`criadores` em `montar_pacote`, `server/src/modules/sincronizacao/pacote.py`, mesma regra de `tasks_donas`) | Zera os 54 + 9 do sync sem mexer no banco de origem; conferido nos pacotes dos três projetos (0 tasks sem responsável) | Chega ao destino na próxima sincronização de cada projeto |
| `create_task` assumir `owner_id` = quem assina quando omitido | Para de gerar task sem dono | Muda o contrato da tool; `owner_id=0` continuaria tirando o dono |
| Script que preenche `owner_id` das tasks sem dono com o criador | Corrige o passado na origem | Escreve no `sync.db` de prod: precisa de backup e aval |

## 2. Limitações que exigem mudança no project-tasks

| # | Limitação | Evidência no código | Efeito observado no sync | Mudança proposta no project-tasks |
|---|---|---|---|---|
| L1 | **Feature sem responsável** | `src/models.ts:14`, `src/schema.ts:82` | 78 features sem dono; não dá para mostrar nem filtrar por pessoa | Campo opcional `responsible` em `Feature` (modelo, `featureData`, DTOs, `list_records` e catálogo `/catalogs/features`) |
| L2 | **Task nasce sem responsável** | `src/schema.ts:86` (opcional), `src/service.ts:1194` (só na claim) | 69 nativas e 63 do sync sem dono em fbi-crm/avb-one | Opção de definir o responsável padrão como o usuário autenticado em `create_task` (ou campo obrigatório) |
| L3 | **`pendente → bloqueada` proibido** | mapa `allowed` em `src/service.ts:2141`: `bloqueada` só nasce de `em_execucao`, exige execução ativa e grava impedimento nela; `set_task_status` aceita só `pendente`, `em_revisao`, `concluida`, `cancelada` (`src/schema.ts:248`) | Tasks `bloqueado`/`aguardando_decisao` da origem (T-071, T-193, T-247) ficam `pendente` no destino para sempre e reaparecem como "ignoradas" em toda prévia | Transição administrativa `pendente → bloqueada` sem execução, com `reason` registrado no evento; incluir `bloqueada` no enum de `set_task_status` |
| L4 | **Sem estado "em andamento" fora do runner** | `em_execucao` só vem de `claim_task` (`src/service.ts:1194`) e o admin só sai dele para `bloqueada` (`src/service.ts:2107`) | O sync mapeia `em_andamento`, `bloqueado` e `aguardando_decisao` para o mesmo `bloqueada`; o destino perde a distinção | Estado ou marcador administrativo de "em andamento" e de "aguardando decisão", ou um campo de rótulo livre na task |
| L5 | **`cancelada` é terminal** | mapa `allowed` em `src/service.ts:2141-2147` não tem chave `cancelada` | Task cancelada e depois reaberta na origem não volta no destino | Permitir `cancelada → pendente` na rota administrativa |
| L6 | **Limite de 20.000 caracteres só na edição** | `text = z.string().min(1).max(20000)` em `src/schema.ts:6`, usado em `name`/`instructions`; a importação não valida o tamanho (há `instructions` de 25.949 caracteres em prod) | Corpos grandes entram na importação mas nunca mais atualizam: T-194, T-200 e T-226 estão desatualizados (T-226: 45,7 mil na origem, 31,8 mil no destino) | Alinhar os limites (subir o da edição ou aplicar o mesmo na importação) e/ou mover o corpo para documento Markdown revisionado em vez de `instructions` |
| L7 | **Importação só insere** | `src/services/project-import-service.ts:258` ("O ID já existe no projeto; registro preservado"), `:388` (projeto existente preservado), `:201-203` (mesmo digest = pacote ignorado) | Features, `markdownDocuments` (contador `revision`) e qualquer registro já importado nunca são atualizados por import; tudo que muda depois exige `edit_record` registro a registro | Modo "upsert" opt-in na importação (por `_id`, respeitando `version`) ou endpoint de lote para `edit_record` |
| L8 | **Importação exige administrador do sistema** | erro "System administrator required" tratado em `server/src/modules/sincronizacao/execucao.py` (`_mensagem`) | A credencial de serviço do `.env` precisa ser de admin total para importar; admin só do projeto não basta | Papel/escopo "importador" por projeto, ou permitir import a admin do projeto de destino |
| L9 | **Critérios de aceite e prioridade ficam vazios nas tasks do sync** | criação exige `acceptance` com ao menos 1 item e `priority` (`src/schema.ts:82-86`); a importação aceita `[]` e `0` | 0 de 415 tasks do sync têm critério; as nativas têm quase todas | Validação única nos dois caminhos, ou campo de mapeamento para o sync gravar critérios (ex.: checklist do corpo) |
| L10 | **Autoria por cabeçalho no `trusted_local`** | `AGENTS.md`: "qualquer pessoa capaz de enviar o cabeçalho pode assumir o e-mail informado" | O sync depende de token humano por pessoa para a autoria sair certa; sem token, tudo vai como a conta de serviço | Autenticação por token também no modo local, ou rejeitar o cabeçalho fora de rede confiável |

## 3. Ordem sugerida para um PR

1. **L1 + L2** (dono em feature e responsável padrão na criação): resolvem direto o "sem dono" e são mudanças aditivas, sem quebrar contrato.
2. **L3 + L5** (transições administrativas): pequenas, ficam todas no mapa `allowed` e em `set_task_status`; desbloqueiam o espelhamento de status.
3. **L6** (limites alinhados): evita corpo desatualizado.
4. **L7, L8, L9, L4, L10**: maiores ou de decisão de produto; abrir como issues separadas.

Antes de abrir o PR: seguir `AGENTS.md` e `README.md` do project-tasks-mcp, rodar a suíte de `test/` e ajustar o frontend (`frontend/`) onde o campo novo aparecer (L1, L2).

## 4. O que não existe hoje

- Dono de feature no project-tasks: não existe.
- Responsável padrão na criação de task: não existe.
- Transição administrativa para `bloqueada` sem execução ativa: não existe.
- Reabertura de task `cancelada`: não existe.
- Atualização de registro existente pela importação: não existe.

## 5. Implementação (branch `feat/melhorias-para-sync-agents`, project-tasks, ainda local)

Um commit por limitação. Nada foi enviado ao remoto nem implantado em prod.

| L | Commit | O que foi feito | Diferença em relação à proposta |
|---|---|---|---|
| L1 | `bcaf89e` | `Feature.responsible` (modelo, `featureData`, contrato, contexto da task, tela de features); `create_feature` assume quem cria | A importação passa a aceitar o campo sozinha, porque valida pelo modelo |
| L2 | `c4d0150` | `create_task` assume `actor.userId` quando `responsible` é omitido | Só lógica de serviço, sem mudança de schema |
| L3 | `4cf941c` | `pendente → bloqueada` na rota administrativa, sem exigir execução; motivo fica no evento | O enum de `set_task_status` (agente) não mudou: a rota humana `/admin/tasks/status` já aceitava `bloqueada` |
| L5 | `ab2e7a8` | `cancelada → pendente` | - |
| L4 | `0210e79` | Campo livre `progressLabel` (até 80 caracteres) na task, editável no editor | Versão mínima: não aparece ainda na tabela de tasks |
| L6 | `8bd9016` | `instructions` da task aceita até 100.000 caracteres (nome e demais textos seguem em 20.000) | - |
| L7 | `0b6ff99` | `POST /admin/records/edit-batch` (até 100 edições, resultado por item) | Escolhido o lote em vez do modo upsert da importação |
| L8 | `b73d077` | Administrador do projeto importa em projeto que já existe e que ele administra; projeto novo continua exigindo admin do sistema | - |
| L9 | `f0b4dc9` | `priority` assume 0 na criação quando omitida | `acceptance` continua exigindo ao menos 1 critério na criação: é regra central para as IAs |
| L10 | `2119709` | `TRUSTED_LOCAL_SECRET` opcional: exige `X-Project-Tasks-Secret` junto do e-mail | Opt-in; sem a variável nada muda |

Teste extra: `55633e3` ajusta 3 testes de "task órfã" em `test/flow.test.ts`, que criavam a task pela API e agora precisam limpar o responsável padrão.

Testes do backend (8 arquivos, um por vez): as falhas que sobraram já existiam antes das mudanças (execução expirada, override de status humano, handshake MCP, 2 de transferência e 1 de criação humana). Não foram criados testes novos. O typecheck do `src` passa; o do frontend não roda aqui porque faltam dependências instaladas (`lucide-react`, `@radix-ui/*`).

## 6. O que mudou no sync-agents depois do deploy do PR

O prod já aceita a rota de lote (sondagem com lote vazio respondeu 400 de validação, sem escrever). Mudanças em `server/src/modules/sincronizacao/`:

| Antes (contorno ou limite) | L | Agora |
|---|---|---|
| Features chegavam sem dono; só "Criado por" em `context` | L1 | `pacote.py` exporta `responsible` = criador da feature. `planejar` inclui features: a que está sem responsável no destino recebe o criador; a que já tem responsável não é alterada |
| `pendente → bloqueada` "não é permitido": `bloqueado` e `aguardando_decisao` nunca chegavam | L3 | `TRANSICOES["pendente"]` ganhou `bloqueada` em `destino.py` |
| `em_andamento`, `bloqueado` e `aguardando_decisao` viravam todos `bloqueada`, sem distinção | L4 | O mapa de status continua igual: `em_andamento` segue como `bloqueada` para que nenhuma automação do destino assuma a task como `pendente`. O que mudou é o `progressLabel` ("Em andamento", "Aguardando decisão", "Parcial"), enviado em `pacote.py` e atualizado pelo plano (campo `progressLabel`) |
| Texto acima de 20.000 caracteres era ignorado (T-194, T-200, T-226) | L6 | `LIMITE_NOME` = 20.000 e `LIMITE_INSTRUCOES` = 100.000 |
| Uma chamada de edição por task | L7 | `aplicar_plano` edita em lotes de 100 por `/admin/records/edit-batch` (tasks e features), com falha reportada por item |
| Mensagem dizia que administrador só do projeto não importa | L8 | `_mensagem` em `execucao.py` passa a dizer que vale administrador do sistema ou, em projeto que já existe, administrador do projeto. A credencial de serviço continua sendo a preferida para importar |
| Criador como responsável quando a task não tem dono | L2 | Continua necessário para as tasks do sync-agents (já em `pacote.py`) |

Decisões que **não** mudaram:
- **L5 (`cancelada → pendente`):** o sync não reabre task `cancelada` nem `concluida` no destino ("não reaberta"). Reabrir sobrescreveria uma decisão tomada no destino, então a regra ficou.
- **Sync e a credencial pessoal na importação:** as telas ainda falam em "administrador do sistema" nos textos de ajuda; só a mensagem de erro foi atualizada.

Prévia calculada contra prod (somente leitura) depois das mudanças, para Arthur e Manuca: as 4 ignoradas por "não é permitido" e as 3 por texto grande deixaram de aparecer, e há edições de `progressLabel`, de `responsible` (54 no fbi-crm) e de dono de feature (17 no avb-one, 8 no sso, 5 no fbi-crm).
