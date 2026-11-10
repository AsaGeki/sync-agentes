# Plano do sync-agents

Mapa de melhorias e features, agrupado por tema. Cada item diz o problema que resolve e de onde veio. A ordem dentro de cada grupo é de valor para custo, não um compromisso. Os achados de regras e contratos estão em [`REVISAO_REGRAS_E_CONTRATOS.md`](REVISAO_REGRAS_E_CONTRATOS.md) e aparecem aqui só pelo código (A1, M3...).

## 1. Confiabilidade primeiro (corrige o que já existe) - feito em 09/11/2026, servidor 3.7.0

1. **Bridge sem estado velho:** git relido a cada chamada, retry cobrindo resposta perdida, erro claro quando `git diff` falha (A1, A2, baixa).
2. **Idempotência de verdade:** operação presa a método, caminho e corpo, e checada depois da autenticação (A3).
3. **Escrita atômica em `update_task`:** `BEGIN IMMEDIATE` e releitura dentro da transação (M3, M2).
4. **Servidor sem bloquear o loop:** serviços síncronos no threadpool (M4).
5. **Contratos pequenos:** cursor do `create_task`, versão inexistente no diff de corpo, título vazio no patch, token não-ASCII (M1, M8, M9, M10).

## 2. Acesso e pessoas (lacunas do modelo)

- **Remover membro, trocar papel e sair do projeto.** Hoje só existe entrar (`add_member`, `link_repo`, `approve_request`); owner não consegue tirar ninguém nem passar o bastão.
- **Desativar pessoa em vez de apagar.** `delete_person` falha se a pessoa tem qualquer vínculo, então não há como desligar alguém que já agiu. Um campo `ativo` bloquearia o token e manteria o histórico.
- **Revogar token sem reemitir** e, opcionalmente, validade do token.
- ~~Projeto `arquivado` somente leitura (M12) e escopo do bridge por repositório (M6)~~: feitos em 3.7.0.

## 3. Tasks e fluxo de trabalho

- ~~Paginação e modo compacto em `list_tasks`~~: feito (servidor 3.7.0). Texto original:  hoje devolve todas as tasks, cada uma com dependências, feature e último não lido, para dentro do contexto da IA (M11). Um `resumo=True` com code, título, status e dono já resolve a maioria dos usos.
- **`nao_lidos` barato:** uma consulta agregada em vez de varrer as tasks a cada resposta de tool.
- ~~Tool `read_feature` no bridge (M13)~~: feita; `delete_feature` fica só no REST.
- **Prazo e prioridade na task** (`due_date`, `prioridade`) com filtro e ordenação; o web já tem ordenação por fluxo de status e poderia ganhar "vencidas".
- **Checklist dentro da task** (critérios de aceite marcáveis), no lugar de texto livre no corpo. Mexe em schema.
- **Reabertura de dependentes configurável:** hoje é sempre `feito -> parcial` em cascata; mostrar no resultado de `update_task` quais tasks foram reabertas.
- **Edição de mensagem e resposta vinculada:** `resposta` fecha a pergunta mais antiga; apontar para qual pergunta responde evita ambiguidade quando há várias abertas.

## 4. Eventos e tempo real

- **SSE com `id:` e `Last-Event-ID`:** reconexão recupera o que perdeu, sem depender só de `/mudancas`.
- **`/mudancas` sem releitura infinita:** com `de_outros=True` e só eventos próprios, o cursor não avança.
- **Webhook de saída** (chat da equipe) para pergunta e bloqueio: a pessoa soube sem abrir o web ou depender da IA ter chamado uma tool.
- **Resumo diário ou semanal** (`read_report` agendado) por projeto.

## 5. Dados e operação

- **Trocar os `CHECK` de `status`/`kind` por validação na aplicação**, para um status novo não exigir recriar a tabela com `DROP TABLE` (já foi preciso duas vezes).
- **Backup com retenção e verificação:** feito (7 diários). Falta um `GET /health` que informe idade do último backup, e um comando de restauração documentado.
- **`PRAGMA integrity_check` no start**, não só `foreign_key_check`.
- **Migrações versionadas** (`schema_migrations` já existe) no lugar da mistura de `_migrar_*` e `MIGRACOES`.
- **Exportar e importar o próprio formato** (JSON do sync-agents): mover um projeto entre servidores sem passar por ferramenta de terceiros. Aproveita o que existe em `projects/exportacao.py`.
- **Scripts de `scripts/legado`** decididos: apagar quando nenhum banco antigo precisar deles.

## 6. Web

- **Edição na web** de título e descrição de feature (hoje só leitura) e de corpo da task.
- **Busca global** entre projetos e dentro de mensagens.
- **Atalhos e filtros salvos** por pessoa.
- **Administração:** tela de membros com remoção e papel, depois do item 2.

## 7. Qualidade e entrega

- **Testes para o que não tem:** idempotência, diffs, membros e pedidos de acesso, autenticação, retry do cliente. A suíte atual leva cerca de 4 minutos (237 s para 292 testes); vale medir onde o tempo vai.
- **`CHANGELOG` e versão em dia** (a exportação não está registrada) e a versão do bridge amarrada à do contrato.
- **CI que roda a suíte** em PR; hoje o único workflow é o de publicação do cliente.
- **Linha de comando de administração** (`sync-agents-admin`): criar pessoa, emitir token, listar projetos, sem depender do Bruno ou do `/web/admin`.

## Decisões abertas

1. A exportação para o sistema de destino continua no código (decidido manter por ora). Rever depois da etapa 1.
2. ~~`root_sha` como prova de entrada (M7)~~: resolvida em 3.7.0, o repositório não adiciona mais ninguém; entrar é `join_project` ou `request_access`.
