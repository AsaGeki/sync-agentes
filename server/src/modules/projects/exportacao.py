"""Exporta um projeto para o formato de importação do Project Tasks MCP."""

import argparse
import json
import os
import sqlite3
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

COLECOES = (
    "features",
    "tasks",
    "taskDependencies",
    "executions",
    "events",
    "taskMessages",
    "conversationTypes",
    "conversations",
    "conversationMessages",
    "actionProposals",
    "deliveryEvents",
    "taskDiffs",
    "automationJobs",
    "markdownDocuments",
    "markdownRevisions",
    "projectMemories",
    "projectMemoryRevisions",
    "projectMemoryProposals",
)
STATUS = {
    "ideia": "pendente",
    "parcial": "pendente",
    "em_andamento": "bloqueada",
    "feito": "concluida",
    "bloqueado": "bloqueada",
    "aguardando_decisao": "bloqueada",
    "cancelada": "cancelada",
}
TIPOS = {"feature", "fix", "chore", "docs", "refactor", "test", "perf", "build", "ci", "revert"}


def escolher(rotulo, opcoes):
    for numero, opcao in enumerate(opcoes, 1):
        print(f"{numero}. {opcao['name']}")
    while True:
        valor = input(f"{rotulo}: ").strip()
        if valor.isdigit() and 1 <= int(valor) <= len(opcoes):
            return opcoes[int(valor) - 1]
        print("Escolha um número da lista.")


def exportar(conn, projeto, repo_padrao):
    origem = f"sync-agents:{projeto['id']}:{projeto['created_at']}"
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, origem)

    def id_de(tipo, valor):
        return str(uuid.uuid5(namespace, f"{tipo}:{valor}"))

    project_id = str(namespace)
    repos = conn.execute(
        "SELECT * FROM project_repos WHERE project_id = ? ORDER BY name, root_sha", (projeto["id"],)
    ).fetchall()
    repositorios = [
        {
            "id": id_de("repo", r["root_sha"]),
            "name": r["name"],
            "url": r["remote"] or "",
            "instructions": f"Commit raiz na origem: {r['root_sha']}\nVinculado em: {r['created_at']}",
        }
        for r in repos
    ]
    features = conn.execute(
        "SELECT f.*, p.email AS creator_email FROM features f JOIN people p ON p.id = f.created_by "
        "WHERE f.project_id = ? ORDER BY f.id",
        (projeto["id"],),
    ).fetchall()
    criador = conn.execute("SELECT email FROM people WHERE id = ?", (projeto["created_by"],)).fetchone()["email"]
    tasks = conn.execute(
        "SELECT t.*, p.email AS owner_email FROM tasks t LEFT JOIN people p ON p.id = t.owner_id "
        "WHERE t.project_id = ? ORDER BY t.id",
        (projeto["id"],),
    ).fetchall()
    eventos = conn.execute(
        "SELECT e.*, p.email AS author_email FROM events e JOIN people p ON p.id = e.author_id "
        "WHERE e.project_id = ? ORDER BY e.seq",
        (projeto["id"],),
    ).fetchall()
    dependencias = conn.execute(
        "SELECT d.* FROM task_dependencies d JOIN tasks t ON t.id = d.task_id "
        "WHERE t.project_id = ? ORDER BY d.task_id, d.depends_on_id",
        (projeto["id"],),
    ).fetchall()
    corpos = {e["task_id"]: e["texto"] for e in eventos if e["kind"] == "body.updated"}
    deps = {t["id"]: [] for t in tasks}
    for d in dependencias:
        if d["depends_on_id"] not in deps:
            raise ValueError("Há uma dependência para uma tarefa de outro projeto.")
        deps[d["task_id"]].append(id_de("task", d["depends_on_id"]))

    dados = {nome: [] for nome in COLECOES}
    dados["project"] = {
        "_id": project_id,
        "name": projeto["name"],
        "description": projeto["description"] or "",
        "instructions": f"Origem: sync-agents/{projeto['slug']}. Status original: {projeto['status']}. "
        f"Criado por: {criador}.",
        "visibility": "private" if projeto["visibility"] == "private" else "public",
        "archived": projeto["status"] == "arquivado",
        "version": 0,
        "eventSequence": 0,
        "repositories": repositorios,
        "areas": ["backend", "frontend", "outro"],
        "createdAt": projeto["created_at"],
        "updatedAt": projeto["updated_at"],
    }
    for f in features:
        dados["features"].append(
            {
                "_id": id_de("feature", f["id"]),
                "projectId": project_id,
                "name": f["title"],
                "objective": f["description"] or "",
                "context": f"Código na origem: {f['code']}\nCriado por: {f['creator_email']}",
                "acceptance": [],
                "version": 0,
                "archived": False,
                "createdAt": f["created_at"],
                "updatedAt": f["updated_at"],
            }
        )
    for t in tasks:
        tags = json.loads(t["tags"])
        areas = {"backend" for tag in tags if tag == "backend"} | {
            "frontend" for tag in tags if tag in ("frontend", "front")
        }
        area = next(iter(areas)) if len(areas) == 1 else "outro"
        tipos = TIPOS.intersection(tags)
        tipo = next(iter(tipos)) if len(tipos) == 1 else "feature"
        instrucoes = f"Código na origem: {t['code']}\nStatus na origem: {t['status']}\nTags: {', '.join(tags)}"
        if corpos.get(t["id"]):
            instrucoes += f"\n\n{corpos[t['id']]}"
        registro = {
            "_id": id_de("task", t["id"]),
            "projectId": project_id,
            "name": t["title"],
            "instructions": instrucoes,
            "acceptance": [],
            "acceptanceProgress": [],
            "priority": 0,
            "area": area,
            "type": tipo,
            "repositoryId": id_de("repo", repo_padrao),
            "dependencies": deps[t["id"]],
            "status": STATUS[t["status"]],
            "checked": False,
            "version": 0,
            "archived": False,
            "createdAt": t["created_at"],
            "updatedAt": t["updated_at"],
        }
        if t["feature_id"] is not None:
            registro["featureId"] = id_de("feature", t["feature_id"])
        if t["owner_email"]:
            registro["responsible"] = t["owner_email"]
        dados["tasks"].append(registro)
    for d in dependencias:
        dados["taskDependencies"].append(
            {
                "_id": id_de("dependency", f"{d['task_id']}:{d['depends_on_id']}"),
                "projectId": project_id,
                "taskId": id_de("task", d["task_id"]),
                "dependencyId": id_de("task", d["depends_on_id"]),
            }
        )
    for e in eventos:
        detalhe = {k: e[k] for k in e.keys() if k not in {"project_id", "author_id", "author_name", "author_email"}}
        if e["task_id"] is not None:
            entidade = id_de("task", e["task_id"])
        elif e["feature_id"] is not None:
            entidade = id_de("feature", e["feature_id"])
        else:
            entidade = project_id
        dados["events"].append(
            {
                "_id": id_de("event", e["seq"]),
                "projectId": project_id,
                "entityId": entidade,
                "action": e["kind"],
                "kind": e["kind"],
                "summary": f"Evento da origem: {e['kind']}",
                "author": e["author_email"],
                "origin": "sync-agents",
                "at": e["created_at"],
                "data": detalhe,
            }
        )
        if e["kind"] == "message.created" and e["task_id"] is not None:
            mensagem = {
                "_id": id_de("message", e["seq"]),
                "projectId": project_id,
                "taskId": id_de("task", e["task_id"]),
                "author": e["author_email"],
                "clientName": e["agent"],
                "type": e["type"],
                "message": e["texto"],
                "references": [],
                "createdAt": e["created_at"],
            }
            if e["agent"] in ("human", "codex", "claude"):
                mensagem["authorType"] = "human" if e["agent"] == "human" else "agent"
            dados["taskMessages"].append(mensagem)
    contagens = {"project": 1, "repositories": len(repositorios)}
    contagens.update({nome: len(dados[nome]) for nome in COLECOES})
    return {
        "format": "project-tasks-export",
        "schemaVersion": 1,
        "exportedAt": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "source": {"projectId": project_id},
        "counts": contagens,
        "data": dados,
        "migrationInstructions": "Importe este pacote pelo importador nativo do Project Tasks MCP. "
        "Confira os avisos e as contagens retornados.",
        "exclusions": ["Credenciais, tokens, permissões, pedidos de acesso e cursores de leitura"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--banco", default=os.environ.get("SYNC_AGENTS_DB", str(Path(__file__).resolve().parents[3] / "sync.db"))
    )
    parser.add_argument("--projeto", help="Slug do projeto")
    parser.add_argument("--repositorio", help="Commit raiz do repositório padrão")
    parser.add_argument("--saida", help="Caminho do JSON gerado")
    args = parser.parse_args()
    caminho = Path(args.banco).resolve()
    if not caminho.is_file():
        raise ValueError(f"Banco não encontrado: {caminho}")
    conn = sqlite3.connect(caminho.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        projetos = conn.execute("SELECT * FROM projects ORDER BY name, id").fetchall()
        if not projetos:
            raise ValueError("Nenhum projeto encontrado.")
        projeto = (
            next((p for p in projetos if p["slug"] == args.projeto), None)
            if args.projeto
            else escolher("Escolha o projeto", projetos)
        )
        if projeto is None:
            raise ValueError("Projeto não encontrado.")
        repos = conn.execute(
            "SELECT * FROM project_repos WHERE project_id = ? ORDER BY name, root_sha", (projeto["id"],)
        ).fetchall()
        if not repos:
            raise ValueError("O projeto não possui repositórios; o destino exige um para cada tarefa.")
        repo = (
            next((r for r in repos if r["root_sha"] == args.repositorio), None)
            if args.repositorio
            else escolher("Escolha o repositório padrão das tarefas", repos)
        )
        if repo is None:
            raise ValueError("Repositório não encontrado no projeto.")
        pacote = exportar(conn, projeto, repo["root_sha"])
        saida = Path(args.saida or f"project-tasks-{projeto['slug']}.json")
        with saida.open("x", encoding="utf-8") as arquivo:
            json.dump(pacote, arquivo, ensure_ascii=False, indent=2)
            arquivo.write("\n")
        print(f"Arquivo criado: {saida.resolve()}")
        print(f"Projeto separado: {pacote['source']['projectId']}")
        print(f"Repositório padrão: {repo['name']}")
        print("Contagens: " + ", ".join(f"{k}={v}" for k, v in pacote["counts"].items() if v))
        print("Confira os textos livres antes de compartilhar. A reimportação não atualiza registros existentes.")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        sys.exit(1)
