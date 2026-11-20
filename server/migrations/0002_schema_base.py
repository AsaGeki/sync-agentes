# Schema completo do sistema. Em banco existente é quase todo no-op (`IF NOT EXISTS`);
# o que falta é a coluna `tasks.feature_id`, que o `CREATE TABLE` não alcança.
import sqlite3

from yoyo import step

from src.shared import db

__transactional__ = False


def aplicar(conn: sqlite3.Connection) -> None:
    conn.executescript(db.SCHEMA)
    colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(tasks)")}
    conn.execute("BEGIN")
    if "feature_id" not in colunas:
        conn.execute("ALTER TABLE tasks ADD COLUMN feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_feature ON tasks (feature_id)")
    conn.execute("COMMIT")


steps = [step(aplicar)]
