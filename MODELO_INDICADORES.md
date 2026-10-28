# Modelagem e regras de negócio do "indicadores" (Dash-Sig / backend_sig)

Referência de domínio para quando for pedido traduzir/organizar as tasks do
sync no modelo do indicadores. Não é sobre arquitetura de código (camadas,
pastas) — é sobre como o domínio é modelado e quais regras de negócio valem
para cada entidade, fonte: `backend_sig/src/modules/indicadores`
(`C:\dev\node\Dash-Sig`).

O domínio tem três entidades: **Projeto**, **Tarefa** (filha de Projeto) e
**Requisição de Alteração** (entidade solta, sem relação com Projeto/Tarefa).

## Projeto (`IndicadorProjeto`)

Campos: `nome`, `descricao`, `status`, `prioridade`, `responsaveis` (lista de
colaboradores), `tarefas` (lista de referências a Tarefa), `setor`,
`inicio_planejado` (default: agora), `fim_planejado`, `inicio_real`,
`fim_real`, `evolucao` (número, default 0), `created_by`, `updated_by`.

`status` é livre (string), mas na prática assume: `Não iniciado`,
`Em andamento`, `Finalizado`.

### Regras de negócio

- **Criar**: nome deve ser único — se já existir projeto com o mesmo nome,
  rejeita. Ao criar, pode vir já com uma lista de `tarefas` embutida no
  payload: cada uma é criada como Tarefa separada (vinculada ao projeto
  recém-criado) e o projeto é atualizado com os ids gerados.
- **Editar**: recebe a lista completa de tarefas do projeto e faz um diff
  contra o que existe no banco:
  - tarefa da lista sem `_id` -> cria nova tarefa vinculada ao projeto;
  - tarefa da lista com `_id` -> atualiza a tarefa existente;
  - tarefa que existia no projeto mas sumiu da lista enviada -> é deletada.
  - Depois do diff, **recalcula automaticamente** `evolucao` e `status` do
    projeto a partir das tarefas atuais (ver regra de evolução abaixo).
- **Deletar**: exclusão direta por id, sem cascata documentada para as
  tarefas filhas (a orfandade de tarefas ao deletar projeto não é tratada
  explicitamente no service).
- **Buscar**: por id (erro de negócio se não encontrar) ou lista paginada
  com busca/ordenação/filtro por ano (`ano` filtra pelo ano de
  `inicio_planejado`).

### Regra de evolução e status automático (recalculada a cada update)

```
totalTarefas   = tarefas.length
concluidas     = tarefas.filter(status === 'Executada').length
evolucao       = totalTarefas > 0 ? (concluidas / totalTarefas) * 100 : 0

evolucao == 100  -> status = 'Finalizado',    fim_real = data enviada ou agora
evolucao == 0    -> status = 'Não iniciado',  fim_real = null
0 < evolucao < 100 -> status = 'Em andamento', fim_real = null
```

Ou seja: **o status do projeto nunca é setado manualmente** de forma
persistente — ele é sempre derivado do progresso das tarefas filhas toda vez
que o projeto é atualizado (via edição do próprio projeto, ou indiretamente
via update de uma tarefa, ver abaixo).

## Tarefa (`IndicadorTarefa`)

Campos: `nome`, `descricao`, `status`, `prioridade`, `responsavel` (um único
colaborador, dono da tarefa), `inicio_planejado`, `fim_planejado`,
`data_conclusao_real`, `data_conclusao` (deprecated, mantido só por
compatibilidade com registros antigos), `projeto` (referência ao Projeto
pai), `created_by`, `updated_by`.

`status` é fechado em 4 valores (enum `STATUS_TAREFA`):
`Não Executada` (default) | `Em andamento` | `Executada` | `Bloqueada`.
**Só `Executada` conta para o % de conclusão do projeto.**

### Regras de negócio

- **Criar**: nome deve ser único no escopo de tarefas (mesma checagem de
  duplicidade do Projeto). Existe também `CreateMass` para criar várias
  tarefas de uma vez (sem checagem de duplicidade, sem transação — segue
  criando mesmo se um item falhar, e devolve contagem de sucesso/erro).
- **Editar** — é aqui que mora a regra mais sutil do domínio:
  1. Se a tarefa é a primeira do projeto a ser concluída (`status` vira
     `Executada` e o projeto ainda não tinha nenhuma tarefa executada),
     o **projeto** é forçado para `Em andamento` (garante que um projeto
     não fique "Não iniciado" com trabalho já concluído).
  2. `data_conclusao_real` é carimbada automaticamente pela transição de
     status, e só se o campo não vier explícito no payload:
     - virou `Executada` agora (não estava antes) -> carimba `agora`;
     - saiu de `Executada` para outro status (reabriu) -> limpa para `null`;
     - qualquer outra transição -> não mexe no campo.
  3. Depois de salvar a tarefa, **o projeto pai é recalculado** com a mesma
     fórmula de evolução/status descrita acima (uma tarefa mudando de status
     propaga para o progresso do projeto).
- **Deletar**: exclusão direta por id. (Não recalcula o projeto pai
  automaticamente no service de delete — a tarefa é apenas removida do
  banco; a lista `tarefas` do projeto só é mantida em sincronia através do
  fluxo de edição do projeto.)
- **Buscar**: por id ou lista paginada, populando `projeto` e `responsavel`.

## Requisição de Alteração (`RequisicaoAlteracao`)

Entidade independente (não é filha de Projeto). Representa uma solicitação
pontual de mudança em algum sistema, com dono e prazo — sem sub-itens.

Campos: `sistema`, `setor`, `solicitante`, `responsavel`, `status` (default
`Não executada`, valor usado para "concluída" é `Executada`), `prioridade`,
`observacao`, `data_abertura`, `data_fechamento`, `data_planejada`,
`created_by`, `updated_by`.

### Regras de negócio

- **Criar**: `data_abertura` é sempre carimbada com o momento da criação
  (não vem do payload).
- **Editar**: update simples — sobrescreve os campos enviados, sem cálculo
  derivado (diferente de Projeto/Tarefa, aqui não há recalculo automático de
  status a partir de nada).
- Não tem conceito de "filhos"; é uma entidade CRUD simples com dono,
  prazo e status.

## Regra transversal: classificação por prazo (usada nos indicadores/dashboards)

Tanto Projeto quanto Requisição de Alteração, quando agregados para exibição
(painéis, gráficos por colaborador/setor/mês), são classificados em 3 baldes
com a mesma lógica:

```
concluído (status == 'Finalizado' / 'Executada')      -> "executadas"
em aberto E prazo planejado já vencido                -> "atrasadas"
em aberto E ainda dentro do prazo                      -> "naoExecutadas"
```

O prazo comparado é `fim_planejado` (Projeto) ou `data_planejada` (Requisição
de Alteração) contra o momento atual (fuso `America/Sao_Paulo`). Essa é a
regra a considerar se o modelo de tasks do sync precisar de um conceito de
"atrasada" derivado de prazo + status, em vez de um campo próprio.

## Resumo para tradução ao domínio do sync

Ao mapear `src/modules/tasks`/`projects` do sync para este modelo, os pontos
que carregam regra de negócio (não só nome de campo) são:
1. Status de Projeto é **sempre derivado** das tarefas filhas, nunca setado
   manualmente de forma persistente.
2. Só um valor de status de Tarefa (`Executada`) conta para progresso.
3. Conclusão/reabertura de tarefa carimba/limpa `data_conclusao_real`
   automaticamente, e propaga recalculo pro projeto pai.
4. "Atrasado" não é status — é status em aberto + prazo vencido, calculado
   na leitura.
5. Requisição de Alteração é o único CRUD "simples" do módulo (sem regra
   derivada) — serve de contraste para o que É regra de negócio vs. o que é
   só CRUD.
