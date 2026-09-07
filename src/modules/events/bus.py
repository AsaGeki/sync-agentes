"""Barramento em memória (WebSocket + SSE)."""

import asyncio
from collections import defaultdict
from typing import Any

INSCRITOS: dict[str, set[asyncio.Queue]] = defaultdict(set)


async def publish(slug: str, evento: dict[str, Any]) -> None:
    for fila in list(INSCRITOS[slug]):
        try:
            fila.put_nowait(evento)
        except asyncio.QueueFull:
            pass
