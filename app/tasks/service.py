import difflib
import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from app.db import agora


def buscar_task(conn: sqlite3.Connection, projeto_id: int, codigo: str) -> sqlite3.Row:
    task = conn.execute(
        "SELECT * FROM tasks WHERE projeto_id = ? AND codigo = ?", (projeto_id, codigo)
    ).fetchone()
    if task is None:
        raise HTTPException(404, f"Task '{codigo}' nao existe neste projeto")
    return task


def proximo_codigo(conn: sqlite3.Connection, projeto_id: int) -> str:
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE projeto_id = ?", (projeto_id,)
    ).fetchone()["n"]
    return f"T-{total + 1:03d}"


def serializar_task(conn: sqlite3.Connection, task: sqlite3.Row) -> dict[str, Any]:
    depende = [
        r["codigo"]
        for r in conn.execute(
            """SELECT t.codigo FROM dependencias d
                 JOIN tasks t ON t.id = d.depende_de_id
                WHERE d.task_id = ? ORDER BY t.codigo""",
            (task["id"],),
        )
    ]
    bloqueia = [
        r["codigo"]
        for r in conn.execute(
            """SELECT t.codigo FROM dependencias d
                 JOIN tasks t ON t.id = d.task_id
                WHERE d.depende_de_id = ? ORDER BY t.codigo""",
            (task["id"],),
        )
    ]
    dono = None
    if task["dono_id"] is not None:
        linha = conn.execute("SELECT nome FROM autores WHERE id = ?", (task["dono_id"],)).fetchone()
        dono = linha["nome"] if linha else None
    corpo = conn.execute(
        "SELECT versao FROM corpos WHERE task_id = ? ORDER BY versao DESC LIMIT 1", (task["id"],)
    ).fetchone()
    return {
        "codigo": task["codigo"],
        "titulo": task["titulo"],
        "status": task["status"],
        "etiquetas": json.loads(task["etiquetas"]),
        "dono": dono,
        "dono_id": task["dono_id"],
        "depende": depende,
        "bloqueia": bloqueia,
        "versao_corpo": corpo["versao"] if corpo else 0,
        "criado_em": task["criado_em"],
        "atualizado_em": task["atualizado_em"],
    }


def montar_diff(antes: str, depois: str, rotulo_antes: str, rotulo_depois: str) -> str:
    linhas = difflib.unified_diff(
        antes.splitlines(keepends=True),
        depois.splitlines(keepends=True),
        fromfile=rotulo_antes,
        tofile=rotulo_depois,
        n=3,
    )
    return "".join(linhas)


def gravar_corpo(
    conn: sqlite3.Connection, task: sqlite3.Row, texto: str, autor_id: int
) -> tuple[int, str]:
    """Grava versao nova do corpo e devolve (versao, diff unificado contra a anterior)."""
    anterior = conn.execute(
        "SELECT versao, texto FROM corpos WHERE task_id = ? ORDER BY versao DESC LIMIT 1",
        (task["id"],),
    ).fetchone()
    versao = (anterior["versao"] if anterior else 0) + 1
    conn.execute(
        "INSERT INTO corpos (task_id, versao, texto, autor_id, criado_em) VALUES (?,?,?,?,?)",
        (task["id"], versao, texto, autor_id, agora()),
    )
    diff = montar_diff(
        anterior["texto"] if anterior else "",
        texto,
        f"{task['codigo']} v{anterior['versao'] if anterior else 0}",
        f"{task['codigo']} v{versao}",
    )
    return versao, diff


def diff_da_task(conn: sqlite3.Connection, task_id: int, codigo: str, desde: int) -> dict[str, Any]:
    versoes = conn.execute(
        "SELECT versao, texto FROM corpos WHERE task_id = ? ORDER BY versao", (task_id,)
    ).fetchall()
    if not versoes:
        return {"codigo": codigo, "versao_de": 0, "versao_para": 0, "diff": ""}
    antes = next((v["texto"] for v in versoes if v["versao"] == desde), "")
    ultima = versoes[-1]
    return {
        "codigo": codigo,
        "versao_de": desde,
        "versao_para": ultima["versao"],
        "diff": montar_diff(
            antes, ultima["texto"], f"{codigo} v{desde}", f"{codigo} v{ultima['versao']}"
        ),
    }
