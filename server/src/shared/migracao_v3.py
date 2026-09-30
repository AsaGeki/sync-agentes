"""Migração 2.x -> 3.0: `authors` vira `people`, projeto ganha membership e
vínculo com repo git.

Roda uma vez, guardada pela existência de `authors` sem `people`. Fica fora de
`db.py` só por tamanho - é chamada de `iniciar_banco()` junto das outras.
"""

from __future__ import annotations

import re
import sqlite3

PROJECTS_V3 = """CREATE TABLE projects_v3 (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  slug        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL CHECK (status IN ('ativo','pausado','concluido','arquivado')),
  visibility  TEXT NOT NULL DEFAULT 'team' CHECK (visibility IN ('team','private')),
  created_by  INTEGER NOT NULL REFERENCES people(id),
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
)"""

TASKS_V3 = """CREATE TABLE tasks_v3 (
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
)"""

EVENTS_V3 = """CREATE TABLE events_v3 (
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
  base_sha   TEXT,
  arquivos   TEXT,
  created_at TEXT NOT NULL
)"""


KIND_V3 = {
    "task_criada": "task.created",
    "mensagem": "message.created",
    "campo": "task.field_changed",
    "corpo": "body.updated",
}


def _email_placeholder(nome: str, autor_id: int) -> str:
    base = re.sub(r"[^a-z0-9._-]+", "-", nome.lower()).strip("-")
    return f"{base or f'pessoa-{autor_id}'}@local.invalid"


def migrar(conn: sqlite3.Connection, tabela_existe, agora: str) -> None:
    """Converte o schema 2.x em 3.0 preservando todo o dado.

    Autor do tipo 'ia' deixa de existir como entidade: os eventos que ele
    assinou passam pro dev responsável e a ferramenta usada vira `events.agent`.
    Banco 2.x não guarda email nem token, então a pessoa nasce com email
    `<nome>@local.invalid` e sem `token_hash` - não autentica até o
    administrador emitir um token (`POST /people`, upsert por email).
    """
    if not tabela_existe(conn, "authors") or tabela_existe(conn, "people"):
        return

    conn.execute(
        """CREATE TABLE people (
             id         INTEGER PRIMARY KEY AUTOINCREMENT,
             email      TEXT NOT NULL UNIQUE,
             alias      TEXT NOT NULL,
             name       TEXT NOT NULL,
             token_hash TEXT UNIQUE,
             created_at TEXT NOT NULL
           )"""
    )
    autores = conn.execute(
        "SELECT id, type, name, responsible_id, created_at FROM authors"
    ).fetchall()
    for autor in autores:
        if autor["type"] != "dev":
            continue
        email = _email_placeholder(autor["name"], autor["id"])
        conn.execute(
            "INSERT INTO people (id, email, alias, name, token_hash, created_at)"
            " VALUES (?,?,?,?,NULL,?)",
            (
                autor["id"],
                email,
                email.split("@")[0],
                autor["name"],
                autor["created_at"],
            ),
        )

    pessoa_de: dict[int, int] = {}
    agente_de: dict[int, str] = {}
    for autor in autores:
        if autor["type"] == "dev":
            pessoa_de[autor["id"]] = autor["id"]
            agente_de[autor["id"]] = "human"
        else:
            pessoa_de[autor["id"]] = autor["responsible_id"]
            agente_de[autor["id"]] = "outro"

    conn.execute(PROJECTS_V3)
    conn.execute(
        """INSERT INTO projects_v3
             (id, slug, name, description, status, visibility, created_by, created_at, updated_at)
           SELECT id, slug, name, description, status, 'team', created_by, created_at, updated_at
             FROM projects"""
    )
    for projeto in conn.execute("SELECT id, created_by FROM projects_v3").fetchall():
        conn.execute(
            "UPDATE projects_v3 SET created_by = ? WHERE id = ?",
            (pessoa_de[projeto["created_by"]], projeto["id"]),
        )
    conn.execute("DROP TABLE projects")
    conn.execute("ALTER TABLE projects_v3 RENAME TO projects")

    # `projects.git_repositories` guardava só o nome do repo em texto - não dá pra
    # derivar root_sha dali. O vínculo nasce na primeira conexão a partir do repo.
    conn.execute(
        """CREATE TABLE project_repos (
             root_sha   TEXT PRIMARY KEY,
             project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
             name       TEXT NOT NULL,
             remote     TEXT,
             created_at TEXT NOT NULL
           )"""
    )

    # No 2.x o token era compartilhado e todo mundo alcançava tudo - a migração
    # mantém esse acesso, com quem criou o projeto como owner.
    conn.execute(
        """CREATE TABLE memberships (
             project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
             person_id  INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
             role       TEXT NOT NULL CHECK (role IN ('owner','member')),
             created_at TEXT NOT NULL,
             PRIMARY KEY (project_id, person_id)
           )"""
    )
    for projeto in conn.execute("SELECT id, created_by FROM projects").fetchall():
        for pessoa in conn.execute("SELECT id FROM people").fetchall():
            papel = "owner" if pessoa["id"] == projeto["created_by"] else "member"
            conn.execute(
                "INSERT INTO memberships (project_id, person_id, role, created_at)"
                " VALUES (?,?,?,?)",
                (projeto["id"], pessoa["id"], papel, agora),
            )

    conn.execute(TASKS_V3)
    conn.execute(
        """INSERT INTO tasks_v3
             (id, project_id, code, title, status, tags, owner_id, created_at, updated_at)
           SELECT id, project_id, code, title, status, tags, owner_id, created_at, updated_at
             FROM tasks"""
    )
    for task in conn.execute(
        "SELECT id, owner_id FROM tasks_v3 WHERE owner_id IS NOT NULL"
    ).fetchall():
        conn.execute(
            "UPDATE tasks_v3 SET owner_id = ? WHERE id = ?",
            (pessoa_de.get(task["owner_id"]), task["id"]),
        )
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_v3 RENAME TO tasks")

    conn.execute(EVENTS_V3)
    for evento in conn.execute("SELECT * FROM events ORDER BY seq").fetchall():
        conn.execute(
            """INSERT INTO events_v3
                 (seq, project_id, task_id, author_id, agent, branch, commit_sha,
                  kind, type, texto, campo, valor_de, valor_para, version, created_at)
               VALUES (?,?,?,?,?,NULL,NULL,?,?,?,?,?,?,?,?)""",
            (
                evento["seq"],
                evento["project_id"],
                evento["task_id"],
                pessoa_de[evento["author_id"]],
                agente_de[evento["author_id"]],
                KIND_V3[evento["kind"]],
                evento["type"],
                evento["texto"],
                evento["campo"],
                evento["valor_de"],
                evento["valor_para"],
                evento["version"],
                evento["created_at"],
            ),
        )
    conn.execute("DROP TABLE events")
    conn.execute("ALTER TABLE events_v3 RENAME TO events")

    conn.execute("DROP TABLE authors")
