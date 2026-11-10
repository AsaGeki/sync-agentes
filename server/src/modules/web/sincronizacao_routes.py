"""Telas admin de configuração da sincronização com o sistema de destino."""

from contextlib import closing

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from src.modules.projects import repositorio as projects_repositorio
from src.modules.sincronizacao import escolhas, execucao, service
from src.modules.sincronizacao import repositorio as sync_repositorio
from src.modules.web import paginas
from src.modules.web.auth import admin_web
from src.modules.web.templating import templates
from src.shared.db import conectar
from src.shared.erros import DomainError, Invalid

router = APIRouter(include_in_schema=False, dependencies=[Depends(admin_web)])

BASE = {"base": "/web/admin", "admin": True}


def _pagina_visao(request: Request):
    destinos, erro_destino = service.destinos_ou_erro()
    with closing(conectar()) as conn:
        linhas = service.visao(conn, destinos)
        for linha in linhas:
            projeto = projects_repositorio.find_by_slug(conn, linha["slug"])
            linha["tasks"] = escolhas.resumo(escolhas.tasks_do_projeto(conn, projeto))
        nav = paginas.ctx_nav(conn, None)
    contexto = {"conexao": service.conexao(), "linhas": linhas, "erro_destino": erro_destino, "nav": nav, **BASE}
    return templates.TemplateResponse(request, "admin/sincronizacao.html", contexto)


def _pagina_projeto(request: Request, slug: str):
    destinos, erro_destino = service.destinos_ou_erro()
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        ctx = service.ctx_projeto(conn, projeto, destinos)
        resumo_tasks = escolhas.resumo(escolhas.tasks_do_projeto(conn, projeto))
        nav = paginas.ctx_nav(conn, None)
    contexto = {
        **ctx,
        "projeto": projeto,
        "resumo_tasks": resumo_tasks,
        "erro_destino": erro_destino,
        "nav": nav,
        **BASE,
    }
    return templates.TemplateResponse(request, "admin/sincronizacao_projeto.html", contexto)


@router.get("/web/admin/sincronizacao")
def visao(request: Request):
    return _pagina_visao(request)


@router.post("/web/admin/sincronizacao/testar")
def testar(request: Request):
    try:
        contexto = {"projetos": service.projetos_destino()}
    except DomainError as erro:
        contexto = {"erro": str(erro)}
    return templates.TemplateResponse(request, "parciais/sinc_teste.html", contexto)


@router.get("/web/admin/sincronizacao/p/{slug}")
def projeto(request: Request, slug: str):
    return _pagina_projeto(request, slug)


@router.post("/web/admin/sincronizacao/p/{slug}/destino")
def salvar_destino(request: Request, slug: str, destino_id: str = Form("")):
    with closing(conectar()) as conn:
        service.salvar_destino(conn, projects_repositorio.find_by_slug(conn, slug), destino_id.strip())
    return _pagina_projeto(request, slug)


@router.post("/web/admin/sincronizacao/p/{slug}/repositorios")
async def salvar_repositorios(request: Request, slug: str):
    dados = await request.form(max_fields=200)
    vinculos = {chave[5:]: str(valor) for chave, valor in dados.items() if chave.startswith("repo_")}
    with closing(conectar()) as conn:
        service.salvar_repositorios(
            conn, projects_repositorio.find_by_slug(conn, slug), vinculos, str(dados.get("padrao", ""))
        )
    return _pagina_projeto(request, slug)


def _filtros(dados) -> dict[str, str]:
    situacao = str(dados.get("situacao") or "sem_repositorio")
    return {
        "situacao": situacao if situacao in escolhas.SITUACOES else "sem_repositorio",
        "tag": str(dados.get("tag") or ""),
        "feature": str(dados.get("feature") or ""),
    }


def _pagina_tasks(request: Request, slug: str, filtros: dict[str, str], aviso: str = ""):
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        todas = escolhas.tasks_do_projeto(conn, projeto)
        repos = service.repos_origem(conn, projeto["id"])
        vinculo = sync_repositorio.find_projeto(conn, projeto["id"])
        features = conn.execute(
            "SELECT id, title FROM features WHERE project_id = ? ORDER BY title", (projeto["id"],)
        ).fetchall()
        nav = paginas.ctx_nav(conn, None)
    contexto = {
        "projeto": projeto,
        "vinculo": vinculo,
        "repos": repos,
        "tasks": escolhas.filtrar(todas, **filtros),
        "resumo": escolhas.resumo(todas),
        "tags": sorted({tag for t in todas for tag in t["tags"]}),
        "features": features,
        "situacoes": escolhas.SITUACOES,
        "filtros": filtros,
        "aviso": aviso,
        "nav": nav,
        **BASE,
    }
    return templates.TemplateResponse(request, "admin/sincronizacao_tasks.html", contexto)


@router.get("/web/admin/sincronizacao/p/{slug}/tasks")
def tasks(request: Request, slug: str, situacao: str = "", tag: str = "", feature: str = ""):
    return _pagina_tasks(request, slug, _filtros({"situacao": situacao, "tag": tag, "feature": feature}))


@router.post("/web/admin/sincronizacao/p/{slug}/tasks/escolhas")
async def salvar_escolhas_tasks(request: Request, slug: str):
    dados = await request.form(max_fields=2000)
    filtros = _filtros(dados)
    pedidas = {}
    for chave, valor in dados.items():
        if chave.startswith("task_"):
            if not chave[5:].isdigit():
                raise Invalid("Dados inválidos. Recarregue a página e tente de novo.")
            pedidas[int(chave[5:])] = str(valor)
    with closing(conectar()) as conn:
        mudadas = escolhas.salvar_escolhas(conn, projects_repositorio.find_by_slug(conn, slug), pedidas)
    return _pagina_tasks(request, slug, filtros, f"{mudadas} task(s) alterada(s).")


@router.post("/web/admin/sincronizacao/p/{slug}/tasks/lote")
async def aplicar_lote(request: Request, slug: str):
    dados = await request.form(max_fields=50)
    filtros = _filtros(dados)
    with closing(conectar()) as conn:
        projeto = projects_repositorio.find_by_slug(conn, slug)
        lista = escolhas.filtrar(escolhas.tasks_do_projeto(conn, projeto), **filtros)
        mudadas = escolhas.aplicar_lote(
            conn,
            projeto,
            str(dados.get("acao", "")),
            lista,
            str(dados.get("repo", "")),
            dados.get("sobrescrever") == "1",
        )
    return _pagina_tasks(request, slug, filtros, f"{mudadas} task(s) alterada(s).")


@router.get("/web/admin/sincronizacao/p/{slug}/replyto.js")
def baixar_patch_replyto(slug: str):
    with closing(conectar()) as conn:
        script, _ = execucao.patch_replyto(conn, projects_repositorio.find_by_slug(conn, slug))
    return Response(
        content=script.encode("utf-8"),
        media_type="text/javascript",
        headers={"Content-Disposition": f'attachment; filename="patch-replyto-{slug}.js"', "Cache-Control": "no-store"},
    )
