import sqlite3
from collections import defaultdict
from typing import Any

from app.db import agora
from app.eventos.service import assinatura, hidratar_evento
from app.projetos.service import buscar_projeto
from app.tasks.service import diff_da_task, serializar_task

ROTULO_STATUS = {
    "feito": "feito",
    "parcial": "parcial",
    "ideia": "ideia",
    "bloqueado": "bloqueado",
    "aguardando_decisao": "aguardando decisao",
}


def montar_relatorio(conn: sqlite3.Connection, slug: str, desde: int) -> dict[str, Any]:
    projeto = buscar_projeto(conn, slug)
    tasks = [
        serializar_task(conn, t)
        for t in conn.execute(
            "SELECT * FROM tasks WHERE projeto_id = ? ORDER BY codigo", (projeto["id"],)
        )
    ]
    eventos = [
        hidratar_evento(conn, r["seq"])
        for r in conn.execute(
            "SELECT seq FROM eventos WHERE projeto_id = ? AND seq > ? ORDER BY seq",
            (projeto["id"], desde),
        )
    ]
    por_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for evento in eventos:
        if evento.get("task_codigo"):
            por_task[evento["task_codigo"]].append(evento)

    contagem_status: dict[str, int] = defaultdict(int)
    for task in tasks:
        contagem_status[task["status"]] += 1

    contagem_autor: dict[str, int] = defaultdict(int)
    for evento in eventos:
        contagem_autor[assinatura(evento)] += 1

    # Pergunta em aberto: ultima mensagem tipo=pergunta sem nenhuma resposta depois dela.
    perguntas_abertas: list[dict[str, Any]] = []
    for task in tasks:
        linhas = conn.execute(
            """SELECT e.seq, e.tipo, e.texto, e.criado_em, a.nome AS autor_nome,
                      a.tipo AS autor_tipo, r.nome AS autor_responsavel
                 FROM eventos e
                 JOIN autores a ON a.id = e.autor_id
                 LEFT JOIN autores r ON r.id = a.responsavel_id
                 JOIN tasks t ON t.id = e.task_id
                WHERE t.codigo = ? AND t.projeto_id = ? AND e.kind = 'mensagem'
                ORDER BY e.seq""",
            (task["codigo"], projeto["id"]),
        ).fetchall()
        pendente = None
        for linha in linhas:
            if linha["tipo"] == "pergunta":
                pendente = dict(linha)
            elif linha["tipo"] == "resposta":
                pendente = None
        if pendente:
            perguntas_abertas.append({"codigo": task["codigo"], **pendente})

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
    projeto = rel["projeto"]
    linhas: list[str] = [
        f"# Relatorio — {projeto['nome']} (`{projeto['slug']}`)",
        "",
        f"Gerado em {agora()} · janela de eventos {rel['desde']} → {rel['cursor']}",
        "",
        "## Resumo geral",
        "",
    ]

    total = len(rel["tasks"])
    resumo = " · ".join(
        f"{n} {ROTULO_STATUS.get(s, s)}" for s, n in sorted(rel["contagem_status"].items())
    )
    linhas.append(f"- **{total} tasks**: {resumo}" if total else "- Nenhuma task cadastrada")
    linhas.append(f"- **{len(rel['eventos'])} eventos** na janela")

    if rel["contagem_autor"]:
        autores = " · ".join(f"{nome} {n}" for nome, n in sorted(rel["contagem_autor"].items()))
        linhas.append(f"- Quem mexeu: {autores}")

    bloqueadas = [t for t in rel["tasks"] if t["status"] == "bloqueado"]
    if bloqueadas:
        alvos = ", ".join(f"{t['codigo']} (dono: {t['dono'] or 'sem dono'})" for t in bloqueadas)
        linhas.append(f"- **Bloqueadas:** {alvos}")

    aguardando = [t for t in rel["tasks"] if t["status"] == "aguardando_decisao"]
    if aguardando:
        alvos = ", ".join(f"{t['codigo']} (dono: {t['dono'] or 'sem dono'})" for t in aguardando)
        linhas.append(f"- **Aguardando decisao:** {alvos}")

    if rel["perguntas_abertas"]:
        linhas.append("- **Perguntas sem resposta:**")
        for pergunta in rel["perguntas_abertas"]:
            primeira = pergunta["texto"].splitlines()[0]
            linhas.append(f"  - {pergunta['codigo']} · {assinatura(pergunta)}: {primeira}")

    linhas += ["", "---", ""]

    for task in rel["tasks"]:
        atividade = rel["por_task"].get(task["codigo"], [])
        if not atividade:
            continue

        marcadores = [ROTULO_STATUS.get(task["status"], task["status"])]
        if task["etiquetas"]:
            marcadores.append(", ".join(task["etiquetas"]))
        if task["dono"]:
            marcadores.append(f"dono {task['dono']}")
        linhas += [
            f"## {task['codigo']} · {task['titulo']}   `[{' · '.join(marcadores)}]`",
            "",
        ]

        relacoes = []
        if task["depende"]:
            relacoes.append(f"depende de: {', '.join(task['depende'])}")
        if task["bloqueia"]:
            relacoes.append(f"bloqueia: {', '.join(task['bloqueia'])}")
        if relacoes:
            linhas += ["  ·  ".join(relacoes), ""]

        linhas += ["### Atividade", ""]
        for evento in atividade:
            hora = evento["criado_em"][11:16]
            quem = assinatura(evento)
            if evento["kind"] == "mensagem":
                linhas.append(f"- `{hora}` **{quem}** · {evento['tipo']}")
                for texto in evento["texto"].splitlines():
                    linhas.append(f"    {texto}")
            elif evento["kind"] == "campo":
                de = evento.get("valor_de", "vazio")
                para = evento.get("valor_para", "vazio")
                linhas.append(f"- `{hora}` **{quem}** · campo `{evento['campo']}`: {de} → {para}")
            elif evento["kind"] == "corpo":
                linhas.append(f"- `{hora}` **{quem}** · corpo atualizado (v{evento['versao']})")
            elif evento["kind"] == "dependencia":
                alvo = evento["valor_para"]
                linhas.append(f"- `{hora}` **{quem}** · passou a depender de {alvo}")
            elif evento["kind"] == "task_criada":
                linhas.append(f"- `{hora}` **{quem}** · task criada")
        linhas.append("")

        if com_diff:
            versoes = [e["versao"] for e in atividade if e["kind"] == "corpo"]
            if versoes:
                task_id = conn.execute(
                    "SELECT id FROM tasks WHERE projeto_id = ? AND codigo = ?",
                    (projeto["id"], task["codigo"]),
                ).fetchone()["id"]
                dados = diff_da_task(conn, task_id, task["codigo"], min(versoes) - 1)
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
