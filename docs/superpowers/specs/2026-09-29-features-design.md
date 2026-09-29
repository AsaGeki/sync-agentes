# Features: hierarquia projeto → feature → task

## Objetivo

Organizar as tasks de um projeto em features, sem perder o ponto central do sync-agents: canal de alinhamento leve entre pessoas e IAs, escopo pelo repositório git, pouca cerimônia. Feature organiza, nunca trava — nenhuma regra impede criar task sem feature, mover task entre features ou fechar task por causa da feature.

Inspiração: a hierarquia `project → feature → task` do `project-tasks-mcp`. Só a organização vem de lá; claim/lease/revisão humana obrigatória/runner ficam de fora.

## Decisões

- Feature é **só agrupador**: code, título, descrição. Conversa, corpo versionado e diff continuam só na task.
- Feature na task é **opcional**. Task avulsa é caso normal.
- Status da feature é **derivado** das tasks, calculado na leitura, nunca gravado.
- Feature é entidade de primeira classe (tabela própria), com 3 tools MCP enxutas.

## 1. Modelo de dados

### Tabela `features`

```sql
CREATE TABLE IF NOT EXISTS features (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  code        TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT,
  created_by  INTEGER NOT NULL REFERENCES people(id),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  UNIQUE (project_id, code)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_features_numero
  ON features (project_id, CAST(SUBSTR(code, 3) AS INTEGER));
```

### `tasks`

Coluna nova `feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL`. Banco existente recebe via `MIGRACOES` (`ALTER TABLE tasks ADD COLUMN ...`); banco novo nasce com ela no `SCHEMA`. Tasks existentes ficam com `NULL` (avulsas).

Índice `idx_tasks_feature ON tasks (feature_id)`.

### `events`

- Coluna nova `feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL`. Evento de feature tem `feature_id` preenchido e `task_id` nulo.
- `kind` passa a aceitar também `feature.created`, `feature.field_changed`, `feature.deleted`.
- SQLite não altera `CHECK` de tabela existente: migração nova recria `events` (CREATE `events_novo` + INSERT + DROP + RENAME), guardada pela ausência de `'feature.created'` no SQL da tabela em `sqlite_master` — mesmo padrão de `_migrar_humano_para_dev`. Recria também os índices `idx_events_project`, `idx_events_task` e `idx_events_corpo_version` (o `SCHEMA` roda depois e cobre com `IF NOT EXISTS`). Roda dentro do bloco com `foreign_keys = OFF` em `iniciar_banco`, depois do backup diário.
- A coluna `feature_id` de `events` entra na própria recriação (não via `MIGRACOES`).

### Code

Formato `F-NNN-slug`, mesma regra da task (`T-NNN-slug`): número sempre acima do maior já usado, slug do título sem acento cortado em palavra inteira, busca aceitando code inteiro, `F-003` ou `F-3`. A lógica hoje em `tasks/repositorio.py` (`slug_do_titulo`, `numero_do_code`, `montar_code`, `proximo_numero`, `find_by_code`) vira helper compartilhado parametrizado pelo prefixo (`T`/`F`) e pela tabela. Criação simultânea tenta o número seguinte, como já acontece com task.

### Status derivado

Calculado a partir das tasks da feature:

| Condição | Status |
| --- | --- |
| sem task, ou todas em `ideia` | `ideia` |
| todas em `feito` | `feito` |
| alguma em `bloqueado` | `bloqueado` |
| qualquer outro caso | `parcial` |

A ordem de avaliação é a da tabela. `aguardando_decisao` cai em `parcial`. Progresso: `{feito: <n tasks feito>, total: <n tasks>}`.

### Exclusão

Só via REST (e futura tela web), sem tool MCP. Tasks da feature ficam avulsas (`ON DELETE SET NULL`). Grava evento `feature.deleted` com o code em `valor_de`, pra o histórico continuar legível mesmo com `feature_id` nulo.

## 2. Contrato

### Models pydantic

```python
class FeatureIn(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = None

class FeaturePatch(BaseModel):
    title: str | None = None
    description: str | None = None
```

- `TaskIn.feature: str | None = None` — code da feature (`F-3` ou inteiro).
- `TaskPatch.feature: str | None = None` — `""` desvincula (task vira avulsa).

Feature inexistente em `TaskIn`/`TaskPatch` responde 404 com mensagem em português.

### REST

| Método | Rota | O que faz |
| --- | --- | --- |
| POST | `/projetos/{slug}/features` | cria; grava `feature.created` |
| GET | `/projetos/{slug}/features` | lista com `status`, `progresso` e contagem por status |
| GET | `/projetos/{slug}/features/{code}` | 1 feature + lista resumida das tasks dela |
| PATCH | `/projetos/{slug}/features/{code}` | 1 `feature.field_changed` por campo que mudou |
| DELETE | `/projetos/{slug}/features/{code}` | desvincula tasks, grava `feature.deleted` |

- `GET /projetos/{slug}/tasks` ganha `feature=<code>` e `sem_feature=true`.
- Mesmas regras de acesso das tasks (`exigir_acesso`, 404 pra quem não é membro) e mesma idempotência por `X-Operation-Id` nas mutações.
- Task serializada ganha `feature: {code, title} | null` em `list_tasks`, `read_task` e no envelope de evento da task.

### Tools MCP

- `create_feature(title, description?, project?)`
- `list_features(project?)` — com status derivado e progresso
- `update_feature(code, title?, description?, project?)`
- `create_task(..., feature?)`
- `update_task(..., feature?)` — `""` desvincula
- `list_tasks(..., feature?, sem_feature?)`

`instructions` do MCP ganha parágrafo curto no bloco MODELO: feature agrupa tasks, é opcional, criar task sem feature é normal, nada trava por causa de feature.

### Eventos

- `feature.created`, `feature.field_changed`, `feature.deleted` aparecem em `read_changes`, no relatório e no SSE, com `resumo` de uma linha (ex.: "Fulano criou F-003-login-sso").
- Não entram em `nao_lidos` (marca d'água é por task).
- Mover task de feature = `task.field_changed` com `campo='feature'`, `valor_de`/`valor_para` com o code das features (nulo quando avulsa). Entra no não lido da task normalmente.

## 3. Relatório, docs, verificação

### Relatório

- Markdown: "Resumo geral" ganha 1 linha por feature (`F-003-login-sso · parcial · 3/5 feito`); seções de task agrupadas por feature (`## F-003 · Login SSO`), grupo "Sem feature" no fim; eventos `feature.*` da janela como linha curta no topo do grupo.
- JSON: cada task carrega `feature`; entra lista `features` com status e progresso.

### Docs e coleção

- Bruno: pasta `Features` (Create, Find All, Find One, Update, Delete) e filtro `feature` em Tasks/Find All.
- `CONECTAR_MCP.md`: modelo de dados com feature.
- `CHANGELOG.md` e `FastAPI(version=...)`: **3.1.0** (aditivo, sem breaking).

### Verificação

Sem arquivo de teste novo.

1. Copiar `sync.db` pro scratchpad; subir servidor com `SYNC_AGENTS_DB` apontando pra cópia.
2. Migração roda limpa (`foreign_key_check` vazio), contagem de tasks e events igual à de antes.
3. Smoke REST: criar feature, criar task nela, mover pra outra, desvincular, conferir status derivado e progresso, apagar feature e ver tasks avulsas, conferir eventos em `/mudancas`.
4. Conferir `read_report` em markdown e JSON.

O `sync.db` real não é tocado; a migração dele roda no próximo start, depois do backup diário.

## Fora deste spec

Tela web: sub-projeto separado, brainstorm próprio depois deste.
