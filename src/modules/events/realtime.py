# `autor_id` filtra o próprio eco - o agente não é notificado do que ele mesmo escreveu.

import asyncio
import json
import secrets

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from src.modules.events.bus import INSCRITOS
from src.modules.events.service import resumir
from src.modules.projects import repositorio as projetos_repositorio
from src.shared.config import TOKEN
from src.shared.db import conectar
from src.shared.erros import NotFound

router = APIRouter()


@router.websocket("/ws")
async def websocket_events(
    websocket: WebSocket,
    projeto: str,
    token: str,
    autor_id: int | None = None,
) -> None:
    if not secrets.compare_digest(token, TOKEN):
        await websocket.close(code=4401)
        return
    conn = conectar()
    try:
        projetos_repositorio.find_by_slug(conn, projeto)
    except NotFound:
        await websocket.close(code=4404)
        return
    finally:
        conn.close()

    await websocket.accept()
    fila: asyncio.Queue = asyncio.Queue(maxsize=500)
    INSCRITOS[projeto].add(fila)
    try:
        while True:
            evento = await fila.get()
            if autor_id is not None and evento.get("autor_id") == autor_id:
                continue
            await websocket.send_text(resumir(evento))
    except WebSocketDisconnect:
        pass
    finally:
        INSCRITOS[projeto].discard(fila)


@router.get("/stream")
async def sse_eventos(projeto: str, token: str, autor_id: int | None = None):
    if not secrets.compare_digest(token, TOKEN):
        raise HTTPException(401, "Token inválido")

    async def gerar():
        fila: asyncio.Queue = asyncio.Queue(maxsize=500)
        INSCRITOS[projeto].add(fila)
        try:
            while True:
                try:
                    evento = await asyncio.wait_for(fila.get(), timeout=25)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if autor_id is not None and evento.get("autor_id") == autor_id:
                    continue
                yield f"data: {json.dumps(resumir(evento), ensure_ascii=False)}\n\n"
        finally:
            INSCRITOS[projeto].discard(fila)

    return StreamingResponse(gerar(), media_type="text/event-stream")
