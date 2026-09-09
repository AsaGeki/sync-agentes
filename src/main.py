import platform
import sqlite3
import time
from typing import Any

import psutil
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from src.modules.events.realtime import router as realtime_router
from src.modules.events.routes import router as eventos_router
from src.modules.people.routes import router as people_router
from src.modules.projects.routes import router as projetos_router
from src.modules.tasks.routes import router as tasks_router
from src.shared.db import BASE_DIR, DB_PATH, conectar, iniciar_banco, now
from src.shared.erros import DomainError

iniciar_banco()

INICIADO_EM = now()
_INICIO_MONOTONICO = time.monotonic()
_PROCESSO = psutil.Process()


def formatar_duracao(segundos: int) -> str:
    dias, resto = divmod(segundos, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, seg = divmod(resto, 60)
    partes = []
    if dias:
        partes.append(f"{dias}d")
    if horas or dias:
        partes.append(f"{horas}h")
    if minutos or horas or dias:
        partes.append(f"{minutos}min")
    partes.append(f"{seg}s")
    return " ".join(partes)


def banco_conectado() -> bool:
    try:
        with conectar() as conn:
            conn.execute("SELECT 1")
        return True
    except sqlite3.Error:
        return False


app = FastAPI(
    title="Sync Agents",
    description="Canal de alinhamento entre agentes de IA e humanos, por projeto e task.",
    version="3.0.0",
)


# Erro de regra de negócio vira HTTP aqui, num handler global - nenhuma rota
# precisa de try/except pra isso.
@app.exception_handler(DomainError)
async def tratar_erro_dominio(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, Any]:
    tempo_ligado_segundos = int(time.monotonic() - _INICIO_MONOTONICO)
    ram_usada_mb = _PROCESSO.memory_info().rss / (1024 * 1024)
    return {
        "status": "ONLINE",
        "online": True,
        "versao": app.version,
        "now": now(),
        "iniciadoEm": INICIADO_EM,
        "tempoLigadoSegundos": tempo_ligado_segundos,
        "tempoLigadoTexto": formatar_duracao(tempo_ligado_segundos),
        "bancoTipo": "sqlite",
        "bancoVersao": sqlite3.sqlite_version,
        "bancoArquivo": DB_PATH.name,
        "bancoConectado": banco_conectado(),
        "sistemaOperacional": f"{platform.system()} {platform.release()}",
        "ramUsadaMb": round(ram_usada_mb, 1),
    }


@app.get("/changelog", response_class=PlainTextResponse)
def changelog() -> str:
    return (BASE_DIR / "CHANGELOG.md").read_text(encoding="utf-8")


app.include_router(people_router)
app.include_router(projetos_router)
app.include_router(tasks_router)
app.include_router(eventos_router)
app.include_router(realtime_router)