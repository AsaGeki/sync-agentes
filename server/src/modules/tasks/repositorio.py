# Corpo versionado não tem tabela própria - é evento kind='body.updated' em `events`
# (ver ultimo_corpo/todos_corpos). find_by_code também é usado por outros domínios.

import json
import sqlite3
from typing import Any

from src.modules.tasks.models import TaskIn
from src.shared import codes
from src.shared.db import now
from src.shared.enums import EStatusTask
from src.shared.erros import NotFound


def numero_do_code(code: str) -> str | None:
    return codes.numero_do_code(code, "T")


def find_by_code(conn: sqlite3.Connection, projeto_id: int, code: str) -> sqlite3.Row:
    """Aceita o code inteiro (`T-007-slug`) ou só o número (`T-7`, `T-007`)."""
    task = codes.buscar_por_code(conn, "tasks", projeto_id, code, "T")
    if task is None:
        raise NotFound(f"Task '{code}' não existe neste projeto")
    return task


def find_by_id(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def proximo_numero(conn: sqlite3.Connection, projeto_id: int) -> str:
    return codes.proximo_numero(conn, "tasks", projeto_id, "T")


def insert(
    conn: sqlite3.Connection, projeto_id: int, code: str, dados: TaskIn, feature_id: int | None
) -> int:
    cursor = conn.execute(
        """INSERT INTO tasks
           (project_id, code, title, status, tags, owner_id, feature_id, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            projeto_id,
            code,
            dados.title,
            dados.status.value,
            json.dumps(dados.tags, ensure_ascii=False),
            dados.owner_id,
            feature_id,
            now(),
            now(),
        ),
    )
    return int(cursor.lastrowid)


def find_all(
    conn: sqlite3.Connection,
    projeto_id: int,
    status: EStatusTask | None,
    feature_id: int | None = None,
    sem_feature: bool = False,
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM tasks WHERE project_id = ?"
    params: list[Any] = [projeto_id]
    if status is not None:
        sql += " AND status = ?"
        params.append(status.value)
    if feature_id is not None:
        sql += " AND feature_id = ?"
        params.append(feature_id)
    if sem_feature:
        sql += " AND feature_id IS NULL"
    sql += " ORDER BY code"
    return conn.execute(sql, params).fetchall()


def ids_que_casam(conn: sqlite3.Connection, projeto_id: int, termo: str) -> set[int]:
    """Tasks cujo code, título ou corpo contém `termo`."""
    like = f"%{termo}%"
    linhas = conn.execute(
        """SELECT t.id FROM tasks t
            WHERE t.project_id = ?
              AND (t.code LIKE ? OR t.title LIKE ?
                   OR EXISTS (SELECT 1 FROM events e
                               WHERE e.task_id = t.id
                                 AND e.kind = 'body.updated'
                                 AND e.texto LIKE ?))""",
        (projeto_id, like, like, like),
    )
    return {linha["id"] for linha in linhas}


def update_campo(conn: sqlite3.Connection, task_id: int, campo: str, valor: Any) -> None:
    conn.execute(f"UPDATE tasks SET {campo} = ? WHERE id = ?", (valor, task_id))


def owner_name(conn: sqlite3.Connection, owner_id: int | None) -> str | None:
    if owner_id is None:
        return None
    linha = conn.execute("SELECT name FROM people WHERE id = ?", (owner_id,)).fetchone()
    return linha["name"] if linha else None


def ultimo_corpo(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """SELECT version, texto FROM events
            WHERE task_id = ? AND kind = 'body.updated' ORDER BY version DESC LIMIT 1""",
        (task_id,),
    ).fetchone()


def quem_esta_fazendo(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    """Último evento que pôs a task em 'em_andamento': a mudança de status ou,
    se ela já nasceu assim, o `task.created`."""
    return conn.execute(
        """SELECT e.created_at, e.agent, pe.alias, pe.name
             FROM events e JOIN people pe ON pe.id = e.author_id
            WHERE e.task_id = ?
              AND ((e.kind = 'task.field_changed' AND e.campo = 'status'
                    AND e.valor_para = 'em_andamento')
                   OR e.kind = 'task.created')
            ORDER BY e.seq DESC LIMIT 1""",
        (task_id,),
    ).fetchone()


def seqs_de_diff(conn: sqlite3.Connection, task_id: int) -> list[int]:
    return [
        linha["seq"]
        for linha in conn.execute(
            """SELECT seq FROM events
                WHERE task_id = ? AND kind = 'diff.published' ORDER BY seq""",
            (task_id,),
        )
    ]


def todos_corpos(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT version, texto FROM events
            WHERE task_id = ? AND kind = 'body.updated' ORDER BY version""",
        (task_id,),
    ).fetchall()


# ---------- dependências ---------- #


def insert_dependencies(conn: sqlite3.Connection, task_id: int, depends_on_ids: list[int]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_id, created_at)"
        " VALUES (?,?,?)",
        [(task_id, depends_on_id, now()) for depends_on_id in depends_on_ids],
    )


def delete_dependencies(conn: sqlite3.Connection, task_id: int) -> None:
    conn.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task_id,))


def dependencies(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    """As tasks que esta depende, com code e status atual de cada uma."""
    return conn.execute(
        """SELECT t.id, t.code, t.status FROM task_dependencies td
             JOIN tasks t ON t.id = td.depends_on_id
            WHERE td.task_id = ? ORDER BY t.code""",
        (task_id,),
    ).fetchall()


def dependentes(conn: sqlite3.Connection, task_id: int) -> list[sqlite3.Row]:
    """As tasks que dependem desta."""
    return conn.execute(
        """SELECT t.id, t.code, t.status FROM task_dependencies td
             JOIN tasks t ON t.id = td.task_id
            WHERE td.depends_on_id = ? ORDER BY t.code""",
        (task_id,),
    ).fetchall()


def alcanca(conn: sqlite3.Connection, origem_id: int, alvo_id: int) -> bool:
    """Caminha o grafo de dependências a partir de `origem_id` procurando
    `alvo_id`. É o que barra ciclo antes de gravar."""
    vistos: set[int] = set()
    fila = [origem_id]
    while fila:
        atual = fila.pop()
        if atual == alvo_id:
            return True
        if atual in vistos:
            continue
        vistos.add(atual)
        fila += [
            linha["depends_on_id"]
            for linha in conn.execute(
                "SELECT depends_on_id FROM task_dependencies WHERE task_id = ?", (atual,)
            )
        ]
    return False


# ---------- leitura ---------- #


def ultimo_seq(conn: sqlite3.Connection, task_id: int) -> int:
    linha = conn.execute(
        "SELECT MAX(seq) AS ultimo FROM events WHERE task_id = ?", (task_id,)
    ).fetchone()
    return int(linha["ultimo"] or 0)


def marcar_lida(conn: sqlite3.Connection, task_id: int, person_id: int, seq: int) -> None:
    """A marca só anda pra frente - releitura de trecho antigo não desmarca o
    que já tinha sido visto."""
    conn.execute(
        """INSERT INTO task_reads (task_id, person_id, last_read_seq, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT (task_id, person_id)
           DO UPDATE SET last_read_seq = MAX(last_read_seq, excluded.last_read_seq),
                         updated_at = excluded.updated_at""",
        (task_id, person_id, seq, now()),
    )


def leitura_do_projeto(
    conn: sqlite3.Connection, projeto_id: int, person_id: int
) -> dict[int, dict[str, int]]:
    """Por task: quantos eventos de outras pessoas estão acima da marca de
    leitura desta pessoa, e o seq do mais recente deles. O próprio eco não
    conta como não lido."""
    linhas = conn.execute(
        """SELECT t.id         AS task_id,
                  COUNT(e.seq) AS nao_lidos,
                  MAX(e.seq)   AS ultimo_nao_lido
             FROM tasks t
             LEFT JOIN events e
                    ON e.task_id = t.id
                   AND e.author_id != ?
                   AND e.seq > COALESCE(
                         (SELECT last_read_seq FROM task_reads
                           WHERE task_id = t.id AND person_id = ?), 0)
            WHERE t.project_id = ?
            GROUP BY t.id""",
        (person_id, person_id, projeto_id),
    )
    return {
        linha["task_id"]: {
            "nao_lidos": int(linha["nao_lidos"]),
            "ultimo_nao_lido": int(linha["ultimo_nao_lido"] or 0),
        }
        for linha in linhas
    }
