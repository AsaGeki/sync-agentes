"""Agregações que só a interface web usa: painel do projeto, cards entre
projetos e o gráfico de atividade (geometria SVG pronta pro template)."""

import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from src.modules.events.relatorio import perguntas_abertas
from src.modules.features import repositorio as features_repositorio
from src.modules.features import service as features_service
from src.modules.projects import repositorio as projects_repositorio
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.modules.web.templating import ROTULO_AGENT
from src.shared.enums import EStatusTask

ORDEM_STATUS = [s.value for s in EStatusTask]
PEDEM_ATENCAO = (EStatusTask.bloqueado.value, EStatusTask.aguardando_decisao.value)


def painel(conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None) -> dict[str, Any]:
    tasks = tasks_service.filtrar_tasks(conn, projeto, person_id, None, None)
    contagem = Counter(t["status"] for t in tasks)
    return {
        "total_tasks": len(tasks),
        "feitas": contagem[EStatusTask.feito.value],
        "contagem_status": [(s, contagem[s]) for s in ORDEM_STATUS],
        "features": [
            features_service.serializar(conn, f)
            for f in features_repositorio.find_all(conn, projeto["id"])
        ],
        "atencao": [t for t in tasks if t["status"] in PEDEM_ATENCAO],
        "perguntas_abertas": perguntas_abertas(conn, projeto["id"], tasks),
        "membros": [dict(m) for m in projects_repositorio.membros_do_projeto(conn, projeto["id"])],
        "repos": [dict(r) for r in projects_repositorio.repos_do_projeto(conn, projeto["id"])],
        "nao_lidos": sum(t.get("nao_lidos", 0) for t in tasks) if person_id is not None else None,
    }


def projetos_da_pessoa(conn: sqlite3.Connection, person_id: int) -> list[sqlite3.Row]:
    return [p for p in projects_repositorio.find_all(conn, person_id) if p["role"] is not None]


def todos_projetos(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def cards(
    conn: sqlite3.Connection, projetos: list[sqlite3.Row], person_id: int | None
) -> list[dict[str, Any]]:
    """Resumo de cada projeto pra visão entre projetos."""
    resultado = []
    for projeto in projetos:
        tasks = [dict(t) for t in tasks_repositorio.find_all(conn, projeto["id"], None)]
        contagem = Counter(t["status"] for t in tasks)
        ultimo = conn.execute(
            "SELECT MAX(created_at) AS ultimo FROM events WHERE project_id = ?", (projeto["id"],)
        ).fetchone()["ultimo"]
        card = {
            "slug": projeto["slug"],
            "name": projeto["name"],
            "description": projeto["description"],
            "status": projeto["status"],
            "visibility": projeto["visibility"],
            "total_tasks": len(tasks),
            "feitas": contagem[EStatusTask.feito.value],
            "atencao": sum(contagem[s] for s in PEDEM_ATENCAO),
            "perguntas_abertas": len(perguntas_abertas(conn, projeto["id"], tasks)),
            "membros": len(projects_repositorio.membros_do_projeto(conn, projeto["id"])),
            "ultima_atividade": ultimo,
            "nao_lidos": None,
        }
        if person_id is not None:
            leitura = tasks_repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
            card["nao_lidos"] = sum(marca["nao_lidos"] for marca in leitura.values())
        resultado.append(card)
    return resultado


# ---------- gráfico de atividade ---------- #

DIAS_ATIVIDADE = 56
# Uma cor por pessoa até esgotar a paleta categórica (8); daí pra frente, "outros".
MAX_PESSOAS = 8
ORDEM_AGENT = ["human", "claude", "codex", "outro"]
# Cor segue a entidade: cada agent tem a sua fixa, `outro` é o cinza de "resto".
CLASSE_AGENT = {"human": "s1", "claude": "s2", "codex": "s3", "outro": "s-resto"}

LARGURA = 720
ALTURA = 180
ESQUERDA = 36
DIREITA = 20
TOPO = 8
BASE = 22
GAP = 2
LARGURA_MAX_BARRA = 24


def _passo_eixo(maximo: int) -> int:
    """Passo "redondo" (1, 2, 5 × 10^n) pra ~4 marcas no eixo."""
    bruto = max(maximo / 4, 1)
    ordem = 10 ** math.floor(math.log10(bruto))
    return int(next(m * ordem for m in (1, 2, 5, 10) if m * ordem >= bruto))


def _barra_arredondada(x: float, y: float, largura: float, altura: float) -> str:
    """Retângulo com só os cantos de cima arredondados (ponta do dado)."""
    r = min(3, largura / 2, altura)
    return (
        f"M{x:.1f},{y + altura:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
        f" H{x + largura - r:.1f} Q{x + largura:.1f},{y:.1f} {x + largura:.1f},{y + r:.1f}"
        f" V{y + altura:.1f} Z"
    )


def _ordem_pessoas(conn: sqlite3.Connection, projeto_id: int) -> list[str]:
    """Aliases na ordem em que cada um escreveu pela primeira vez no projeto.
    Quem chega depois entra no fim, então a cor de ninguém muda."""
    return [
        linha["alias"]
        for linha in conn.execute(
            """SELECT pe.alias FROM events e JOIN people pe ON pe.id = e.author_id
                WHERE e.project_id = ? GROUP BY e.author_id ORDER BY MIN(e.seq)""",
            (projeto_id,),
        )
    ]


def _series(
    por: str, por_dia: dict[str, Counter], ordem_pessoas: list[str]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Séries com atividade na janela e de qual série bruta cada uma vem. A cor
    sai da posição fixa da entidade, não do volume na janela."""
    totais: Counter = Counter()
    for contagem in por_dia.values():
        totais.update(contagem)
    if por == "agent":
        presentes = [a for a in ORDEM_AGENT if totais[a]]
        series = [{"chave": a, "rotulo": ROTULO_AGENT[a], "classe": CLASSE_AGENT[a]} for a in presentes]
        return series, {a: a for a in presentes}
    com_cor = ordem_pessoas[:MAX_PESSOAS]
    series = [
        {"chave": alias, "rotulo": alias, "classe": f"s{i + 1}"}
        for i, alias in enumerate(com_cor)
        if totais[alias]
    ]
    destino = {alias: alias for alias in com_cor}
    resto = [alias for alias in totais if alias not in destino]
    if resto:
        series.append({"chave": "_outros", "rotulo": "outros", "classe": "s-resto"})
        destino.update({alias: "_outros" for alias in resto})
    return series, destino


def atividade(conn: sqlite3.Connection, projeto_id: int, por: str) -> dict[str, Any]:
    """Eventos por dia nas últimas `DIAS_ATIVIDADE`, empilhados por pessoa ou por
    agent. `created_at` guarda o offset local, então o dia já sai no fuso de quem
    escreveu."""
    hoje = date.today()
    dias = [(hoje - timedelta(days=DIAS_ATIVIDADE - 1 - i)).isoformat() for i in range(DIAS_ATIVIDADE)]
    coluna = {"pessoa": "pe.alias", "agent": "e.agent"}[por]
    linhas = conn.execute(
        f"""SELECT substr(e.created_at, 1, 10) AS dia, {coluna} AS serie, COUNT(*) AS n
              FROM events e JOIN people pe ON pe.id = e.author_id
             WHERE e.project_id = ? AND substr(e.created_at, 1, 10) >= ?
             GROUP BY dia, serie""",
        (projeto_id, dias[0]),
    ).fetchall()
    brutos: dict[str, Counter] = defaultdict(Counter)
    for linha in linhas:
        brutos[linha["dia"]][linha["serie"]] += linha["n"]

    series, destino = _series(por, brutos, _ordem_pessoas(conn, projeto_id))
    por_dia: dict[str, Counter] = defaultdict(Counter)
    for dia, contagem in brutos.items():
        for serie, n in contagem.items():
            por_dia[dia][destino[serie]] += n

    maximo = max((sum(c.values()) for c in por_dia.values()), default=0)
    passo = _passo_eixo(maximo)
    teto = max(passo * math.ceil(maximo / passo), passo)
    altura_plot = ALTURA - TOPO - BASE
    largura_plot = LARGURA - ESQUERDA - DIREITA
    fatia = largura_plot / DIAS_ATIVIDADE
    largura_barra = min(fatia - GAP, LARGURA_MAX_BARRA)
    base_y = TOPO + altura_plot

    colunas = []
    for i, dia in enumerate(dias):
        contagem = por_dia.get(dia, Counter())
        x = ESQUERDA + i * fatia + (fatia - largura_barra) / 2
        segmentos = []
        cursor = base_y
        visiveis = [s for s in series if contagem[s["chave"]]]
        for j, serie in enumerate(visiveis):
            altura = contagem[serie["chave"]] / teto * altura_plot
            fundo = cursor - (GAP if j else 0)
            altura_util = max(altura - (GAP if j else 0), 1)
            topo = fundo - altura_util
            if j == len(visiveis) - 1:
                d = _barra_arredondada(x, topo, largura_barra, altura_util)
            else:
                d = f"M{x:.1f},{fundo:.1f} V{topo:.1f} H{x + largura_barra:.1f} V{fundo:.1f} Z"
            segmentos.append({"classe": serie["classe"], "d": d})
            cursor = fundo - altura_util
        total = sum(contagem.values())
        detalhe = ", ".join(f"{s['rotulo']} {contagem[s['chave']]}" for s in visiveis)
        colunas.append(
            {
                "dia": dia,
                "x": ESQUERDA + i * fatia,
                "largura": fatia,
                "segmentos": segmentos,
                "titulo": f"{date.fromisoformat(dia):%d/%m}: {total} evento(s)"
                + (f" - {detalhe}" if detalhe else ""),
                "rotulo": f"{date.fromisoformat(dia):%d/%m}" if (DIAS_ATIVIDADE - 1 - i) % 7 == 0 else None,
                "centro": x + largura_barra / 2,
                "valores": [contagem[s["chave"]] for s in series],
                "total": total,
            }
        )

    return {
        "por": por,
        "series": series,
        "colunas": colunas,
        "ticks": [
            {"valor": v, "y": base_y - v / teto * altura_plot} for v in range(0, teto + 1, passo)
        ],
        "total": sum(c["total"] for c in colunas),
        "largura": LARGURA,
        "altura": ALTURA,
        "esquerda": ESQUERDA,
        "fim_x": LARGURA - DIREITA,
        "base_y": base_y,
    }
