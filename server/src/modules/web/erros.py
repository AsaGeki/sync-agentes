from fastapi import Request
from fastapi.responses import RedirectResponse, Response

from src.modules.web.templating import templates
from src.shared.erros import DomainError, Unauthorized


def resposta_erro_web(request: Request, exc: DomainError) -> Response:
    """Sem sessão vai pro login. Erro em request HTMX vira aviso no topo da
    página atual (`#erro`); em navegação normal, página de erro."""
    htmx = request.headers.get("HX-Request") == "true"
    if isinstance(exc, Unauthorized):
        destino = "/web/admin/login" if request.url.path.startswith("/web/admin") else "/web/login"
        if htmx:
            return Response(status_code=204, headers={"HX-Redirect": destino})
        return RedirectResponse(destino, status_code=303)
    if htmx:
        return templates.TemplateResponse(
            request,
            "parciais/erro.html",
            {"mensagem": str(exc)},
            status_code=exc.status,
            headers={"HX-Retarget": "#erro", "HX-Reswap": "innerHTML", "HX-Reselect": "#erro-msg"},
        )
    return templates.TemplateResponse(
        request, "erro.html", {"mensagem": str(exc), "status": exc.status}, status_code=exc.status
    )
