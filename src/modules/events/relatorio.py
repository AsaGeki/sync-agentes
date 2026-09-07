import sqlite3
from collections import defaultdict
from typing import Any

from src.modules.events import repositorio as eventos_repositorio
from src.modules.events import service as eventos_service
from src.modules.projects import repositorio as projetos_repositorio
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.shared.db import now

ROTULO_STATUS = {
    "feito": "feito",
    "parcial": "parcial",
    "ideia": "ideia",
    "bloqueado": "bloqueado",
    "aguardando_decisao": "aguardando decisão",
}


def montar_relatorio(conn: sqlite3.Connection, slug: str, desde: int) -> dict[str, Any]:
    projeto = projetos_repositorio.find_by_slug(conn, slug)
    tasks = [
        tasks_service.serializar(conn, t)
        for t in tasks_repositorio.find_all(conn, projeto["id"], None)
    ]
    seqs = eventos_repositorio.seqs_do_projeto(conn, projeto["id"], desde)
    eventos = [eventos_service.hidratar(conn, seq) for seq in seqs]

    por_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evento in eventos:
        if evento.get("task_code"):
            por_task[evento["task_code"]].append(evento)

    contagem_status: dict[str, int] = defaultdict(int)
    for task in tasks:
        contagem_status[task["status"]] += 1

    contagem_autor: dict[str, int] = defaultdict(int)
    for evento in eventos:
        contagem_autor[eventos_service.assinatura(evento)] += 1

    # Pergunta em aberto: última mensagem type=pergunta sem nenhuma resposta depois dela.
    perguntas_abertas: list[dict[str, Any]] = []
    for task in tasks:
        linhas = eventos_repositorio.mensagens_da_task(conn, projeto["id"], task["code"])
        pendente = None
        for linha in linhas:
            if linha["type"] == "pergunta":
                pendente = dict(linha)
            elif linha["type"] == "resposta":
                pendente = None
        if pendente:
            perguntas_abertas.append({"code": task["code"], **pendente})

    return {
        "projeto": dict(projeto),
        "tasks": tasks,
        "eventos": eventos,
        "por_task": por_task,
        "contagem_status": dict(contagem_status),
        "contagem_autor": dict(contagem_autor),
        "perguntas_abertas": perguntas_abertas,
        "desde": desde,
        "cursor": eventos[-1]["seq"] if eventos else desde,
    }


def relatorio_markdown(conn: sqlite3.Connection, rel: dict[str, Any], com_diff: bool) -> str:
    """Resumo técnico do estado do projeto - por task, mostra status/tags/dono
    atuais, campos que mudaram na janela e diff acumulado do corpo. Não narra
    mensagens (mudanca/pergunta/resposta/decisao/bloqueio) nem autoria por
    evento - quem quiser isso usa `formato=json`, que carrega os eventos crus."""
    projeto = rel["projeto"]
    linhas: list[str] = [
        f"# Relatório — {projeto['name']} (`{projeto['slug']}`)",
        "",
        f"Gerado em {now()} · janela de eventos {rel['desde']} → {rel['cursor']}",
        "",
        "## Resumo geral",
        "",
    ]

    total = len(rel["tasks"])
    resumo = " · ".join(
        f"{n} {ROTULO_STATUS.get(s, s)}" for s, n in sorted(rel["contagem_status"].items())
    )
    linhas.append(f"- **{total} tasks**: {resumo}" if total else "- Nenhuma task cadastrada")

    bloqueadas = [t for t in rel["tasks"] if t["status"] == "bloqueado"]
    if bloqueadas:
        alvos = ", ".join(f"{t['code']} (dono: {t['owner'] or 'sem dono'})" for t in bloqueadas)
        linhas.append(f"- **Bloqueadas:** {alvos}")

    aguardando = [t for t in rel["tasks"] if t["status"] == "aguardando_decisao"]
    if aguardando:
        alvos = ", ".join(f"{t['code']} (dono: {t['owner'] or 'sem dono'})" for t in aguardando)
        linhas.append(f"- **Aguardando decisão:** {alvos}")

    linhas += ["", "---", ""]

    for task in rel["tasks"]:
        atividade = rel["por_task"].get(task["code"], [])
        if not atividade:
            continue

        marcadores = [ROTULO_STATUS.get(task["status"], task["status"])]
        if task["tags"]:
            marcadores.append(", ".join(task["tags"]))
        if task["owner"]:
            marcadores.append(f"dono {task['owner']}")
        linhas += [
            f"## {task['code']} · {task['title']}   `[{' · '.join(marcadores)}]`",
            "",
        ]

        for evento in atividade:
            if evento["kind"] == "campo":
                de = evento.get("valor_de", "vazio")
                para = evento.get("valor_para", "vazio")
                linhas.append(f"- `{evento['campo']}`: {de} → {para}")
        linhas.append("")

        if com_diff:
            versoes = [e["version"] for e in atividade if e["kind"] == "corpo"]
            if versoes:
                task_row = tasks_repositorio.find_by_code(conn, projeto["id"], task["code"])
                dados = tasks_service.task_diff(
                    conn, task_row["id"], task["code"], min(versoes) - 1
                )
                if dados["diff"]:
                    linhas += [
                        f"### Diff do corpo (v{dados['versao_de']} → v{dados['versao_para']})",
                        "",
                        "```diff",
                        dados["diff"].rstrip("\n"),
                        "```",
                        "",
                    ]
        linhas += ["---", ""]

    return "\n".join(linhas)
