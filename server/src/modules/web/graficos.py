"""Séries dos gráficos da web, reconstruídas da trilha de eventos, e o título de
cada gráfico já com a conclusão que ele mostra."""

import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from src.modules.events.relatorio import ROTULO_STATUS
from src.shared.enums import EKindEvent, EStatusTask

ABERTOS = [
    EStatusTask.ideia.value,
    EStatusTask.em_andamento.value,
    EStatusTask.parcial.value,
    EStatusTask.aguardando_decisao.value,
    EStatusTask.bloqueado.value,
]
TRAVADOS = (EStatusTask.aguardando_decisao.value, EStatusTask.bloqueado.value)
SEMANAS = 8
DIAS_COMPARACAO = 42


def _data(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def dias_br(dias: float) -> str:
    """`8,0 dias`, `6 horas`, `30 min`."""
    if dias >= 1:
        return f"{dias:.1f}".replace(".", ",") + (" dia" if round(dias, 1) == 1 else " dias")
    if dias * 24 >= 1:
        return f"{round(dias * 24)} horas"
    return f"{max(1, round(dias * 1440))} min"


def historico_de_status(conn: sqlite3.Connection, projeto_id: int) -> dict[int, list[tuple[datetime, str]]]:
    """Por task, a sequência (instante, status) desde a criação. O status inicial é
    o `valor_de` da primeira mudança, ou o atual quando nunca mudou."""
    linhas = conn.execute(
        f"""SELECT t.id, t.status AS atual, e.kind, e.valor_de, e.valor_para, e.created_at
              FROM tasks t JOIN events e ON e.task_id = t.id
             WHERE t.project_id = ?
               AND (e.kind = '{EKindEvent.task_created}'
                    OR (e.kind = '{EKindEvent.task_field_changed}' AND e.campo = 'status'))
             ORDER BY e.seq""",
        (projeto_id,),
    ).fetchall()
    criacao: dict[int, datetime] = {}
    atual: dict[int, str] = {}
    mudancas: dict[int, list[tuple[datetime, str, str]]] = defaultdict(list)
    for linha in linhas:
        atual[linha["id"]] = linha["atual"]
        if linha["kind"] == EKindEvent.task_created:
            criacao[linha["id"]] = _data(linha["created_at"])
        else:
            mudancas[linha["id"]].append((_data(linha["created_at"]), linha["valor_de"], linha["valor_para"]))
    historico = {}
    for task_id, inicio in criacao.items():
        lista = mudancas[task_id]
        inicial = lista[0][1] if lista else atual[task_id]
        historico[task_id] = [(inicio, inicial)] + [(quando, para) for quando, _, para in lista]
    return historico


def _status_em(passos: list[tuple[datetime, str]], instante: datetime) -> str | None:
    status = None
    for quando, valor in passos:
        if quando > instante:
            break
        status = valor
    return status


def ritmo_semanal(historico: dict[int, list[tuple[datetime, str]]], agora: datetime) -> dict[str, Any]:
    """Concluídas e ciclo mediano por semana (segunda a domingo), as últimas
    `SEMANAS`, com a atual marcada como em curso."""
    segunda = (agora - timedelta(days=agora.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    inicios = [segunda - timedelta(weeks=SEMANAS - 1 - i) for i in range(SEMANAS)]
    concluidas = [0] * SEMANAS
    ciclos: list[list[float]] = [[] for _ in range(SEMANAS)]
    for passos in historico.values():
        primeira = True
        for i, (quando, status) in enumerate(passos):
            if status != EStatusTask.feito.value or (i > 0 and passos[i - 1][1] == EStatusTask.feito.value):
                continue
            semana = (quando - inicios[0]).days // 7
            if 0 <= semana < SEMANAS:
                concluidas[semana] += 1
                if primeira:
                    ciclos[semana].append((quando - passos[0][0]).total_seconds() / 86400)
            primeira = False
    semanas = [
        {
            "rotulo": inicio.strftime("%d/%m"),
            "valor": concluidas[i],
            "ciclo": statistics.median(ciclos[i]) if ciclos[i] else None,
            "em_curso": i == SEMANAS - 1,
        }
        for i, inicio in enumerate(inicios)
    ]
    fechadas = semanas[:-1]
    ultima, anterior = fechadas[-1], fechadas[-2]
    media = sum(s["valor"] for s in fechadas) / len(fechadas)
    for s in semanas:
        s["destaque"] = s is ultima
    titulo = "Tasks concluídas por semana"
    subtitulo = (
        f"{ultima['valor']} na semana de {ultima['rotulo']} · {anterior['valor']} na anterior · média de {media:.0f}"
    )
    return {
        "semanas": semanas,
        "ultima": ultima,
        "anterior": anterior,
        "media": media,
        "titulo": titulo,
        "subtitulo": subtitulo,
    }


def status_comparado(historico: dict[int, list[tuple[datetime, str]]], agora: datetime) -> dict[str, Any]:
    """Tasks abertas por status há `DIAS_COMPARACAO` dias e agora."""
    antes = agora - timedelta(days=DIAS_COMPARACAO)
    cont_antes = Counter(_status_em(p, antes) for p in historico.values())
    cont_agora = Counter(p[-1][1] for p in historico.values())
    linhas = [
        {"status": s, "nome": ROTULO_STATUS[s], "antes": cont_antes.get(s, 0), "agora": cont_agora.get(s, 0)}
        for s in ABERTOS
        if cont_antes.get(s, 0) or cont_agora.get(s, 0)
    ]
    teto = max([1] + [max(linha["antes"], linha["agora"]) for linha in linhas])
    for linha in linhas:
        linha["delta"] = linha["agora"] - linha["antes"]
        linha["pct_antes"] = 85 * linha["antes"] / teto
        linha["pct_agora"] = 85 * linha["agora"] / teto
    return {
        "linhas": linhas,
        "titulo": "Tasks abertas por status",
        "subtitulo": f"{antes:%d/%m} comparado com {agora:%d/%m}",
        "rotulo_antes": f"{antes:%d/%m}",
        "rotulo_agora": f"{agora:%d/%m}",
    }


def tempo_por_status(historico: dict[int, list[tuple[datetime, str]]]) -> dict[str, Any]:
    """Mediana dos períodos já encerrados em cada status aberto."""
    duracoes: dict[str, list[float]] = defaultdict(list)
    for passos in historico.values():
        for (inicio, status), (fim, _) in zip(passos, passos[1:], strict=False):
            if status in ABERTOS:
                duracoes[status].append((fim - inicio).total_seconds() / 86400)
    linhas = sorted(
        (
            {"status": s, "nome": ROTULO_STATUS[s], "dias": statistics.median(v), "n": len(v)}
            for s, v in duracoes.items()
        ),
        key=lambda linha: -linha["dias"],
    )
    for linha in linhas:
        linha["texto"] = dias_br(linha["dias"])
        linha["destaque"] = linha is linhas[0]
    return {"linhas": linhas, "titulo": "Tempo em cada status", "subtitulo": "mediana dos períodos já encerrados"}


def travadas(
    tasks: list[dict[str, Any]], historico: dict[int, list[tuple[datetime, str]]], ids: dict[str, int], agora: datetime
) -> list[dict[str, Any]]:
    """Tasks aguardando decisão ou bloqueadas, da parada há mais tempo à mais recente."""
    itens = []
    for task in tasks:
        if task["status"] not in TRAVADOS:
            continue
        passos = historico.get(ids[task["code"]])
        desde = passos[-1][0] if passos else _data(task["created_at"])
        itens.append({**task, "dias_parada": (agora - desde).days})
    return sorted(itens, key=lambda t: -t["dias_parada"])


def features_travadas(tasks: list[dict[str, Any]], features: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantas tasks travadas cada feature tem, só as que têm alguma."""
    por_feature = Counter(t["feature"]["code"] for t in tasks if t["status"] in TRAVADOS and t["feature"])
    total = sum(1 for t in tasks if t["status"] in TRAVADOS)
    linhas = sorted(
        ({**f, "travadas": por_feature[f["code"]]} for f in features if por_feature.get(f["code"])),
        key=lambda f: -f["travadas"],
    )
    for linha in linhas:
        linha["destaque"] = linha is linhas[0]
    em_features = sum(por_feature.values())
    return {
        "linhas": linhas[:5],
        "titulo": "Tasks travadas por feature",
        "subtitulo": f"{em_features} das {total} travadas estão em features · {total - em_features} fora"
        if total
        else "nenhuma task travada",
        "fora": total - sum(por_feature.values()),
        "sem_travadas": len(features) - len(linhas),
    }


def eventos_por_pessoa(conn: sqlite3.Connection, projeto_id: int, agora: datetime) -> dict[str, Any]:
    """Eventos de cada pessoa nas últimas `SEMANAS` semanas e quando ela apareceu por último."""
    desde = (agora - timedelta(weeks=SEMANAS)).isoformat(timespec="seconds")
    linhas = [
        dict(linha)
        for linha in conn.execute(
            """SELECT pe.alias, pe.name, COUNT(*) AS total, MAX(e.created_at) AS ultimo
                 FROM events e JOIN people pe ON pe.id = e.author_id
                WHERE e.project_id = ? AND e.created_at >= ?
                GROUP BY pe.id ORDER BY total DESC""",
            (projeto_id, desde),
        )
    ]
    soma = sum(linha["total"] for linha in linhas)
    for linha in linhas:
        linha["pct"] = round(100 * linha["total"] / soma) if soma else 0
        dias = (agora - _data(linha["ultimo"])).days
        linha["nota"] = "ativo nos últimos 7 dias" if dias < 7 else f"sem eventos desde {_data(linha['ultimo']):%d/%m}"
        linha["destaque"] = linha is linhas[0]
    return {
        "linhas": linhas,
        "total": soma,
        "titulo": "Eventos por pessoa",
        "subtitulo": f"últimas {SEMANAS} semanas · {soma} eventos",
    }


def evolucao_da_feature(
    historico: dict[int, list[tuple[datetime, str]]], ids: list[int], agora: datetime
) -> dict[str, Any]:
    """Tasks na feature e concluídas no fim de cada semana, desde a primeira task (até 12 semanas)."""
    passos = [historico[i] for i in ids if i in historico]
    if not passos:
        return {
            "semanas": [],
            "titulo": "Concluídas e total de tasks, por semana",
            "subtitulo": "a feature ainda não tem tasks",
        }
    primeira = min(p[0][0] for p in passos)
    n = min(12, max(2, (agora - primeira).days // 7 + 2))
    fins = [agora - timedelta(weeks=n - 1 - i) for i in range(n)]
    semanas = []
    for fim in fins:
        existentes = [p for p in passos if p[0][0] <= fim and _status_em(p, fim) != EStatusTask.cancelada.value]
        semanas.append(
            {
                "rotulo": fim.strftime("%d/%m"),
                "total": len(existentes),
                "feitas": sum(1 for p in existentes if _status_em(p, fim) == EStatusTask.feito.value),
            }
        )
    while len(semanas) > 1 and semanas[0]["total"] == 0:
        semanas.pop(0)
    ultima = semanas[-1]
    ultima_feita = max(
        (
            q
            for p in passos
            for i, (q, s) in enumerate(p)
            if s == EStatusTask.feito.value and (i == 0 or p[i - 1][1] != s)
        ),
        default=None,
    )
    restantes = ultima["total"] - ultima["feitas"]
    teto = max([1] + [s["total"] for s in semanas])
    for s in semanas:
        s["pct_total"] = 100 * s["total"] / teto
        s["pct_feitas"] = 100 * s["feitas"] / s["total"] if s["total"] else 0
    partes = [f"{ultima['feitas']} de {ultima['total']} concluídas"]
    if ultima_feita:
        partes.append(f"última conclusão em {ultima_feita:%d/%m}")
    return {
        "semanas": semanas,
        "titulo": "Concluídas e total de tasks, por semana",
        "subtitulo": " · ".join(partes),
        "restantes": restantes,
        "ultima_feita": ultima_feita,
    }


def resumo_das_etapas(etapas: list[dict[str, Any]]) -> str | None:
    """Título da linha do tempo de uma task: em que status ela passou mais tempo."""
    ate_fechar = [
        e for e in etapas if not (e["atual"] and e["status"] in (EStatusTask.feito.value, EStatusTask.cancelada.value))
    ]
    total = sum(e["segundos"] for e in ate_fechar)
    if not ate_fechar or not total:
        return None
    por_status: dict[str, float] = defaultdict(float)
    for e in ate_fechar:
        por_status[e["status"]] += e["segundos"]
    status, segundos = max(por_status.items(), key=lambda kv: kv[1])
    return f"{round(100 * segundos / total)}% do tempo em {ROTULO_STATUS[status]}"
