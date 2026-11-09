# Revisão do Project Tasks MCP e comparação com sync-agents

Data: 04/11/2026.

## Escopo e método

- Origem: `augustoOliveira1993/project-tasks-mcp`, branch `main`, commit `500661c2bd61fa95e0fe41f62d69d7bcd44bf679`.
- Comparação: checkout local de `sync-agents`, HEAD `c1944932e98c7639b4ca2dbf6bec9943ab4dec43`, incluindo as alterações locais que já existiam.
- O projeto remoto foi baixado pela API autenticada do GitHub para uma pasta temporária. Nenhum fluxo Git foi alterado.
- Revisão de código dos caminhos de autenticação, sessão MCP, tarefas, dependências, bridge Git e importação/exportação. Não é uma auditoria exaustiva do frontend, do runner ou de segurança.
- Quatro comportamentos foram reproduzidos em memória, executando trechos extraídos do código com dependências simuladas: conclusão de tarefa, troca de token na sessão, erro auxiliar após gravação e deduplicação de mensagens. Isso valida os trechos, mas não substitui execução integrada com MongoDB e clientes MCP.
- O projeto remoto não possui dependências instaladas na cópia de análise. Não foram instaladas dependências, criados testes ou executadas mutações no servidor da equipe.
- Validação do checkout local: `.venv/Scripts/python.exe -m pytest server/tests client/tests -q -p no:cacheprovider`, com bytecode desabilitado, terminou com **292 testes aprovados**, em 227,44 segundos. Houve um aviso de depreciação da integração Starlette/AnyIO. A infraestrutura existente usa SQLite descartável e não abre o banco real.
- A suíte e o build do Project Tasks MCP não foram executados. Os achados abaixo não significam que toda a aplicação tenha sido validada em execução.

## Achados priorizados

### 1. Alta — Uma gravação bem-sucedida pode aparecer como erro na bridge

**Local:** [src/bridge/main.ts:124–128](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/bridge/main.ts#L124-L128). Também ocorre no caminho de publicação de diff, linhas 106–109.

**Cenário:** a ferramenta cria ou altera um registro; em seguida, a consulta `get_project_novelties` falha por indisponibilidade transitória.

**Causa:** a escrita e a leitura auxiliar compartilham o mesmo `try/catch`. A falha posterior descarta `result` e devolve `isError: true`, embora a escrita já tenha terminado.

**Impacto:** a IA recebe uma informação incorreta sobre o resultado e pode tentar executar novamente. Nas ferramentas encaminhadas, repetir o mesmo `operationId` preserva a idempotência; gerar outro UUID pode duplicar a ação. Em `publish_task_diff`, o UUID é gerado internamente em cada chamada: repetir com `baseCommit` explícito pode registrar o mesmo diff novamente. Sem base explícita, a repetição também pode terminar em erro de diff vazio.

**Evidência:** a execução isolada registrou uma gravação e retornou `isError: true` quando somente a consulta de novidades lançou erro.

**Comparação:** o `sync-agents` já preserva o resultado e acrescenta `nao_lidos_indisponivel` quando a consulta auxiliar falha (`client/src/sync_agents_mcp/server.py:274–280`). Existe cobertura específica em `client/tests/test_envelope_nao_lidos.py:76`.

**Direção de correção:** preservar o resultado principal e representar a falha auxiliar em um campo separado; manter o identificador da publicação de diff disponível para repetição idêntica.

### 2. Alta — Conclusão direta ignora dependências pendentes

**Local:** [src/service.ts:2078–2099](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/service.ts#L2078-L2099).

**Cenário:** tarefa A está pendente ou bloqueada e depende de B, que ainda não foi concluída. Uma credencial de agente com escrita chama `set_task_status` com `status: concluida` e versão correta.

**Causa:** `applyTaskStatus` permite essas transições e salva o estado sem consultar as dependências. A verificação de dependências existe em `claim_task` (linhas 1160–1165), mas pode ser contornada pela conclusão direta. A autorização genérica e o guard de automação não acrescentam essa verificação para um agente comum, sem `jobId`.

**Impacto:** o grafo pode apresentar trabalho concluído apoiado em pré-requisitos ainda pendentes. Como `claim_task` confere apenas o status das dependências diretas, outras tarefas podem ser liberadas a partir dessa conclusão.

**Evidência:** execução isolada de `applyTaskStatus` passou A de `pendente` para `concluida`, mantendo `dependencies: [B]`, sem consultar tarefas. O mesmo trecho também aceitou `acceptanceProgress: [false]`: a verificação dos critérios, nesse caminho, depende da conduta do agente, não de uma barreira no servidor.

**Comparação:** o `sync-agents` verifica dependências ao fechar a tarefa e reabre dependentes concluídas em cascata quando um pré-requisito é reaberto (`server/src/modules/tasks/service.py:76`, `:120`, `:499`, `:525`). O consolidado também permite reabrir uma tarefa concluída sem tratar suas dependentes em `applyTaskStatus`.

**Direção de correção:** definir a regra de conclusão e aplicá-la aos caminhos MCP, humano e aprovação em lote. Se o administrador puder forçar uma conclusão, essa exceção deve ser explícita. Definir também o comportamento esperado das dependentes quando uma tarefa for reaberta.

### 3. Média — Trocar o token do projeto não atualiza uma sessão MCP existente

**Local:** [src/http.ts:641–649](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/http.ts#L641-L649), criação do ator da sessão na linha 577 e execução das ferramentas na linha 609. O GET repete o padrão nas linhas 653–655.

**Cenário:** no modo `trusted_local`, a pessoa inicia uma sessão com `X-Project-Tasks-Project-Token` de A. Na mesma sessão, envia o token de B, mantendo o mesmo e-mail.

**Causa:** a requisição é autenticada novamente, mas o código compara apenas `actor.id`. O ator recém-criado é descartado; as ferramentas continuam recebendo `session.actor`, com o token inicial.

**Impacto:** B permanece inacessível nessa sessão. Remover o cabeçalho também não remove o token já retido. A rotação do token armazenado no banco continua sendo verificada pelo serviço; este achado não demonstra que um token revogado no banco continue válido.

**Evidência:** execução isolada do handler recebeu `token-B`, mas a sessão permaneceu com `token-A`.

**Direção de correção:** atualizar o contexto autenticado da requisição ou rejeitar a mudança de contexto com orientação explícita de reconexão. Considerar chamadas concorrentes ao escolher a implementação.

### 4. Média — Conflito de nome de tipo de conversa aborta a importação inteira

**Local:** [src/services/project-import-service.ts:247–295](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/services/project-import-service.ts#L247-L295), inserção na linha 407 e índice único em [src/models.ts:58](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/models.ts#L58).

**Cenário:** o destino contém um tipo de conversa ativo com o mesmo `projectId` e `nameKey` do pacote, mas com outro `_id`. Isso pode ocorrer ao importar novamente depois de o tipo original ter sido removido e recriado no destino.

**Causa:** o importador trata conflito por `_id` e várias outras chaves únicas, mas não a chave de tipos de conversa ativos. O registro chega a `insertMany` e viola o índice único parcial `{ projectId, nameKey }`.

**Impacto:** a transação inteira é revertida e a API retorna 409, inclusive para registros independentes que poderiam ser importados. Isso contraria a proposta declarada de preservar conflitos e continuar com os demais registros.

**Evidência:** confirmado por leitura do filtro, do índice e do tratamento transacional em `src/service.ts:257–268`. Não reproduzido com MongoDB.

**Direção de correção:** tratar essa chave antes da inserção e definir o tratamento das conversas que referenciam um tipo conflitante, preservando seus snapshots quando aplicável.

### 5. Média — Migração pode ignorar mensagens distintas com o mesmo UUID de operação

**Local:** [src/services/project-export-service.ts:6–27](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/services/project-export-service.ts#L6-L27), [src/services/project-import-service.ts:266–295](https://github.com/augustoOliveira1993/project-tasks-mcp/blob/500661c2bd61fa95e0fe41f62d69d7bcd44bf679/src/services/project-import-service.ts#L266-L295) e índice em `src/models.ts:72`.

**Cenário:** duas pessoas enviam mensagens distintas na mesma conversa com o mesmo `operationId`. É um conjunto permitido pelo banco, pois a unicidade inclui `senderId`.

**Causa:** a exportação remove `senderId`; a importação atribui `senderId: import` a todas as mensagens e deduplica apenas por conversa e operação. Duas identidades válidas da origem se tornam uma única chave no destino.

**Impacto:** uma mensagem é ignorada como conflito, embora não seja duplicata. O descarte é contabilizado pelo importador; não é necessariamente silencioso. A frequência prática é baixa com UUIDs gerados independentemente, mas o contrato permite essa combinação.

**Evidência:** execução isolada do laço de deduplicação, com duas mensagens de remetentes diferentes, marcou a segunda como ignorada.

**Direção de correção:** usar uma identidade de importação derivada de cada mensagem ou preservar um identificador estável e não secreto do remetente para manter a chave original.

## Comparação de proposta e arquitetura

| Aspecto | sync-agents | Project Tasks MCP | Consequência |
| --- | --- | --- | --- |
| Objetivo | Alinhamento entre pessoas e suas IAs | Gestão de tarefas e execução de agentes | O consolidado cobre um domínio maior e exige mais controles operacionais. |
| Stack | Python, FastAPI, SQLite, Jinja2/htmx | TypeScript, Express, MongoDB, React/Vite | SQLite simplifica a operação; o consolidado exige replica set para as transações. Isso, isoladamente, não determina qualidade ou capacidade. |
| MCP | Cliente stdio publicado separadamente | HTTP canônico e bridge Git opcional | O consolidado centraliza ferramentas, mas também passa a gerenciar sessões HTTP. |
| Contexto Git | Commit raiz; múltiplas raízes são ordenadas | Bridge cruza remote e commit raiz previamente vinculados | O vínculo explícito dá controle administrativo; a bridge escolhe a primeira raiz retornada pelo Git sem ordenação, um ponto a revisar em históricos unidos. |
| Identidade | Token pessoal; identidade resolvida pelo servidor | Credenciais com escopo ou identidade declarada em `trusted_local` | `trusted_local` confia no e-mail enviado: é uma decisão documentada, não um bug novo identificado nesta revisão. |
| Concorrência | Transações SQLite e versão do corpo | `operationId`, versões, transações MongoDB, fences e leases | O consolidado tem mecanismos explícitos para concorrência e recuperação de execução. O sync-agents não tem uma reserva de execução equivalente. |
| Dependências | Bloqueio de conclusão e reabertura em cascata | Validação do grafo e bloqueio na tomada de tarefa | As garantias de conclusão do sync-agents precisam ser consideradas na consolidação. |
| Falha de novidades | Preserva o resultado principal | Bridge pode substituir sucesso por erro | Comportamento do sync-agents que merece ser incorporado ao consolidado. |
| Automação | Sem runner equivalente | Jobs, runners Codex/Claude, propostas e permissões | Expansão funcional relevante; precisa de revisão própria antes de presumir isolamento completo. |
| Documentos e anexos | Corpo versionado, mensagens e diffs | Markdown com revisões, anexos e memórias de projeto/tarefa | O consolidado oferece mais recursos e mais contratos de integridade. |
| Organização | Separação cliente/servidor e módulos por domínio | Serviços extraídos, mas `service.ts` ainda reúne 2.141 linhas | A concentração aumenta o custo de localizar regras repetidas ou divergentes. Não é, sozinha, um defeito funcional. |

## Cuidados na comparação e na migração

- Os estados não são equivalentes: o sync-agents tem `parcial` e `aguardando_decisao`; o consolidado tem execução com lease e etapa de revisão. A conversão deve ser entendida como transformação do fluxo, não apenas tradução de nomes.
- A exportação local transforma tarefas em andamento em bloqueadas para não inventar execuções ativas. Esse comportamento está documentado e não foi classificado como bug.
- O exportador local já documenta que importar um pacote atualizado não atualiza registros existentes. Isso limita o uso como sincronização contínua; não equivale a uma falha de idempotência.
- A comparação não sustenta a conclusão de que um projeto inteiro é melhor. O consolidado tem maior cobertura funcional; o sync-agents contém garantias úteis de colaboração que não aparecem em todos os caminhos equivalentes do consolidado.

## Ordem recomendada

1. Preservar resultados de gravação quando falhar a consulta auxiliar da bridge.
2. Unificar as invariantes de conclusão e reabertura de tarefas.
3. Corrigir a atualização do contexto autenticado nas sessões.
4. Tratar as chaves únicas de importação e a identidade das mensagens.
5. Revisar o runner separadamente, incluindo permissões, limites do checkout, retomada e efeitos externos.

Nenhuma dessas correções foi aplicada nesta revisão. Alterações em enums, tipos, interfaces ou schemas dependem de aprovação explícita do usuário.

## Funcionalidades do sync-agents que poderiam ser incorporadas

Comparação com a mesma revisão do consolidado indicada no início deste documento. Ausência significa que não foi localizado um equivalente nos contratos e caminhos revisados, não uma garantia sobre versões posteriores ou implementações externas.

| Funcionalidade | O que existe no sync-agents | Situação no Project Tasks MCP | Benefício e prioridade sugerida |
| --- | --- | --- | --- |
| Reabertura de dependentes em cascata | `_reabrir_dependentes`, em `server/src/modules/tasks/service.py`, reabre tarefas concluídas que dependiam de uma tarefa reaberta. | `applyTaskStatus` altera somente a tarefa selecionada. | Alta: impedir que a cadeia continue aparecendo como concluída sobre uma base reaberta. Precisa definir como tratar dependentes com execução ativa. |
| Diff do texto de planejamento | `read_body_diff` compara uma versão do corpo com a atual; é separado do diff de código. | Existem revisões de Markdown, leitura de revisão e diffs Git; não foi localizada uma ferramenta equivalente que calcule o diff entre revisões do documento. | Alta: mostrar exatamente o que mudou no escopo sem exigir a leitura e comparação de duas versões completas. |
| Códigos humanos de tarefas e features | `T-007-migrar-relatorio`, `F-003-...`; aceita também `T-7` e `T-007`. Implementação em `server/src/shared/codes.py`. | Entidades usam UUID; `resolve_task_context` também aceita prefixo de UUID, que é um atalho diferente de código sequencial por projeto. | Média: facilitar referências em conversas, reuniões e commits. Preservar UUID como identidade interna. |
| Tags livres | A tarefa armazena várias tags, independentemente de status, dono e feature. | Há área, tipo e feature, mas não um campo de tags nos contratos e modelos de tarefa revisados. | Média: permitir classificações transversais, como `integracao-sap`, `cliente-x` e `migracao`, sem multiplicar áreas e tipos. |
| Solicitação de acesso com aprovação | `request_access`, `list_requests`, `approve_request` e `reject_request`, com pedidos persistidos. | Há administração de membros e token de projeto privado; não foi localizado o fluxo equivalente de pedido pendente e decisão do administrador. | Média: tornar a entrada na equipe rastreável e evitar depender exclusivamente de concessão manual fora do sistema. O desenho deve respeitar os controles humanos administrativos do consolidado. |
| Distinção entre trabalho parcial e decisão pendente | Estados `parcial` e `aguardando_decisao` preservam essas situações separadamente. | O conjunto de estados não distingue esses dois motivos: a conversão local usa estados mais amplos. | Condicional: melhorar a leitura de impedimentos. Avaliar motivo estruturado ou indicador antes de ampliar a máquina de estados de execução. |

Também vale incorporar a preservação do resultado principal quando a consulta de novidades falha, descrita no achado 1. É uma melhoria de confiabilidade existente no sync-agents, não uma nova funcionalidade de produto.

Não devem ser propostas como ausências: novidades e tarefas não lidas, relatório de sincronização (`get_project_sync_report`), perguntas abertas, resumos por feature, histórico de Markdown, diffs Git e atualização por eventos. O consolidado já contém recursos nessas famílias; diferenças de comportamento devem ser avaliadas individualmente.

Para uma primeira rodada de aproveitamento, as prioridades sugeridas são reabertura de dependências, diff de planejamento e códigos humanos. Esta lista é uma avaliação para discussão; nenhuma implementação foi iniciada.
