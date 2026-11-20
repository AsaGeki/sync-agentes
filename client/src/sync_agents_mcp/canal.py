"""Canal em tempo real (`claude/channel`): empurra pra dentro da sessão o que o
outro lado escreveu, em vez de a IA ter que perguntar.

O servidor já entrega os eventos por SSE (`/stream`); aqui cada evento vira uma
notificação `notifications/claude/channel`. O Claude Code só repassa isso ao
modelo quando a sessão abre com `--channels` (ou `--dangerously-load-development-channels`
enquanto o servidor não está na allowlist); sem a flag a notificação é ignorada.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from collections.abc import Awaitable, Callable

import httpx

CAPACIDADE = {"claude/channel": {}}

# O servidor manda um ping a cada 25s; sem nada por 40s a conexão caiu.
TIMEOUT_DO_STREAM = httpx.Timeout(10, read=40)
ESPERA_MAXIMA = 60


def _ler_stream(
    url: str, params: dict[str, str], cabecalhos: dict[str, str], ao_evento: Callable[[dict], None]
) -> None:
    with httpx.stream("GET", url, params=params, headers=cabecalhos, timeout=TIMEOUT_DO_STREAM) as resposta:
        resposta.raise_for_status()
        for linha in resposta.iter_lines():
            if linha.startswith("data:"):
                ao_evento(json.loads(linha[5:]))


def _observar(
    base_url: str,
    token: str,
    agent: str,
    slug: str,
    loop: asyncio.AbstractEventLoop,
    notificar: Callable[[str, dict[str, str]], Awaitable[None]],
) -> None:
    url = f"{base_url.rstrip('/')}/stream"
    params = {"projeto": slug}
    cabecalhos = {"Authorization": f"Bearer {token}", "X-Agent": agent}

    def ao_evento(evento: dict) -> None:
        meta = {"project": evento["project"], "kind": str(evento["kind"])}
        if evento.get("task"):
            meta["task"] = evento["task"]
        asyncio.run_coroutine_threadsafe(notificar(evento["resumo"], meta), loop).result()

    espera = 1
    while True:
        inicio = time.monotonic()
        try:
            _ler_stream(url, params, cabecalhos, ao_evento)
        except Exception as erro:  # a conexão cai por rede, deploy ou token: só reconecta
            print(f"sync-agents: canal de {slug} caiu ({erro}); reconectando", file=sys.stderr)
        # Conexão que durou foi saudável: a próxima falha recomeça o backoff do zero.
        espera = 1 if time.monotonic() - inicio > ESPERA_MAXIMA else min(espera * 2, ESPERA_MAXIMA)
        time.sleep(espera)


def iniciar(
    base_url: str,
    token: str,
    agent: str,
    slugs: list[str],
    notificar: Callable[[str, dict[str, str]], Awaitable[None]],
) -> None:
    """Abre 1 thread por projeto; elas morrem junto com o processo."""
    loop = asyncio.get_running_loop()
    for slug in slugs:
        threading.Thread(
            target=_observar,
            args=(base_url, token, agent, slug, loop, notificar),
            daemon=True,
            name=f"canal-{slug}",
        ).start()
