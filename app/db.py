"""Schema SQLite e conexao. `sync.db` fica na raiz do projeto, WAL ligado,
`foreign_keys = ON`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "sync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS autores (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo           TEXT NOT NULL CHECK (tipo IN ('ia','humano')),
  nome           TEXT NOT NULL UNIQUE,
  responsavel_id INTEGER REFERENCES autores(id),
  criado_em      TEXT NOT NULL,
  CHECK (
    (tipo = 'ia'     AND responsavel_id IS NOT NULL) OR
    (tipo = 'humano' AND responsavel_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS projetos (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  slug          TEXT NOT NULL UNIQUE,
  nome          TEXT NOT NULL,
  descricao     TEXT,
  status        TEXT NOT NULL CHECK (status IN ('ativo','pausado','concluido','arquivado')),
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  projeto_id    INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  codigo        TEXT NOT NULL,
  titulo        TEXT NOT NULL,
  status        TEXT NOT NULL
                CHECK (status IN ('ideia','parcial','feito','bloqueado','aguardando_decisao')),
  etiquetas     TEXT NOT NULL DEFAULT '[]',
  dono_id       INTEGER REFERENCES autores(id),
  criado_em     TEXT NOT NULL,
  atualizado_em TEXT NOT NULL,
  UNIQUE (projeto_id, codigo)
);

CREATE TABLE IF NOT EXISTS dependencias (
  task_id       INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depende_de_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  PRIMARY KEY (task_id, depende_de_id),
  CHECK (task_id <> depende_de_id)
);

CREATE TABLE IF NOT EXISTS corpos (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id   INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  versao    INTEGER NOT NULL,
  texto     TEXT NOT NULL,
  autor_id  INTEGER NOT NULL REFERENCES autores(id),
  criado_em TEXT NOT NULL,
  UNIQUE (task_id, versao)
);

CREATE TABLE IF NOT EXISTS eventos (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
  task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
  autor_id   INTEGER NOT NULL REFERENCES autores(id),
  kind       TEXT NOT NULL CHECK (kind IN ('task_criada','mensagem','campo','corpo','dependencia')),
  tipo       TEXT,
  texto      TEXT,
  campo      TEXT,
  valor_de   TEXT,
  valor_para TEXT,
  versao     INTEGER,
  criado_em  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eventos_projeto ON eventos (projeto_id, seq);
CREATE INDEX IF NOT EXISTS idx_eventos_task    ON eventos (task_id, seq);
"""


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def iniciar_banco() -> None:
    conn = conectar()
    with conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    conn.close()
