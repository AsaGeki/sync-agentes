"""Canal de sincronizacao entre agentes (IA e humanos) sobre projetos e tasks.

Nao e especifico de nenhum projeto: `projetos` e a raiz, `tasks` pendura em projeto,
e toda escrita registra um evento na trilha unica (`eventos`), que serve de cursor
para "o que mudou desde X", de fonte do relatorio e de payload do tempo real.

Alem da API REST, o mesmo contrato fica disponivel como servidor MCP em
`/mcp/` (ver `app/mcp_server.py`) - mesma porta, mesmo token.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings

from app.autores.routes import router as autores_router
from app.db import agora, iniciar_banco
from app.eventos.realtime import router as realtime_router
from app.eventos.routes import router as eventos_router
from app.mcp_server import mcp
from app.projetos.routes import router as projetos_router
from app.tasks.routes import router as tasks_router

iniciar_banco()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Starlette nao roda o lifespan de uma sub-app montada com app.mount() -
    # sem isto, a 1a chamada MCP falha (session manager nunca sobe).
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Sync de agentes",
    description="Canal de alinhamento entre agentes de IA e humanos, por projeto e task.",
    version="1.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "agora": agora(), "versao": app.version}


app.include_router(autores_router)
app.include_router(projetos_router)
app.include_router(tasks_router)
app.include_router(eventos_router)
app.include_router(realtime_router)

# DNS-rebinding protection do MCP so aceita Host: localhost por padrao - quebraria
# acesso por IP de rede. A autenticacao real ja e o token (mesmo modelo do REST),
# entao essa camada extra fica redundante aqui.
mcp_app = mcp.streamable_http_app(
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
app.mount("/mcp", mcp_app)
