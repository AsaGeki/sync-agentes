"""Repositório de cada task na sincronização: escolha à mão, sugestão por tag ou padrão do projeto."""

import json
import sqlite3
from typing import Any

from src.modules.sincronizacao import repositorio
from src.modules.sincronizacao.pacote import resolver_repositorio
from src.modules.sincronizacao.service import repos_origem
from src.shared.erros import Invalid

SITUACOES = {
    "sem_repositorio": "Sem repositório",
    "todas": "Todas as tasks",
    "manual": "Escolhidas à mão",
    "tag": "Resolvidas pela tag",
    "padrao": "Resolvidas pelo padrão",
}
ACOES_LOTE = ("atribuir", "limpar")


def tasks_do_projeto(conn: sqlite3.Connection, projeto: sqlite3.Row) -> list[dict[str, Any]]:
    repos = repos_origem(conn, projeto["id"])
    vinculo = repositorio.find_projeto(conn, projeto["id"])
    padrao = vinculo["repo_padrao"] if vinculo else None
    manuais = repositorio.escolhas_tasks(conn, projeto["id"])
    vinculados = repositorio.vinculos_repos(conn, projeto["id"])
    linhas = conn.execute(
        """SELECT t.id, t.code, t.title, t.tags, t.feature_id, f.title AS feature
             FROM tasks t LEFT JOIN features f ON f.id = t.feature_id
            WHERE t.project_id = ?
            ORDER BY CAST(SUBSTR(t.code, 3) AS INTEGER)""",
        (projeto["id"],),
    ).fetchall()
    tasks = []
    for linha in linhas:
        tags = json.loads(linha["tags"])
        repo, via = resolver_repositorio(tags, repos, manuais.get(linha["id"]), padrao)
        tasks.append(
            {
                "id": linha["id"],
                "code": linha["code"],
                "numero": linha["code"].split("-")[1],
                "title": linha["title"],
                "tags": tags,
                "feature_id": linha["feature_id"],
                "feature": linha["feature"],
                "manual": manuais.get(linha["id"]),
                "resolvido": repo["root_sha"] if repo else None,
                "resolvido_nome": repo["name"] if repo else None,
                "via": via,
                "sem_vinculo": bool(repo and repo["root_sha"] not in vinculados),
            }
        )
    return tasks


def resumo(tasks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(tasks),
        "sem_repositorio": sum(1 for t in tasks if t["via"] is None),
        "manual": sum(1 for t in tasks if t["via"] == "manual"),
        "tag": sum(1 for t in tasks if t["via"] == "tag"),
        "padrao": sum(1 for t in tasks if t["via"] == "padrao"),
        "sem_vinculo": sum(1 for t in tasks if t["sem_vinculo"]),
    }


def filtrar(tasks: list[dict[str, Any]], situacao: str, tag: str, feature: str) -> list[dict[str, Any]]:
    def passa(t: dict[str, Any]) -> bool:
        if situacao == "sem_repositorio" and t["via"] is not None:
            return False
        if situacao in ("manual", "tag", "padrao") and t["via"] != situacao:
            return False
        if tag and tag not in t["tags"]:
            return False
        if feature == "avulsa":
            return t["feature_id"] is None
        return not feature or str(t["feature_id"]) == feature

    return [t for t in tasks if passa(t)]


def _raizes_e_ids(conn: sqlite3.Connection, projeto: sqlite3.Row) -> tuple[set[str], set[int]]:
    raizes = {r["root_sha"] for r in repos_origem(conn, projeto["id"])}
    ids = {linha["id"] for linha in conn.execute("SELECT id FROM tasks WHERE project_id = ?", (projeto["id"],))}
    return raizes, ids


def salvar_escolhas(conn: sqlite3.Connection, projeto: sqlite3.Row, escolhas: dict[int, str]) -> int:
    """Grava a escolha de cada task listada (vazio volta ao automático). Devolve quantas mudaram."""
    raizes, ids = _raizes_e_ids(conn, projeto)
    atuais = repositorio.escolhas_tasks(conn, projeto["id"])
    mudancas = {}
    for task_id, root_sha in escolhas.items():
        if task_id not in ids or (root_sha and root_sha not in raizes):
            raise Invalid("Task ou repositório inválido. Recarregue a página e tente de novo.")
        if (root_sha or None) != atuais.get(task_id):
            mudancas[task_id] = root_sha or None
    with conn:
        repositorio.salvar_escolhas_tasks(conn, mudancas)
    return len(mudancas)


def aplicar_lote(
    conn: sqlite3.Connection,
    projeto: sqlite3.Row,
    acao: str,
    tasks: list[dict[str, Any]],
    root_sha: str,
    sobrescrever: bool,
) -> int:
    """Aplica uma ação às tasks da lista atual. Devolve quantas mudaram."""
    if acao not in ACOES_LOTE:
        raise Invalid("Ação inválida.")
    raizes, _ = _raizes_e_ids(conn, projeto)
    mudancas: dict[int, str | None] = {}
    for t in tasks:
        if acao == "atribuir":
            if root_sha not in raizes:
                raise Invalid("Escolha um repositório para atribuir.")
            if (sobrescrever or not t["manual"]) and t["manual"] != root_sha:
                mudancas[t["id"]] = root_sha
        elif t["manual"]:
            mudancas[t["id"]] = None
    with conn:
        repositorio.salvar_escolhas_tasks(conn, mudancas)
    return len(mudancas)
