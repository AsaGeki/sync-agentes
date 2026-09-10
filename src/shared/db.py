"""Schema SQLite e conexão. `sync.db` fica na raiz do projeto, WAL ligado,
`foreign_keys = ON`.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from src.shared import migracao_v3

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# SYNC_AGENTS_DB troca o arquivo do banco, pra rodar contra um descartável.
DB_PATH = Path(os.environ.get("SYNC_AGENTS_DB") or BASE_DIR / "sync.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  email      TEXT NOT NULL UNIQUE,
  alias      TEXT NOT NULL,
  name       TEXT NOT NULL,
  token_hash TEXT UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL CHECK (status IN ('ativo','pausado','concluido','arquivado')),
  visibility  TEXT NOT NULL DEFAULT 'team' CHECK (visibility IN ('team','private')),
  created_by  INTEGER NOT NULL REFERENCES people(id),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- Vinculo repo git -> projeto. `root_sha` (sha do commit raiz) e a chave: e igual
-- em todo clone, sobrevive a rename de pasta e a troca de remote. Um projeto pode
-- ter varios repos (frontend + backend no mesmo canal); um repo pertence a 1 projeto.
CREATE TABLE IF NOT EXISTS project_repos (
  root_sha   TEXT PRIMARY KEY,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name       TEXT NOT NULL,
  remote     TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  person_id  INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('owner','member')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (project_id, person_id)
);

-- Pedido de acesso a projeto `private`. `team` não passa por aqui - entra
-- sozinho direto em `memberships`.
CREATE TABLE IF NOT EXISTS membership_requests (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','rejected')),
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  code       TEXT NOT NULL,
  title      TEXT NOT NULL,
  status     TEXT NOT NULL
             CHECK (status IN ('ideia','parcial','feito','bloqueado','aguardando_decisao')),
  tags       TEXT NOT NULL DEFAULT '[]',
  owner_id   INTEGER REFERENCES people(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (project_id, code)
);

CREATE TABLE IF NOT EXISTS events (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  author_id  INTEGER NOT NULL REFERENCES people(id),
  agent      TEXT NOT NULL DEFAULT 'outro'
             CHECK (agent IN ('claude','codex','human','outro')),
  branch     TEXT,
  commit_sha TEXT,
  kind       TEXT NOT NULL CHECK (kind IN (
               'task.created','task.field_changed','body.updated',
               'message.created','diff.published')),
  type       TEXT,
  texto      TEXT,
  campo      TEXT,
  valor_de   TEXT,
  valor_para TEXT,
  version    INTEGER,
  -- Só em diff.published: `commit_sha` é o head do diff, `base_sha` a base, e
  -- `arquivos` a lista de caminhos tocados (json).
  base_sha   TEXT,
  arquivos   TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_project ON events (project_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_task    ON events (task_id, seq);
CREATE INDEX IF NOT EXISTS idx_repos_project  ON project_repos (project_id);

-- Garante 1 corpo por versao por task.
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_corpo_version
  ON events (task_id, version) WHERE kind = 'body.updated';

CREATE TABLE IF NOT EXISTS schema_migrations (
  id          TEXT PRIMARY KEY,
  aplicada_em TEXT NOT NULL
);
"""

# Mudou modelagem (coluna nova numa tabela existente)? `CREATE TABLE IF NOT EXISTS`
# acima não alcança banco já criado - ele pula a tabela inteira. Adicione aqui:
# (id único e permanente, tabela, coluna, "ALTER TABLE ... ADD COLUMN ...").
# Bancos novos já nascem com a coluna via SCHEMA (adicione lá também) - a checagem
# de coluna existente abaixo garante que a migração não tenta duplicar.
MIGRACOES: list[tuple[str, str, str, str]] = []


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _tabela_existe(conn: sqlite3.Connection, tabela: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabela,)
        ).fetchone()
        is not None
    )


def _coluna_existe(conn: sqlite3.Connection, tabela: str, coluna: str) -> bool:
    linhas = conn.execute(f"PRAGMA table_info({tabela})").fetchall()
    return any(linha["name"] == coluna for linha in linhas)


def _migrar_para_ingles(conn: sqlite3.Connection) -> None:
    """Migração única: renomeia tabela/coluna estrutural pro inglês (mantém
    `texto`/`campo`/`valor_de`/`valor_para` em português - são conteúdo livre,
    não estrutura), funde `corpos` em `events` (evento kind='corpo' passa a
    carregar o texto direto em `texto`) e remove `dependencias`. Só roda se o
    banco ainda tiver o schema antigo - auto-guardada pela existência da
    tabela `autores`, idempotente sem precisar de registro em
    `schema_migrations` (schema_migrations só existe depois que SCHEMA roda,
    e isto tem que rodar antes do SCHEMA).
    """
    if not _tabela_existe(conn, "autores"):
        return

    conn.execute("ALTER TABLE autores RENAME TO authors")
    conn.execute("ALTER TABLE authors RENAME COLUMN tipo TO type")
    conn.execute("ALTER TABLE authors RENAME COLUMN nome TO name")
    conn.execute("ALTER TABLE authors RENAME COLUMN responsavel_id TO responsible_id")
    conn.execute("ALTER TABLE authors RENAME COLUMN criado_em TO created_at")

    conn.execute("ALTER TABLE projetos RENAME TO projects")
    conn.execute("ALTER TABLE projects RENAME COLUMN nome TO name")
    conn.execute("ALTER TABLE projects RENAME COLUMN descricao TO description")
    conn.execute("ALTER TABLE projects RENAME COLUMN criado_em TO created_at")
    conn.execute("ALTER TABLE projects RENAME COLUMN atualizado_em TO updated_at")

    # git_repositories/created_by são colunas novas - `created_by NOT NULL REFERENCES`
    # não dá pra ADD COLUMN direto (SQLite proíbe REFERENCES com default não-nulo em
    # ALTER TABLE ADD COLUMN), então reconstrói a tabela já com a forma final.
    # Banco existente não tem como saber quem criou projeto já existente - preenche
    # com o primeiro autor humano cadastrado, nunca com uma IA (IA não responde por si).
    primeiro_humano = conn.execute(
        "SELECT id FROM authors WHERE type = 'humano' ORDER BY id LIMIT 1"
    ).fetchone()
    if primeiro_humano is None:
        raise RuntimeError(
            "Migração de projects precisa de 1 autor humano existente pra preencher "
            "created_by dos projetos já cadastrados - nenhum encontrado."
        )
    conn.execute(
        """CREATE TABLE projects_novo (
             id               INTEGER PRIMARY KEY AUTOINCREMENT,
             slug             TEXT NOT NULL UNIQUE,
             name             TEXT NOT NULL,
             description      TEXT,
             git_repositories TEXT NOT NULL DEFAULT '[]',
             status           TEXT NOT NULL
                              CHECK (status IN ('ativo','pausado','concluido','arquivado')),
             created_by       INTEGER NOT NULL REFERENCES authors(id),
             created_at       TEXT NOT NULL,
             updated_at       TEXT NOT NULL
           )"""
    )
    conn.execute(
        """INSERT INTO projects_novo
               (id, slug, name, description, status, created_by, created_at, updated_at)
           SELECT id, slug, name, description, status, ?, created_at, updated_at
             FROM projects""",
        (primeiro_humano["id"],),
    )
    conn.execute("DROP TABLE projects")
    conn.execute("ALTER TABLE projects_novo RENAME TO projects")

    conn.execute("ALTER TABLE tasks RENAME COLUMN projeto_id TO project_id")
    conn.execute("ALTER TABLE tasks RENAME COLUMN codigo TO code")
    conn.execute("ALTER TABLE tasks RENAME COLUMN titulo TO title")
    conn.execute("ALTER TABLE tasks RENAME COLUMN etiquetas TO tags")
    conn.execute("ALTER TABLE tasks RENAME COLUMN dono_id TO owner_id")
    conn.execute("ALTER TABLE tasks RENAME COLUMN criado_em TO created_at")
    conn.execute("ALTER TABLE tasks RENAME COLUMN atualizado_em TO updated_at")

    conn.execute("ALTER TABLE eventos RENAME TO events")
    conn.execute("ALTER TABLE events RENAME COLUMN projeto_id TO project_id")
    conn.execute("ALTER TABLE events RENAME COLUMN autor_id TO author_id")
    conn.execute("ALTER TABLE events RENAME COLUMN tipo TO type")
    conn.execute("ALTER TABLE events RENAME COLUMN versao TO version")
    conn.execute("ALTER TABLE events RENAME COLUMN criado_em TO created_at")

    # corpos -> events: cada linha de `corpos` casa 1:1 com o evento kind='corpo'
    # do mesmo task_id+version (gravar_corpo()+registrar_evento() escrevem as
    # duas linhas juntas, na mesma transação) - só falta copiar o texto.
    conn.execute(
        """UPDATE events
              SET texto = (
                SELECT texto FROM corpos
                 WHERE corpos.task_id = events.task_id
                   AND corpos.versao = events.version
              )
            WHERE kind = 'corpo'"""
    )
    conn.execute("DROP TABLE corpos")
    conn.execute("DROP TABLE dependencias")
    conn.execute("DELETE FROM events WHERE kind = 'dependencia'")

    # 'dependencia' sai do CHECK de kind e o UNIQUE parcial de corpo entra -
    # SQLite não altera CHECK/index de tabela existente com ALTER TABLE, único
    # jeito é recriar a tabela.
    conn.execute(
        """CREATE TABLE events_novo (
             seq        INTEGER PRIMARY KEY AUTOINCREMENT,
             project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
             task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
             author_id  INTEGER NOT NULL REFERENCES authors(id),
             kind       TEXT NOT NULL CHECK (kind IN ('task_criada','mensagem','campo','corpo')),
             type       TEXT,
             texto      TEXT,
             campo      TEXT,
             valor_de   TEXT,
             valor_para TEXT,
             version    INTEGER,
             created_at TEXT NOT NULL
           )"""
    )
    conn.execute(
        """INSERT INTO events_novo
           SELECT seq, project_id, task_id, author_id, kind, type, texto, campo,
                  valor_de, valor_para, version, created_at
             FROM events"""
    )
    conn.execute("DROP TABLE events")
    conn.execute("ALTER TABLE events_novo RENAME TO events")


def _authors_tem_check_antigo(conn: sqlite3.Connection) -> bool:
    linha = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'authors'"
    ).fetchone()
    return linha is not None and "'humano'" in linha["sql"]


def _migrar_humano_para_dev(conn: sqlite3.Connection) -> None:
    """Migração única: authors.type usa 'dev' no lugar de 'humano'. Guardada
    pelo texto do CHECK (não por contagem de linha - tabela sem nenhum autor
    'humano' ainda tem o CHECK antigo se nunca foi reconstruída) porque
    SQLite não altera CHECK de tabela existente com ALTER TABLE.
    """
    if not _authors_tem_check_antigo(conn):
        return

    conn.execute(
        """CREATE TABLE authors_novo (
             id             INTEGER PRIMARY KEY AUTOINCREMENT,
             type           TEXT NOT NULL CHECK (type IN ('ia','dev')),
             name           TEXT NOT NULL UNIQUE,
             responsible_id INTEGER REFERENCES authors_novo(id),
             created_at     TEXT NOT NULL,
             CHECK (
               (type = 'ia'  AND responsible_id IS NOT NULL) OR
               (type = 'dev' AND responsible_id IS NULL)
             )
           )"""
    )
    conn.execute(
        """INSERT INTO authors_novo (id, type, name, responsible_id, created_at)
           SELECT id, CASE WHEN type = 'humano' THEN 'dev' ELSE type END,
                  name, responsible_id, created_at
             FROM authors"""
    )
    conn.execute("DROP TABLE authors")
    conn.execute("ALTER TABLE authors_novo RENAME TO authors")


def _backup_antes_de_migrar() -> None:
    """Cópia do banco antes das migrações, que fazem DROP TABLE. Uma por dia."""
    if not DB_PATH.exists():
        return
    destino = DB_PATH.with_name(f"{DB_PATH.name}.bak-{datetime.now():%Y%m%d}")
    if not destino.exists():
        shutil.copy2(DB_PATH, destino)


def iniciar_banco() -> None:
    _backup_antes_de_migrar()
    conn = conectar()

    # DROP TABLE com foreign_keys=ON dispara DELETE implícito em cascata nas
    # tabelas filhas (documentado no próprio SQLite) - a migração recria
    # tabela (DROP + rename), então teria apagado tasks/events junto ao
    # recriar projects. PRAGMA foreign_keys só tem efeito fora de transação,
    # por isso roda antes do `with conn` (que abre a transação principal).
    conn.execute("PRAGMA foreign_keys = OFF")
    with conn:
        _migrar_para_ingles(conn)
        _migrar_humano_para_dev(conn)
        migracao_v3.migrar(conn, _tabela_existe, now())
    conn.execute("PRAGMA foreign_keys = ON")
    problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problemas:
        raise RuntimeError(f"Inconsistência de FK após migração: {[dict(p) for p in problemas]}")

    with conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)

        aplicadas = {row["id"] for row in conn.execute("SELECT id FROM schema_migrations")}
        for id_, tabela, coluna, sql in MIGRACOES:
            if id_ in aplicadas:
                continue
            if not _coluna_existe(conn, tabela, coluna):
                conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (id, aplicada_em) VALUES (?, ?)",
                (id_, now()),
            )
    conn.close()
