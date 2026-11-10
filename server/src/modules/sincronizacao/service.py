"""Configuração da sincronização: conexão com o destino e vínculos de projeto e repositório."""

import sqlite3
import urllib.error
from typing import Any

from src.modules.sincronizacao import repositorio
from src.modules.sincronizacao.destino import ClienteDestino, ErroDestino
from src.modules.sincronizacao.pacote import mesmo_repositorio
from src.shared import config
from src.shared.erros import Indisponivel, Invalid, MissingRequirement


def conexao() -> dict[str, Any]:
    # `tem_url` basta para a sincronização de cada pessoa, que usa o token dela; o token do .env só serve
    # à configuração na administração (ler os projetos do destino).
    return {
        "url": config.DESTINO_URL,
        "tem_url": bool(config.DESTINO_URL),
        "tem_token": bool(config.DESTINO_TOKEN),
        "configurada": bool(config.DESTINO_URL and config.DESTINO_TOKEN),
    }


def projetos_destino(token: str | None = None) -> list[dict[str, Any]]:
    """Projetos do destino, lidos com o token da pessoa ou, sem ele, com o do .env."""
    token = token or config.DESTINO_TOKEN
    if not config.DESTINO_URL:
        raise MissingRequirement("Defina DESTINO_URL no .env do servidor e reinicie.")
    if not token:
        raise MissingRequirement("Informe o seu token do destino.")
    try:
        return ClienteDestino(config.DESTINO_URL, token).listar("project")
    except ErroDestino as erro:
        if erro.status in (401, 403):
            raise Indisponivel("O destino recusou o token. Ele precisa ser um token humano válido.") from erro
        raise Indisponivel(f"O destino respondeu com erro ({erro}).") from erro
    except urllib.error.URLError as erro:
        raise Indisponivel(f"Não consegui conectar em {config.DESTINO_URL}: {erro.reason}") from erro


def verificar_token(token: str) -> dict[str, Any]:
    """Confirma que o token funciona e se é de administrador do sistema (só ele consegue importar)."""
    projetos = projetos_destino(token)
    cliente = ClienteDestino(config.DESTINO_URL, token)
    try:
        cliente.get("/admin/credentials")
        administrador = True
    except ErroDestino as erro:
        if erro.status != 403:
            raise Indisponivel(f"O destino respondeu com erro ({erro}).") from erro
        administrador = False
    return {"projetos": len(projetos), "administrador": administrador}


def destinos_ou_erro(token: str | None = None) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Para páginas que continuam úteis com o destino fora do ar: devolve o aviso em vez de falhar."""
    try:
        return projetos_destino(token), None
    except (Indisponivel, MissingRequirement) as erro:
        return None, str(erro)


def sugerir_destino(repos: list[sqlite3.Row], destinos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """O projeto do destino que contém todos os repositórios de origem, se for um só."""
    if not repos:
        return None
    completos = [d for d in destinos if all(any(mesmo_repositorio(r, x) for x in d["repositories"]) for r in repos)]
    return completos[0] if len(completos) == 1 else None


def repos_origem(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT root_sha, name, remote FROM project_repos WHERE project_id = ? ORDER BY name", (project_id,)
    ).fetchall()


def visao(conn: sqlite3.Connection, destinos: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    linhas = []
    for projeto in conn.execute("SELECT id, slug, name FROM projects ORDER BY name").fetchall():
        repos = repos_origem(conn, projeto["id"])
        vinculo = repositorio.find_projeto(conn, projeto["id"])
        sugestao = None if vinculo or destinos is None else sugerir_destino(repos, destinos)
        linhas.append(
            {
                "slug": projeto["slug"],
                "name": projeto["name"],
                "vinculo": vinculo,
                "sugestao": sugestao["name"] if sugestao else None,
                "repos_total": len(repos),
                "repos_vinculados": len(repositorio.vinculos_repos(conn, projeto["id"])) if vinculo else 0,
            }
        )
    return linhas


def ctx_projeto(
    conn: sqlite3.Connection, projeto: sqlite3.Row, destinos: list[dict[str, Any]] | None
) -> dict[str, Any]:
    repos = repos_origem(conn, projeto["id"])
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    destino = None
    if vinculo and destinos is not None:
        destino = next((d for d in destinos if d["_id"] == vinculo["destino_id"]), None)
    salvos = repositorio.vinculos_repos(conn, projeto["id"]) if vinculo else {}
    linhas = []
    for repo in repos:
        sugerido = None
        if destino:
            sugerido = next((x["id"] for x in destino["repositories"] if mesmo_repositorio(repo, x)), None)
        linhas.append(
            {
                "root_sha": repo["root_sha"],
                "name": repo["name"],
                "remote": repo["remote"],
                "salvo": salvos.get(repo["root_sha"]),
                "sugerido": sugerido,
            }
        )
    return {
        "vinculo": vinculo,
        "destino": destino,
        "destinos": destinos,
        "sugestao": None if vinculo or destinos is None else sugerir_destino(repos, destinos),
        "repos": linhas,
        "destino_removido": bool(vinculo and destinos is not None and destino is None),
    }


def salvar_destino(conn: sqlite3.Connection, projeto: sqlite3.Row, destino_id: str) -> None:
    if not destino_id:
        with conn:
            repositorio.desvincular_projeto(conn, projeto["id"])
        return
    destino = next((d for d in projetos_destino() if d["_id"] == destino_id), None)
    if destino is None:
        raise Invalid("Esse projeto não existe mais no destino. Recarregue a página.")
    with conn:
        repositorio.vincular_projeto(conn, projeto["id"], destino["_id"], destino["name"])


def salvar_repositorios(conn: sqlite3.Connection, projeto: sqlite3.Row, escolhas: dict[str, str], padrao: str) -> None:
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    if vinculo is None:
        raise Invalid("Vincule o projeto a um projeto do destino antes de vincular repositórios.")
    destino = next((d for d in projetos_destino() if d["_id"] == vinculo["destino_id"]), None)
    if destino is None:
        raise Invalid("O projeto vinculado não existe mais no destino. Escolha outro destino.")
    origem = {r["root_sha"] for r in repos_origem(conn, projeto["id"])}
    validos = {r["id"] for r in destino["repositories"]}
    vinculos = {}
    for root_sha, destino_repo_id in escolhas.items():
        if not destino_repo_id:
            continue
        if root_sha not in origem or destino_repo_id not in validos:
            raise Invalid("Repositório inválido. Recarregue a página e tente de novo.")
        vinculos[root_sha] = destino_repo_id
    if padrao and padrao not in origem:
        raise Invalid("Repositório padrão inválido. Recarregue a página e tente de novo.")
    with conn:
        repositorio.substituir_vinculos_repos(conn, projeto["id"], vinculos)
        repositorio.set_repo_padrao(conn, projeto["id"], padrao or None)
