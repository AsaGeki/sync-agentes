import sqlite3
from typing import Any

from src.modules.features.models import FeatureIn
from src.shared import codes
from src.shared.db import now
from src.shared.erros import NotFound


def find_by_code(conn: sqlite3.Connection, projeto_id: int, code: str) -> sqlite3.Row:
    """Aceita o code inteiro (`F-003-slug`) ou só o número (`F-3`, `F-003`)."""
    feature = codes.buscar_por_code(conn, "features", projeto_id, code, "F")
    if feature is None:
        raise NotFound(f"Feature '{code}' não existe neste projeto")
    return feature


def find_by_id(conn: sqlite3.Connection, feature_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM features WHERE id = ?", (feature_id,)).fetchone()


def find_all(conn: sqlite3.Connection, projeto_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM features WHERE project_id = ? ORDER BY code", (projeto_id,)
    ).fetchall()


def proximo_numero(conn: sqlite3.Connection, projeto_id: int) -> str:
    """Feature pode ser apagada, então o maior número já usado também vem do
    code guardado no `feature.deleted` - reusar o número faria o histórico da
    apagada parecer da nova."""
    vivo = codes.proximo_numero(conn, "features", projeto_id, "F")
    apagado = conn.execute(
        "SELECT MAX(CAST(SUBSTR(valor_de, 3) AS INTEGER)) AS maior FROM events"
        " WHERE project_id = ? AND kind = 'feature.deleted'",
        (projeto_id,),
    ).fetchone()["maior"]
    if apagado is None or int(vivo[2:]) > apagado:
        return vivo
    return f"F-{apagado + 1:03d}"


def insert(
    conn: sqlite3.Connection, projeto_id: int, code: str, dados: FeatureIn, created_by: int
) -> int:
    cursor = conn.execute(
        """INSERT INTO features
           (project_id, code, title, description, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (projeto_id, code, dados.title, dados.description, created_by, now(), now()),
    )
    return int(cursor.lastrowid)


def update_campo(conn: sqlite3.Connection, feature_id: int, campo: str, valor: Any) -> None:
    conn.execute(
        f"UPDATE features SET {campo} = ?, updated_at = ? WHERE id = ?",
        (valor, now(), feature_id),
    )


def delete(conn: sqlite3.Connection, feature_id: int) -> None:
    conn.execute("DELETE FROM features WHERE id = ?", (feature_id,))


def tasks_da_feature(conn: sqlite3.Connection, feature_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT code, title, status, owner_id FROM tasks WHERE feature_id = ? ORDER BY code",
        (feature_id,),
    ).fetchall()
