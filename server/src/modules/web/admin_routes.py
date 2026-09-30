"""Área admin (`ADMIN_TOKEN`): people e tokens, todos os projetos, leitura de
qualquer projeto e gestão de membros e pedidos sem precisar de owner."""

from contextlib import closing

from fastapi import APIRouter, Depends, Form, Path, Query, Request
from fastapi.responses import RedirectResponse, Response

from src.modules.people import service as people_service
from src.modules.people.models import PersonPatch, PessoaIn
from src.modules.projects import repositorio as projects_repositorio
from src.modules.projects import service as projects_service
from src.modules.web import indicadores, paginas
from src.modules.web.auth import COOKIE_ADMIN, admin_web, apagar_cookie, gravar_cookie
from src.modules.web.filtros import filtros_atividade, filtros_tasks
from src.modules.web.paginas import FEATURE_STATUSES
from src.modules.web.templating import templates
from src.shared.auth import validate_admin
from src.shared.db import conectar
from src.shared.erros import Unauthorized

router = APIRouter(include_in_schema=False)
protegido = APIRouter(include_in_schema=False, dependencies=[Depends(admin_web)])


# ---------- sessão ---------- #


@router.get("/web/admin/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"alvo": "admin"})


@router.post("/web/admin/login")
def login(request: Request, token: str = Form(...)):
    try:
        validate_admin(f"Bearer {token.strip()}")
    except Unauthorized as erro:
        return templates.TemplateResponse(
            request, "login.html", {"alvo": "admin", "erro": str(erro)}, status_code=401
        )
    resposta = RedirectResponse("/web/admin", status_code=303)
    gravar_cookie(resposta, COOKIE_ADMIN, token.strip())
    return resposta


@router.post("/web/admin/logout")
def logout() -> RedirectResponse:
    resposta = RedirectResponse("/web/admin/login", status_code=303)
    apagar_cookie(resposta, COOKIE_ADMIN)
    return resposta


# ---------- people ---------- #


def _pagina_people(request: Request, token_emitido: dict | None = None):
    with closing(conectar()) as conn:
        people = people_service.list_people(conn)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(
        request,
        "admin/people.html",
        {"people": people, "token_emitido": token_emitido, "nav": nav, "base": "/web/admin", "admin": True},
    )


@protegido.get("/web/admin")
def inicio() -> RedirectResponse:
    return RedirectResponse("/web/admin/people", status_code=303)


@protegido.get("/web/admin/people")
def people(request: Request):
    return _pagina_people(request)


@protegido.post("/web/admin/people")
def criar_pessoa(request: Request, email: str = Form(...), name: str = Form(...)):
    with closing(conectar()) as conn:
        people_service.create_person(conn, PessoaIn(email=email.strip(), name=name.strip()))
    return _pagina_people(request)


@protegido.post("/web/admin/people/{person_id}")
def editar_pessoa(request: Request, person_id: int, email: str = Form(...), name: str = Form(...)):
    with closing(conectar()) as conn:
        people_service.patch_person(conn, person_id, PersonPatch(email=email.strip(), name=name.strip()))
    return _pagina_people(request)


@protegido.post("/web/admin/people/{person_id}/token")
def emitir_token(request: Request, person_id: int):
    with closing(conectar()) as conn:
        emitido = people_service.generate_token(conn, person_id)
    return _pagina_people(request, token_emitido=emitido)


@protegido.post("/web/admin/people/{person_id}/apagar")
def apagar_pessoa(request: Request, person_id: int):
    with closing(conectar()) as conn:
        people_service.delete_person(conn, person_id)
    return _pagina_people(request)


# ---------- projetos ---------- #


@protegido.get("/web/admin/projetos")
def projetos(request: Request):
    with closing(conectar()) as conn:
        cards = indicadores.cards(conn, indicadores.todos_projetos(conn), None)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(
        request, "inicio.html", {"cards": cards, "nav": nav, "base": "/web/admin", "admin": True}
    )


@protegido.post("/web/admin/p/{slug}/apagar")
def apagar_projeto(slug: str) -> Response:
    with closing(conectar()) as conn:
        projects_service.delete_project(conn, slug)
    return Response(status_code=204, headers={"HX-Redirect": "/web/admin/projetos"})


@protegido.get("/web/admin/p/{slug}")
def painel(request: Request, slug: str, por: str = Query("pessoa", pattern="^(pessoa|agent)$")):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_painel(conn, projeto, None, por)
        pedidos = projects_repositorio.pending_requests_do_projeto(conn, projeto["id"])
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, "painel.html", {**ctx, "pedidos": pedidos, "nav": nav})


@protegido.post("/web/admin/p/{slug}/membros")
def adicionar_membro(request: Request, slug: str, email: str = Form(...)):
    with closing(conectar()) as conn:
        projects_service.admin_add_member(conn, slug, email.strip())
    return painel(request, slug, por="pessoa")


@protegido.post("/web/admin/p/{slug}/pedidos/{request_id}/{acao}")
def resolver_pedido(
    request: Request, slug: str, request_id: int, acao: str = Path(..., pattern="^(aceitar|recusar)$")
):
    with closing(conectar()) as conn:
        projects_service.admin_resolver_request(conn, slug, request_id, aceitar=acao == "aceitar")
    return painel(request, slug, por="pessoa")


@protegido.get("/web/admin/p/{slug}/tasks")
def tasks(request: Request, slug: str, filtros: dict = Depends(filtros_tasks)):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_tasks(conn, projeto, None, filtros)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, "tasks.html", {**ctx, "nav": nav})


@protegido.get("/web/admin/p/{slug}/features")
def features(
    request: Request,
    slug: str,
    status: str = Query("", pattern="^(|" + "|".join(FEATURE_STATUSES) + ")$"),
):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_features(conn, projeto, None, status)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, "features.html", {**ctx, "nav": nav})


@protegido.get("/web/admin/p/{slug}/f/{code}")
def feature(request: Request, slug: str, code: str):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_feature(conn, projeto, None, code)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, "feature.html", {**ctx, "nav": nav})


def _pagina_atividade(request: Request, slug: str, filtros: dict, modelo: str):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_atividade(conn, projeto, None, filtros)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, modelo, {**ctx, "nav": nav})


@protegido.get("/web/admin/p/{slug}/atividade")
def atividade(request: Request, slug: str, filtros: dict = Depends(filtros_atividade)):
    return _pagina_atividade(request, slug, filtros, "atividade.html")


@protegido.get("/web/admin/p/{slug}/atividade/mais")
def atividade_mais(request: Request, slug: str, filtros: dict = Depends(filtros_atividade)):
    return _pagina_atividade(request, slug, filtros, "parciais/feed_itens.html")


@protegido.get("/web/admin/p/{slug}/t/{code}")
def task(request: Request, slug: str, code: str):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_task(conn, projeto, code, None)
        nav = paginas.ctx_nav(conn, None)
    return templates.TemplateResponse(request, "task.html", {**ctx, "nav": nav})


@protegido.get("/web/admin/p/{slug}/t/{code}/corpo-diff")
def corpo_diff(request: Request, slug: str, code: str, versao: int = Query(..., ge=1)):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = paginas.ctx_corpo_diff(conn, projeto, code, versao)
    return templates.TemplateResponse(request, "parciais/corpo_diff.html", ctx)


router.include_router(protegido)
