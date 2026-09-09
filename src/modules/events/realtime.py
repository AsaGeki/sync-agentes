"""Entrega em tempo real do que o outro lado escreveu (WebSocket + SSE, fallback).

O frame é o mesmo envelope de evento que `/mudancas` devolve - quem consome os
dois não tem dois formatos pra tratar.

Autenticação é a mesma do REST: token pessoal. O WebSocket aceita `Authorization`
como header (é o que o bridge usa) ou `?token=` na query, pra cliente que não
consegue mandar header. Quem não é membro do projeto não conecta.
"""

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from src.modules.events.bus import INSCRITOS
from src.modules.events.service import envelope
from src.modules.projects.service import exigir_acesso
from src.shared.auth import resolve_person
from src.shared.db import conectar
from src.shared.erros import DomainError

router = APIRouter()


def _autenticar(authorization: str | None, token: str | None, projeto: str) -> int:
    cabecalho = authorization or (f"Bearer {token}" if token else None)
    pessoa = resolve_person(cabecalho)
    conn = conectar()
    try:
        exigir_acesso(conn, projeto, pessoa["id"])
    finally:
        conn.close()
    return int(pessoa["id"])


@router.websocket("/ws")
async def websocket_events(
    websocket: WebSocket,
    projeto: str,
    token: str | None = None,
    authorization: str | None = Header(None),
) -> None:
    try:
        person_id = _autenticar(authorization, token, projeto)
    except DomainError as erro:
        await websocket.close(code=4401 if erro.status == 401 else 4404)
        return

    await websocket.accept()
    fila: asyncio.Queue = asyncio.Queue(maxsize=500)
    INSCRITOS[projeto].add(fila)
    try:
        while True:
            evento = await fila.get()
            # Filtro do próprio eco: ninguém é notificado do que acabou de escrever.
            if evento.get("author_id") == person_id:
                continue
            await websocket.send_text(json.dumps(envelope(evento), ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    finally:
        INSCRITOS[projeto].discard(fila)


@router.get("/stream")
async def sse_eventos(
    projeto: str, token: str | None = None, authorization: str | None = Header(None)
):
    try:
        person_id = _autenticar(authorization, token, projeto)
    except DomainError as erro:
        raise HTTPException(erro.status, str(erro)) from None

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
                if evento.get("author_id") == person_id:
                    continue
                yield f"data: {json.dumps(envelope(evento), ensure_ascii=False)}\n\n"
        finally:
            INSCRITOS[projeto].discard(fila)

    return StreamingResponse(gerar(), media_type="text/event-stream")
