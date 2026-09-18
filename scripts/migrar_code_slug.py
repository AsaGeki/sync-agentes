"""Passa os codes de task pro formato `T-007-slug-do-titulo`.

O número continua sendo a identidade da task (e resolve sozinho em qualquer
tool); o slug atrás dele existe pra quem lê reconhecer a task sem abrir. Task
que já está no formato novo fica como está.

Uso:
    python scripts/migrar_code_slug.py           # lista o que mudaria
    python scripts/migrar_code_slug.py --apply   # grava (faz backup antes)

O banco é o mesmo da aplicação: `SYNC_AGENTS_DB` se definida, senão `sync.db`
na raiz do projeto.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

from src.modules.tasks.repositorio import montar_code, numero_do_code
from src.shared.db import DB_PATH


def backup() -> str:
    destino = DB_PATH.with_name(f"{DB_PATH.name}.bak-code-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(DB_PATH, destino)
    return str(destino)


def main() -> int:
    aplicar = "--apply" in sys.argv[1:]

    if not DB_PATH.exists():
        print(f"Banco não encontrado: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    linhas = conn.execute(
        """SELECT t.id, t.code, t.title, p.slug AS projeto
             FROM tasks t JOIN projects p ON p.id = t.project_id
            ORDER BY p.slug, t.code"""
    ).fetchall()

    renomear: list[tuple[int, str, str, str]] = []
    sem_numero: list[sqlite3.Row] = []
    for linha in linhas:
        numero = numero_do_code(linha["code"])
        if numero is None:
            sem_numero.append(linha)
            continue
        novo = montar_code(numero, linha["title"])
        if novo != linha["code"]:
            renomear.append((linha["id"], linha["projeto"], linha["code"], novo))

    print(f"Banco: {DB_PATH}")
    if sem_numero:
        print(f"\n{len(sem_numero)} task(s) com code fora do padrão T-N, ignoradas:")
        for linha in sem_numero:
            print(f"  {linha['projeto']}/{linha['code']}")

    if not renomear:
        print("\nNenhum code a mudar.")
        conn.close()
        return 0

    print(f"\n{len(renomear)} code(s) a mudar:\n")
    for _, projeto, antigo, novo in renomear:
        print(f"  {projeto}: {antigo} -> {novo}")

    if not aplicar:
        print("\nNada gravado. Rode com --apply pra aplicar.")
        conn.close()
        return 0

    destino = backup()
    print(f"\nBackup: {destino}")
    # `updated_at` fica como está: renomear o code não é atividade na task.
    with conn:
        conn.executemany(
            "UPDATE tasks SET code = ? WHERE id = ?",
            [(novo, task_id) for task_id, _, _, novo in renomear],
        )
    conn.close()
    print(f"{len(renomear)} code(s) atualizado(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
