"""Entrega em tempo real do que o outro lado escreveu (SSE).

O frame é o mesmo envelope de evento que `/mudancas` devolve - quem consome os
dois não tem dois formatos pra tratar.

Autenticação exige token pessoal (`Authorization` ou `?token=`) e `X-Agent`.
"""

import asyncio
import json
from contextlib import closing

from fastapi import APIRouter, Header, HTTPException
from sse_starlette import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from src.modules.events.bus import desinscrever, inscrever
from src.modules.events.service import envelope
from src.modules.projects.service import exigir_acesso
from src.shared.auth import normalizar_agent, resolve_person
from src.shared.db import conectar
from src.shared.erros import DomainError

router = APIRouter()
# O bridge (canal) considera a conexão caída sem nada por 40s: o ping vem antes disso.
INTERVALO_PING = 25


def _autenticar(
    authorization: str | None, token: str | None, projeto: str, x_agent: str | None
) -> int:
    cabecalho = authorization or (f"Bearer {token}" if token else None)
    pessoa = resolve_person(cabecalho)
    normalizar_agent(x_agent)
    with closing(conectar()) as conn:
        exigir_acesso(conn, projeto, pessoa["id"])
    return int(pessoa["id"])


@router.get("/stream")
async def sse_eventos(
    projeto: str,
    token: str | None = None,
    authorization: str | None = Header(None),
    x_agent: str | None = Header(None, alias="X-Agent"),
):
    try:
        person_id = _autenticar(authorization, token, projeto, x_agent)
    except DomainError as erro:
        raise HTTPException(erro.status, str(erro)) from None

    async def gerar():
        fila: asyncio.Queue = asyncio.Queue(maxsize=500)
        inscrever(fila, {projeto})
        try:
            while True:
                try:
                    evento = await asyncio.wait_for(fila.get(), timeout=INTERVALO_PING)
                except TimeoutError:
                    # Token reemitido ou pessoa removida do projeto encerra o stream.
                    try:
                        await run_in_threadpool(_autenticar, authorization, token, projeto, x_agent)
                    except DomainError:
                        return
                    continue
                if evento.get("author_id") == person_id:
                    continue
                yield {"data": json.dumps(envelope(evento), ensure_ascii=False)}
        finally:
            desinscrever(fila, {projeto})

    return EventSourceResponse(gerar(), ping=INTERVALO_PING)
