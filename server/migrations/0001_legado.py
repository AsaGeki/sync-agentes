# Migrações de antes do yoyo. Cada uma confere o estado do schema e só age em banco antigo,
# então em banco novo ou já migrado não faz nada.
import sqlite3

from yoyo import step

from src.shared import db, migracao_v3

__transactional__ = False


def aplicar(conn: sqlite3.Connection) -> None:
    fabrica = conn.row_factory
    conn.row_factory = sqlite3.Row
    # DROP TABLE com foreign_keys ligado apaga em cascata as tabelas filhas, e as migrações
    # recriam tabela. O PRAGMA só vale fora de transação.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        try:
            db._migrar_para_ingles(conn)
            db._migrar_humano_para_dev(conn)
            migracao_v3.migrar(conn, db._tabela_existe, db.now())
            db._migrar_repo_para_muitos_projetos(conn)
            db._migrar_events_para_features(conn)
            db._migrar_tasks_status(conn)
            db._migrar_visibilidade_publica(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("PRAGMA foreign_keys = ON")
        problemas = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problemas:
            raise RuntimeError(f"Inconsistência de FK após migração: {[dict(p) for p in problemas]}")
    finally:
        conn.row_factory = fabrica


steps = [step(aplicar)]
