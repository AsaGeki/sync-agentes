import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import autor_atual, exigir_token
from app.db import agora, conectar
from app.enums import EKindEvento, EStatusTask
from app.eventos.bus import publicar
from app.eventos.service import hidratar_evento, registrar_evento
from app.projetos.service import buscar_projeto
from app.tasks.models import CorpoIn, DependenciaIn, MensagemIn, TaskIn, TaskPatch
from app.tasks.service import (
    buscar_task,
    diff_da_task,
    gravar_corpo,
    proximo_codigo,
    serializar_task,
)

router = APIRouter()


# ---------- tasks ---------- #


@router.post("/projetos/{slug}/tasks", status_code=201, dependencies=[Depends(exigir_token)])
async def criar_task(
    slug: str, dados: TaskIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        codigo = dados.codigo or proximo_codigo(conn, projeto["id"])
        try:
            with conn:
                cursor = conn.execute(
                    """INSERT INTO tasks
                       (projeto_id, codigo, titulo, status, etiquetas,
                        dono_id, criado_em, atualizado_em)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        projeto["id"],
                        codigo,
                        dados.titulo,
                        dados.status.value,
                        json.dumps(dados.etiquetas, ensure_ascii=False),
                        dados.dono_id,
                        agora(),
                        agora(),
                    ),
                )
                task_id = int(cursor.lastrowid)
                seq = registrar_evento(
                    conn,
                    projeto_id=projeto["id"],
                    task_id=task_id,
                    autor_id=autor["id"],
                    kind=EKindEvento.task_criada.value,
                    texto=dados.titulo,
                )
                task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
                if dados.corpo is not None:
                    versao, _ = gravar_corpo(conn, task, dados.corpo, autor["id"])
                    registrar_evento(
                        conn,
                        projeto_id=projeto["id"],
                        task_id=task_id,
                        autor_id=autor["id"],
                        kind=EKindEvento.corpo.value,
                        versao=versao,
                    )
        except sqlite3.IntegrityError:
            raise HTTPException(409, f"Task '{codigo}' ja existe neste projeto") from None
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, **serializar_task(conn, task)}
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks", dependencies=[Depends(exigir_token)])
def listar_tasks(
    slug: str,
    status: EStatusTask | None = None,
    etiqueta: str | None = None,
) -> list[dict[str, Any]]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        sql = "SELECT * FROM tasks WHERE projeto_id = ?"
        params: list[Any] = [projeto["id"]]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        sql += " ORDER BY codigo"
        tasks = [serializar_task(conn, t) for t in conn.execute(sql, params)]
        if etiqueta is not None:
            tasks = [t for t in tasks if etiqueta in t["etiquetas"]]
        return tasks
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{codigo}", dependencies=[Depends(exigir_token)])
def ler_task(slug: str, codigo: str, com_corpo: bool = True) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        dados = serializar_task(conn, task)
        if com_corpo:
            corpo = conn.execute(
                "SELECT versao, texto FROM corpos WHERE task_id = ? ORDER BY versao DESC LIMIT 1",
                (task["id"],),
            ).fetchone()
            dados["corpo"] = corpo["texto"] if corpo else None
        dados["eventos"] = [
            hidratar_evento(conn, r["seq"])
            for r in conn.execute(
                "SELECT seq FROM eventos WHERE task_id = ? ORDER BY seq", (task["id"],)
            )
        ]
        return dados
    finally:
        conn.close()


@router.patch("/projetos/{slug}/tasks/{codigo}", dependencies=[Depends(exigir_token)])
async def atualizar_task(
    slug: str, codigo: str, dados: TaskPatch, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        mudancas = dados.model_dump(mode="json", exclude_none=True)
        if not mudancas:
            raise HTTPException(422, "Nada pra atualizar")
        sequencias: list[int] = []
        with conn:
            for campo, valor in mudancas.items():
                antes = task[campo]
                novo = json.dumps(valor, ensure_ascii=False) if campo == "etiquetas" else valor
                if str(antes) == str(novo):
                    continue
                conn.execute(f"UPDATE tasks SET {campo} = ? WHERE id = ?", (novo, task["id"]))
                sequencias.append(
                    registrar_evento(
                        conn,
                        projeto_id=projeto["id"],
                        task_id=task["id"],
                        autor_id=autor["id"],
                        kind=EKindEvento.campo.value,
                        campo=campo,
                        valor_de=None if antes is None else str(antes),
                        valor_para=None if novo is None else str(novo),
                    )
                )
            conn.execute("UPDATE tasks SET atualizado_em = ? WHERE id = ?", (agora(), task["id"]))
        for seq in sequencias:
            await publicar(slug, hidratar_evento(conn, seq))
        atual = buscar_task(conn, projeto["id"], codigo)
        return {"cursor": sequencias[-1] if sequencias else None, **serializar_task(conn, atual)}
    finally:
        conn.close()


@router.post(
    "/projetos/{slug}/tasks/{codigo}/dependencias",
    status_code=201,
    dependencies=[Depends(exigir_token)],
)
async def criar_dependencia(
    slug: str, codigo: str, dados: DependenciaIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        alvo = buscar_task(conn, projeto["id"], dados.depende_de)
        if task["id"] == alvo["id"]:
            raise HTTPException(422, "Task nao pode depender de si mesma")
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO dependencias (task_id, depende_de_id) VALUES (?,?)",
                (task["id"], alvo["id"]),
            )
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.dependencia.value,
                valor_para=alvo["codigo"],
            )
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, **serializar_task(conn, task)}
    finally:
        conn.close()


# ---------- conversa ---------- #


@router.post(
    "/projetos/{slug}/tasks/{codigo}/mensagens",
    status_code=201,
    dependencies=[Depends(exigir_token)],
)
async def criar_mensagem(
    slug: str, codigo: str, dados: MensagemIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        with conn:
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.mensagem.value,
                tipo=dados.tipo.value,
                texto=dados.texto,
            )
        evento = hidratar_evento(conn, seq)
        await publicar(slug, evento)
        return {"cursor": seq, **evento}
    finally:
        conn.close()


@router.put("/projetos/{slug}/tasks/{codigo}/corpo", dependencies=[Depends(exigir_token)])
async def atualizar_corpo(
    slug: str, codigo: str, dados: CorpoIn, autor: sqlite3.Row = Depends(autor_atual)
) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        with conn:
            versao, diff = gravar_corpo(conn, task, dados.texto, autor["id"])
            seq = registrar_evento(
                conn,
                projeto_id=projeto["id"],
                task_id=task["id"],
                autor_id=autor["id"],
                kind=EKindEvento.corpo.value,
                versao=versao,
            )
        await publicar(slug, hidratar_evento(conn, seq))
        return {"cursor": seq, "codigo": codigo, "versao": versao, "diff": diff}
    finally:
        conn.close()


@router.get("/projetos/{slug}/tasks/{codigo}/diff", dependencies=[Depends(exigir_token)])
def ler_diff(slug: str, codigo: str, desde: int = Query(0, ge=0)) -> dict[str, Any]:
    conn = conectar()
    try:
        projeto = buscar_projeto(conn, slug)
        task = buscar_task(conn, projeto["id"], codigo)
        return diff_da_task(conn, task["id"], codigo, desde)
    finally:
        conn.close()
