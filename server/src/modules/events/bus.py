"""Barramento em memória (SSE)."""

import asyncio
from collections import defaultdict
from typing import Any

from anyio import from_thread

INSCRITOS: dict[str, set[asyncio.Queue]] = defaultdict(set)


def _entregar(slug: str, evento: dict[str, Any]) -> None:
    for fila in list(INSCRITOS.get(slug, ())):
        try:
            fila.put_nowait(evento)
        except asyncio.QueueFull:
            pass


def publish(slug: str, evento: dict[str, Any]) -> None:
    """Chamado das rotas síncronas, que rodam em thread: a entrega vai pro event
    loop, que é de onde as filas do SSE podem ser tocadas."""
    from_thread.run_sync(_entregar, slug, evento)
