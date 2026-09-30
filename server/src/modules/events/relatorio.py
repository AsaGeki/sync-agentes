import sqlite3
from collections import defaultdict
from typing import Any

from src.modules.events import repositorio as eventos_repositorio
from src.modules.events import service as eventos_service
from src.modules.features import repositorio as features_repositorio
from src.modules.features import service as features_service
from src.modules.projects.service import exigir_acesso
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.shared.db import now
from src.shared.enums import EKindEvent

ROTULO_STATUS = {
    "feito": "feito",
    "em_andamento": "em andamento",
    "parcial": "parcial",
    "ideia": "ideia",
    "bloqueado": "bloqueado",
    "aguardando_decisao": "aguardando decisão",
}


def perguntas_abertas(
    conn: sqlite3.Connection, projeto_id: int, tasks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Cada `resposta` fecha a pergunta aberta mais antiga da task: duas perguntas
    em aberto exigem duas respostas pra sumirem daqui."""
    pendentes: list[dict[str, Any]] = []
    for task in tasks:
        linhas = eventos_repositorio.mensagens_da_task(conn, projeto_id, task["code"])
        abertas: list[dict[str, Any]] = []
        for linha in linhas:
            if linha["type"] == "pergunta":
                abertas.append(dict(linha))
            elif linha["type"] == "resposta" and abertas:
                abertas.pop(0)
        pendentes += [{"code": task["code"], **pendente} for pendente in abertas]
    return pendentes


def montar_relatorio(
    conn: sqlite3.Connection, slug: str, person_id: int, desde: int
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    leitura = tasks_repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
    tasks = [
        tasks_service.serializar(conn, t, leitura.get(t["id"]))
        for t in tasks_repositorio.find_all(conn, projeto["id"], None)
    ]
    features = [
        features_service.serializar(conn, f)
        for f in features_repositorio.find_all(conn, projeto["id"])
    ]
    seqs = eventos_repositorio.seqs_do_projeto(conn, projeto["id"], desde)
    crus = [eventos_service.hidratar(conn, seq) for seq in seqs]
    eventos = [eventos_service.envelope(cru) for cru in crus]

    por_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    por_feature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    features_apagadas: list[str] = []
    for evento in eventos:
        if evento.get("task"):
            por_task[evento["task"]].append(evento)
        elif evento["kind"] == EKindEvent.feature_deleted:
            features_apagadas.append(evento["payload"]["code"])
        elif evento.get("feature"):
            por_feature[evento["feature"]].append(evento)

    contagem_status: dict[str, int] = defaultdict(int)
    for task in tasks:
        contagem_status[task["status"]] += 1

    contagem_autor: dict[str, int] = defaultdict(int)
    for cru in crus:
        contagem_autor[eventos_service.assinatura(cru)] += 1

    return {
        "projeto": dict(projeto),
        "tasks": tasks,
        "eventos": eventos,
        "por_task": por_task,
        "features": features,
        "por_feature": por_feature,
        "features_apagadas": features_apagadas,
        "contagem_status": dict(contagem_status),
        "contagem_autor": dict(contagem_autor),
        "perguntas_abertas": perguntas_abertas(conn, projeto["id"], tasks),
        "desde": desde,
        "cursor": eventos[-1]["seq"] if eventos else desde,
    }


def _pontos_git(eventos: list[dict[str, Any]]) -> str:
    """Onde no git a atividade da task aconteceu: branches tocadas e o intervalo
    de commit entre o primeiro e o último evento da janela."""
    branches = sorted({e["git"]["branch"] for e in eventos if e["git"].get("branch")})
    commits = [e["git"]["commit"] for e in eventos if e["git"].get("commit")]
    if not branches and not commits:
        return ""
    partes = []
    if branches:
        partes.append(", ".join(f"`{b}`" for b in branches))
    if commits:
        primeiro, ultimo = commits[0][:7], commits[-1][:7]
        partes.append(primeiro if primeiro == ultimo else f"{primeiro}..{ultimo}")
    return " · ".join(partes)


def _secao_task(
    conn: sqlite3.Connection,
    projeto: dict[str, Any],
    task: dict[str, Any],
    atividade: list[dict[str, Any]],
    com_diff: bool,
) -> list[str]:
    marcadores = [ROTULO_STATUS.get(task["status"], task["status"])]
    if task["tags"]:
        marcadores.append(", ".join(task["tags"]))
    if task["owner"]:
        marcadores.append(f"dono {task['owner']}")
    linhas = [f"### {task['code']} · {task['title']}   `[{' · '.join(marcadores)}]`", ""]

    for evento in atividade:
        if evento["kind"] == EKindEvent.task_field_changed:
            dados = evento["payload"]
            de = eventos_service.linha_curta(dados.get("valor_de")) or "vazio"
            para = eventos_service.linha_curta(dados.get("valor_para")) or "vazio"
            linhas.append(f"- `{dados['campo']}`: {de} → {para}")
        elif evento["kind"] == EKindEvent.diff_published:
            dados = evento["payload"]
            arquivos = ", ".join(f"`{a}`" for a in dados["arquivos"][:6])
            sobra = len(dados["arquivos"]) - 6
            if sobra > 0:
                arquivos += f" (+{sobra})"
            base = (dados.get("base_sha") or "")[:7]
            head = (dados.get("head_sha") or "")[:7]
            linhas.append(f"- diff `{base}..{head}`: {arquivos or 'nenhum arquivo'}")

    pontos = _pontos_git(atividade)
    if pontos:
        linhas.append(f"- git: {pontos}")
    linhas.append("")

    if com_diff:
        versoes = [
            e["payload"]["versao"] for e in atividade if e["kind"] == EKindEvent.body_updated
        ]
        if versoes:
            task_row = tasks_repositorio.find_by_code(conn, projeto["id"], task["code"])
            dados = tasks_service.task_diff(conn, task_row["id"], task["code"], min(versoes) - 1)
            if dados["diff"]:
                linhas += [
                    f"#### Diff do corpo (v{dados['versao_de']} → v{dados['versao_para']})",
                    "",
                    "```diff",
                    dados["diff"].rstrip("\n"),
                    "```",
                    "",
                ]
    return linhas


def relatorio_markdown(conn: sqlite3.Connection, rel: dict[str, Any], com_diff: bool) -> str:
    """Resumo técnico do estado do projeto - tasks agrupadas por feature (as
    avulsas em "Sem feature"), com status/tags/dono atuais, campos que mudaram na
    janela e diff acumulado do corpo. Não narra mensagens
    (mudanca/pergunta/resposta/decisao/bloqueio) nem autoria por evento - quem
    quiser isso usa `formato=json`, que carrega os eventos crus."""
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

    em_andamento = [t for t in rel["tasks"] if t["fazendo_agora"]]
    if em_andamento:
        alvos = ", ".join(
            f"{t['code']} ({t['fazendo_agora']['person']} · {t['fazendo_agora']['agent']})"
            for t in em_andamento
        )
        linhas.append(f"- **Em andamento:** {alvos}")

    bloqueadas = [t for t in rel["tasks"] if t["status"] == "bloqueado"]
    if bloqueadas:
        alvos = ", ".join(f"{t['code']} (dono: {t['owner'] or 'sem dono'})" for t in bloqueadas)
        linhas.append(f"- **Bloqueadas:** {alvos}")

    aguardando = [t for t in rel["tasks"] if t["status"] == "aguardando_decisao"]
    if aguardando:
        alvos = ", ".join(f"{t['code']} (dono: {t['owner'] or 'sem dono'})" for t in aguardando)
        linhas.append(f"- **Aguardando decisão:** {alvos}")

    for feature in rel["features"]:
        progresso = feature["progresso"]
        linhas.append(
            f"- `{feature['code']}` · {ROTULO_STATUS.get(feature['status'], feature['status'])}"
            f" · {progresso['feito']}/{progresso['total']} feito"
        )
    if rel["features_apagadas"]:
        linhas.append(f"- **Features apagadas:** {', '.join(rel['features_apagadas'])}")

    linhas += ["", "---", ""]

    grupos: list[tuple[dict[str, Any] | None, list[dict[str, Any]]]] = [
        (f, [t for t in rel["tasks"] if t["feature"] and t["feature"]["code"] == f["code"]])
        for f in rel["features"]
    ]
    grupos.append((None, [t for t in rel["tasks"] if t["feature"] is None]))

    for feature, tasks in grupos:
        com_atividade = [t for t in tasks if rel["por_task"].get(t["code"])]
        eventos_feature = rel["por_feature"].get(feature["code"], []) if feature else []
        if not com_atividade and not eventos_feature:
            continue

        if feature:
            progresso = feature["progresso"]
            status = ROTULO_STATUS.get(feature["status"], feature["status"])
            linhas += [
                f"## {feature['code']} · {feature['title']}"
                f"   `[{status} · {progresso['feito']}/{progresso['total']} feito]`",
                "",
            ]
        else:
            linhas += ["## Sem feature", ""]

        for evento in eventos_feature:
            if evento["kind"] == EKindEvent.feature_created:
                linhas.append("- feature criada")
            else:
                dados = evento["payload"]
                de = eventos_service.linha_curta(dados.get("valor_de")) or "vazio"
                para = eventos_service.linha_curta(dados.get("valor_para")) or "vazio"
                linhas.append(f"- `{dados['campo']}`: {de} → {para}")
        if eventos_feature:
            linhas.append("")

        for task in com_atividade:
            linhas += _secao_task(conn, projeto, task, rel["por_task"][task["code"]], com_diff)
        linhas += ["---", ""]

    return "\n".join(linhas)
