"""Realinha `tasks.updated_at` com o evento mais recente de cada task.

`updated_at` significa "quando aconteceu a última coisa nesta task". Task cujo
evento mais novo é posterior ao próprio `updated_at` está desalinhada, e quem
usa `list_tasks` pra saber o que andou não enxerga aquela movimentação. O
script corrige essas linhas.

Uso:
    python scripts/backfill_updated_at.py           # lista o que mudaria
    python scripts/backfill_updated_at.py --apply   # grava (faz backup antes)

O banco é o mesmo da aplicação: `SYNC_AGENTS_DB` se definida, senão `sync.db`
na raiz do projeto.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("SYNC_AGENTS_DB") or BASE_DIR / "sync.db")

DESALINHADAS = """
SELECT t.id, t.code, p.slug, t.updated_at, MAX(e.created_at) AS ultimo_evento
  FROM tasks t
  JOIN events e   ON e.task_id = t.id
  JOIN projects p ON p.id = t.project_id
 GROUP BY t.id
HAVING MAX(e.created_at) > t.updated_at
 ORDER BY p.slug, t.code
"""


def backup() -> Path:
    destino = DB_PATH.with_name(f"{DB_PATH.name}.bak-backfill-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(DB_PATH, destino)
    return destino


def main() -> int:
    aplicar = "--apply" in sys.argv[1:]

    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    linhas = conn.execute(DESALINHADAS).fetchall()

    print(f"Banco: {DB_PATH}")
    if not linhas:
        print("Nenhuma task desalinhada.")
        conn.close()
        return 0

    print(f"{len(linhas)} task(s) desalinhada(s):\n")
    for linha in linhas:
        print(
            f"  {linha['slug']}/{linha['code']}: "
            f"{linha['updated_at']} -> {linha['ultimo_evento']}"
        )

    if not aplicar:
        print("\nNada gravado. Rode com --apply pra aplicar.")
        conn.close()
        return 0

    destino = backup()
    print(f"\nBackup: {destino}")
    ids = [linha["id"] for linha in linhas]
    with conn:
        conn.execute(
            f"""UPDATE tasks
                   SET updated_at = (
                         SELECT MAX(created_at) FROM events WHERE task_id = tasks.id
                       )
                 WHERE id IN ({",".join("?" for _ in ids)})""",
            ids,
        )
    restantes = conn.execute(DESALINHADAS).fetchall()
    conn.close()
    print(f"{len(ids)} task(s) atualizada(s). Restam desalinhadas: {len(restantes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
