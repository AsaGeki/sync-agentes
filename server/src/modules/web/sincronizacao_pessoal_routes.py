"""Área pessoal: cada pessoa sincroniza o que é dela com o próprio token do destino."""

import sqlite3
from contextlib import closing

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from src.modules.projects.service import exigir_acesso
from src.modules.sincronizacao import execucao, service
from src.modules.sincronizacao import repositorio as sync_repositorio
from src.modules.web import indicadores, paginas
from src.modules.web.auth import (
    COOKIE_DESTINO,
    VALIDADE_COOKIE_DESTINO,
    apagar_cookie,
    gravar_cookie,
    pessoa_web,
    token_destino,
)
from src.modules.web.templating import templates
from src.shared import config
from src.shared.db import conectar
from src.shared.erros import DomainError

router = APIRouter(include_in_schema=False)

BASE = {"base": "/web", "admin": False}


def _estado_token(token: str | None) -> dict:
    """O que a tela mostra sobre o token: nenhum, válido (e se é administrador) ou com problema."""
    if not token:
        return {"informado": False}
    try:
        return {"informado": True, **service.verificar_token(token)}
    except DomainError as erro:
        return {"informado": True, "erro": str(erro)}


def _pagina_inicio(request: Request, pessoa: sqlite3.Row, token: str | None, aviso: str = ""):
    with closing(conectar()) as conn:
        projetos = []
        for projeto in sorted(indicadores.projetos_da_pessoa(conn, pessoa["id"]), key=lambda p: p["name"]):
            vinculo = sync_repositorio.find_projeto(conn, projeto["id"])
            if vinculo is None:
                continue
            escopo = execucao.escopo_da_pessoa(conn, projeto, pessoa["id"])
            if escopo["proprias"]:
                projetos.append(
                    {"slug": projeto["slug"], "name": projeto["name"], "destino": vinculo["destino_nome"], **escopo}
                )
        nav = paginas.ctx_nav(conn, pessoa["id"])
    contexto = {
        "pessoa": pessoa,
        "token": _estado_token(token),
        "conexao": service.conexao(),
        "projetos": projetos,
        "aviso": aviso,
        "nav": nav,
        **BASE,
    }
    return templates.TemplateResponse(request, "sincronizacao_pessoal.html", contexto)


@router.get("/web/sincronizacao")
def inicio(request: Request, pessoa: sqlite3.Row = Depends(pessoa_web)):
    return _pagina_inicio(request, pessoa, token_destino(request))


@router.post("/web/sincronizacao/token")
def salvar_token(request: Request, token: str = Form(...), pessoa: sqlite3.Row = Depends(pessoa_web)):
    token = token.strip()
    service.verificar_token(token)
    resposta = _pagina_inicio(request, pessoa, token, "Token aceito para este navegador.")
    gravar_cookie(resposta, COOKIE_DESTINO, token, VALIDADE_COOKIE_DESTINO)
    return resposta


@router.post("/web/sincronizacao/token/remover")
def remover_token(request: Request, pessoa: sqlite3.Row = Depends(pessoa_web)):
    resposta = _pagina_inicio(request, pessoa, None, "Token removido deste navegador.")
    apagar_cookie(resposta, COOKIE_DESTINO)
    return resposta


def _pagina_projeto(request: Request, slug: str, pessoa: sqlite3.Row, run_id: int | None = None):
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        vinculo = sync_repositorio.find_projeto(conn, projeto["id"])
        historico = execucao.listar(conn, projeto["id"], pessoa["id"])
        if run_id is not None:
            atual = execucao.obter(conn, projeto["id"], pessoa["id"], run_id)
        else:
            atual = historico[0] if historico else None
        vigente = execucao.previa_vigente(conn, projeto, pessoa["id"]) if vinculo else None
        escopo = execucao.escopo_da_pessoa(conn, projeto, pessoa["id"])
        quem_roda = execucao.em_andamento(conn, projeto["id"])
        nav = paginas.ctx_nav(conn, pessoa["id"])
    conexao = service.conexao()
    pessoal, servico = token_destino(request), config.DESTINO_TOKEN
    # A de serviço importa (precisa ser administradora do sistema); a pessoa, se tiver token, assina as edições.
    importacao = "servico" if servico else ("pessoal" if pessoal else None)
    edicao = "pessoal" if pessoal else ("servico" if servico else None)
    estado = _estado_token(servico or pessoal) if importacao else {}
    contexto = {
        "pessoa": pessoa,
        "projeto": projeto,
        "vinculo": vinculo,
        "conexao": conexao,
        "esperado": pessoa["email"] if edicao == "pessoal" else (config.DESTINO_USUARIO_SERVICO or None),
        "importacao": importacao,
        "edicao": edicao,
        "administrador": estado.get("administrador"),
        "erro_credencial": estado.get("erro"),
        "escopo": escopo,
        "historico": historico,
        "atual": atual,
        "vigente": vigente,
        "quem_roda": quem_roda,
        "url": f"/web/sincronizacao/p/{slug}",
        "nav": nav,
        **BASE,
    }
    return templates.TemplateResponse(request, "sincronizacao_pessoal_projeto.html", contexto)


@router.get("/web/sincronizacao/p/{slug}")
def projeto(request: Request, slug: str, run: int | None = None, pessoa: sqlite3.Row = Depends(pessoa_web)):
    return _pagina_projeto(request, slug, pessoa, run)


@router.post("/web/sincronizacao/p/{slug}/executar/{modo}")
def iniciar_execucao(request: Request, slug: str, modo: str, pessoa: sqlite3.Row = Depends(pessoa_web)):
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        run_id = execucao.iniciar(conn, projeto, modo, pessoa, token_destino(request))
    return _pagina_projeto(request, slug, pessoa, run_id)


@router.get("/web/sincronizacao/p/{slug}/execucoes/{run_id}")
def acompanhar(request: Request, slug: str, run_id: int, pessoa: sqlite3.Row = Depends(pessoa_web)):
    with closing(conectar()) as conn:
        projeto = exigir_acesso(conn, slug, pessoa["id"])
        run = execucao.obter(conn, projeto["id"], pessoa["id"], run_id)
    if run["status"] != "rodando":
        # Terminou: a página inteira recarrega para liberar os botões e atualizar o histórico.
        return Response(status_code=200, headers={"HX-Refresh": "true"})
    contexto = {"run": run, "url": f"/web/sincronizacao/p/{slug}"}
    return templates.TemplateResponse(request, "parciais/sinc_execucao.html", contexto)
