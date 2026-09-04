import asyncio
import json
import secrets

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.auth import CONFIG
from app.db import conectar
from app.eventos.bus import INSCRITOS
from app.eventos.service import resumir_evento

router = APIRouter()


@router.websocket("/ws")
async def websocket_eventos(
    websocket: WebSocket,
    projeto: str,
    token: str,
    autor_id: int | None = None,
) -> None:
    if not secrets.compare_digest(token, CONFIG["token"]):
        await websocket.close(code=4401)
        return
    conn = conectar()
    try:
        existe = conn.execute("SELECT 1 FROM projetos WHERE slug = ?", (projeto,)).fetchone()
    finally:
        conn.close()
    if existe is None:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    fila: asyncio.Queue = asyncio.Queue(maxsize=500)
    INSCRITOS[projeto].add(fila)
    try:
        while True:
            evento = await fila.get()
            # autor_id filtra o proprio eco: o agente nao e notificado do que ele mesmo escreveu.
            if autor_id is not None and evento.get("autor_id") == autor_id:
                continue
            await websocket.send_text(resumir_evento(evento))
    except WebSocketDisconnect:
        pass
    finally:
        INSCRITOS[projeto].discard(fila)


@router.get("/stream")
async def sse_eventos(projeto: str, token: str, autor_id: int | None = None):
    if not secrets.compare_digest(token, CONFIG["token"]):
        raise HTTPException(401, "Token invalido")

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
                yield f"data: {json.dumps(resumir_evento(evento), ensure_ascii=False)}\n\n"
        finally:
            INSCRITOS[projeto].discard(fila)

    return StreamingResponse(gerar(), media_type="text/event-stream")
