"""Barramento em memória (SSE)."""

import asyncio
from collections import defaultdict
from typing import Any

from anyio import from_thread

INSCRITOS: dict[str, set[asyncio.Queue]] = defaultdict(set)


def inscrever(fila: asyncio.Queue, slugs: set[str]) -> None:
    for slug in slugs:
        INSCRITOS[slug].add(fila)


def desinscrever(fila: asyncio.Queue, slugs: set[str]) -> None:
    """Tira a fila dos projetos; projeto sem ninguém ouvindo sai do dicionário."""
    for slug in slugs:
        INSCRITOS[slug].discard(fila)
        if not INSCRITOS[slug]:
            del INSCRITOS[slug]


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
