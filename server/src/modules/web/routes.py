"""Área da pessoa: login pelo token pessoal, projetos de que ela é membro,
leitura de task e as escritas leves (mensagem e campos da task)."""

import asyncio
import json
import sqlite3
from contextlib import closing

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response
from sse_starlette import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from src.modules.events.bus import desinscrever, inscrever
from src.modules.events.realtime import INTERVALO_PING
from src.modules.projects import service as projects_service
from src.modules.projects.service import exigir_acesso
from src.modules.tasks import service as tasks_service
from src.modules.tasks.models import MensagemIn, TaskPatch
from src.modules.web import exportacao, indicadores, paginas
from src.modules.web.auth import COOKIE_PESSOA, apagar_cookie, gravar_cookie, pessoa_web
from src.modules.web.filtros import filtros_atividade, filtros_tasks
from src.modules.web.paginas import FEATURE_STATUSES
from src.modules.web.templating import templates
from src.shared.auth import ContextoGit, resolve_person
from src.shared.db import conectar
from src.shared.enums import EAgent, ERole, EStatusTask, ETypeMessage
from src.shared.erros import Unauthorized

router = APIRouter(include_in_schema=False)

CTX_WEB = ContextoGit(agent=EAgent.human)


@router.get("/")
def raiz() -> RedirectResponse:
    return RedirectResponse("/web", status_code=303)


# ---------- sessão ---------- #


@router.get("/web/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"alvo": "pessoa"})


@router.post("/web/login")
def login(request: Request, token: str = Form(...)):
    try:
        resolve_person(f"Bearer {token.strip()}")
    except Unauthorized as erro:
        return templates.TemplateResponse(
            request, "login.html", {"alvo": "pessoa", "erro": str(erro)}, status_code=401
        )
    resposta = RedirectResponse("/web", status_code=303)
    gravar_cookie(resposta, COOKIE_PESSOA, token.strip())
    return resposta


@router.post("/web/logout")
def logout() -> RedirectResponse:
    resposta = RedirectResponse("/web/login", status_code=303)
    apagar_cookie(resposta, COOKIE_PESSOA)
    return resposta


# ---------- páginas ---------- #


def _pagina_do_projeto(request: Request, slug: str, pessoa: sqlite3.Row, modelo: str, montar):
    """Página de projeto da pessoa: confere o acesso, monta o contexto com `montar(conn, projeto)`
    e junta a barra lateral."""
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        ctx = montar(conn, projeto)
        nav = paginas.ctx_nav(conn, pessoa["id"])
    return templates.TemplateResponse(request, modelo, {"pessoa": pessoa, "nav": nav, **ctx})


@router.get("/web")
def inicio(request: Request, pessoa: sqlite3.Row = Depends(pessoa_web)):
    with closing(conectar()) as conn:
        cards = indicadores.cards(conn, indicadores.projetos_da_pessoa(conn, pessoa["id"]), pessoa["id"])
        nav = paginas.ctx_nav(conn, pessoa["id"])
    return templates.TemplateResponse(
        request, "inicio.html", {"pessoa": pessoa, "cards": cards, "nav": nav, "base": "/web", "admin": False}
    )


@router.get("/web/p/{slug}")
def painel(
    request: Request,
    slug: str,
    por: str = Query("pessoa", pattern="^(pessoa|agent)$"),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    return _pagina_do_projeto(
        request, slug, pessoa, "painel.html", lambda conn, projeto: paginas.ctx_painel(conn, projeto, pessoa["id"], por)
    )


@router.get("/web/p/{slug}/exportar")
def pagina_exportacao(request: Request, slug: str, pessoa: sqlite3.Row = Depends(pessoa_web)):
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        ctx = exportacao.preparar(conn, projeto)
        nav = paginas.ctx_nav(conn, pessoa["id"])
    return templates.TemplateResponse(
        request, "exportacao.html",
        {**ctx, "projeto": projeto, "nav": nav, "pessoa": pessoa, "base": "/web", "admin": False},
    )


@router.post("/web/p/{slug}/exportar")
async def exportar_projeto(request: Request, slug: str, pessoa: sqlite3.Row = Depends(pessoa_web)):
    dados = await request.form(max_fields=10000)
    with closing(conectar()) as conn:
        conn.execute("BEGIN")
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        return exportacao.baixar_projeto(conn, projeto, dados)


@router.get("/web/p/{slug}/tasks")
def tasks(
    request: Request,
    slug: str,
    filtros: dict = Depends(filtros_tasks),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    return _pagina_do_projeto(
        request, slug, pessoa, "tasks.html",
        lambda conn, projeto: paginas.ctx_tasks(conn, projeto, pessoa["id"], filtros)
    )


@router.get("/web/p/{slug}/features")
def features(
    request: Request,
    slug: str,
    status: str = Query("", pattern="^(|" + "|".join(FEATURE_STATUSES) + ")$"),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    return _pagina_do_projeto(
        request, slug, pessoa, "features.html",
        lambda conn, projeto: paginas.ctx_features(conn, projeto, pessoa["id"], status)
    )


@router.get("/web/p/{slug}/f/{code}")
def feature(request: Request, slug: str, code: str, pessoa: sqlite3.Row = Depends(pessoa_web)):
    return _pagina_do_projeto(
        request, slug, pessoa, "feature.html",
        lambda conn, projeto: paginas.ctx_feature(conn, projeto, pessoa["id"], code)
    )


def _pagina_atividade(request: Request, slug: str, filtros: dict, pessoa: sqlite3.Row, modelo: str):
    return _pagina_do_projeto(
        request, slug, pessoa, modelo, lambda conn, projeto: paginas.ctx_atividade(conn, projeto, pessoa["id"], filtros)
    )


@router.get("/web/p/{slug}/atividade")
def atividade(
    request: Request,
    slug: str,
    filtros: dict = Depends(filtros_atividade),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    return _pagina_atividade(request, slug, filtros, pessoa, "atividade.html")


@router.get("/web/p/{slug}/atividade/mais")
def atividade_mais(
    request: Request,
    slug: str,
    filtros: dict = Depends(filtros_atividade),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    return _pagina_atividade(request, slug, filtros, pessoa, "parciais/feed_itens.html")


def _pagina_task(request: Request, slug: str, code: str, pessoa: sqlite3.Row):
    return _pagina_do_projeto(
        request, slug, pessoa, "task.html", lambda conn, projeto: paginas.ctx_task(conn, projeto, code, pessoa["id"])
    )


@router.get("/web/p/{slug}/t/{code}")
def task(request: Request, slug: str, code: str, pessoa: sqlite3.Row = Depends(pessoa_web)):
    return _pagina_task(request, slug, code, pessoa)


@router.get("/web/p/{slug}/t/{code}/corpo-diff")
def corpo_diff(
    request: Request,
    slug: str,
    code: str,
    versao: int = Query(..., ge=1),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        ctx = paginas.ctx_corpo_diff(conn, projeto, code, versao)
    return templates.TemplateResponse(request, "parciais/corpo_diff.html", ctx)


# ---------- escrita ---------- #


@router.post("/web/p/{slug}/t/{code}/campos")
def editar_campos(
    request: Request,
    slug: str,
    code: str,
    status: EStatusTask = Form(...),
    owner_id: str = Form("", pattern=r"^\d{0,18}$"),
    feature: str = Form(""),
    tags: str = Form(""),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    campos = {
        "status": status,
        "feature": feature,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
    }
    # Vazio não muda o dono; "0" é "sem dono" e vira `null` explícito.
    if owner_id == "0":
        campos["owner_id"] = None
    elif owner_id:
        campos["owner_id"] = int(owner_id)
    dados = TaskPatch(**campos)
    with closing(conectar()) as conn:
        tasks_service.update_task(conn, slug, code, pessoa["id"], CTX_WEB, dados)
    return _pagina_task(request, slug, code, pessoa)


@router.post("/web/p/{slug}/t/{code}/mensagens")
def enviar_mensagem(
    request: Request,
    slug: str,
    code: str,
    tipo: ETypeMessage = Form(...),
    texto: str = Form(..., min_length=1),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    with closing(conectar()) as conn:
        tasks_service.create_message(
            conn, slug, code, pessoa["id"], CTX_WEB, MensagemIn(type=tipo, texto=texto)
        )
    return _pagina_task(request, slug, code, pessoa)


@router.post("/web/p/{slug}/membros/{person_id}/remover")
def remover_membro(
    request: Request, slug: str, person_id: int, pessoa: sqlite3.Row = Depends(pessoa_web)
):
    """Owner tira um membro; quem tira a si mesmo sai do projeto e volta ao início."""
    with closing(conectar()) as conn:
        projects_service.remove_member(conn, slug, pessoa["id"], person_id, CTX_WEB)
    if person_id == pessoa["id"]:
        return Response(headers={"HX-Redirect": "/web"})
    return painel(request, slug, "pessoa", pessoa)


@router.post("/web/p/{slug}/membros/{person_id}/papel")
def trocar_papel(
    request: Request,
    slug: str,
    person_id: int,
    role: ERole = Form(...),
    pessoa: sqlite3.Row = Depends(pessoa_web),
):
    with closing(conectar()) as conn:
        projects_service.set_member_role(conn, slug, pessoa["id"], person_id, role)
    return painel(request, slug, "pessoa", pessoa)


# ---------- tempo real ---------- #


@router.get("/web/stream")
async def stream(pessoa: sqlite3.Row = Depends(pessoa_web)) -> EventSourceResponse:
    """Um canal só por pessoa, com todos os projetos dela: as abas dividem esta
    conexão via SharedWorker, porque o navegador limita 6 conexões HTTP/1.1 por
    host e uma por aba travava quem abria várias. Cada aviso diz projeto e task;
    a página filtra o que é dela e rebusca o trecho afetado. Não corta o próprio
    eco: a IA da pessoa escreve assinando como ela, e isso precisa aparecer."""
    def projetos_atuais() -> set[str]:
        with closing(conectar()) as conn:
            return {p["slug"] for p in indicadores.projetos_da_pessoa(conn, pessoa["id"])}

    slugs = projetos_atuais()

    async def gerar():
        fila: asyncio.Queue = asyncio.Queue(maxsize=500)
        inscritos = set(slugs)
        inscrever(fila, inscritos)
        try:
            while True:
                try:
                    evento = await asyncio.wait_for(fila.get(), timeout=INTERVALO_PING)
                except TimeoutError:
                    # A inscrição acompanha os projetos de agora (entrou ou saiu de algum).
                    atuais = await run_in_threadpool(projetos_atuais)
                    inscrever(fila, atuais - inscritos)
                    desinscrever(fila, inscritos - atuais)
                    inscritos = atuais
                    continue
                aviso = {"projeto": evento["project_slug"], "task": evento.get("task_code")}
                yield {"event": "mudou", "data": json.dumps(aviso)}
        finally:
            desinscrever(fila, inscritos)

    return EventSourceResponse(gerar(), ping=INTERVALO_PING)
