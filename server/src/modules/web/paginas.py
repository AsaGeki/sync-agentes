"""Contexto das páginas de projeto, igual pra pessoa e pra admin. `person_id=None`
é a leitura de admin: sem não lidos, sem marcar lido, sem formulário."""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from src.modules.events import etapas as etapas_service
from src.modules.events import service as eventos_service
from src.modules.events.relatorio import ROTULO_STATUS, perguntas_abertas
from src.modules.features import repositorio as features_repositorio
from src.modules.features import service as features_service
from src.modules.projects import repositorio as projects_repositorio
from src.modules.tasks import repositorio as tasks_repositorio
from src.modules.tasks import service as tasks_service
from src.modules.web import indicadores
from src.modules.web.templating import ROTULO_AGENT, code_curto, parada
from src.shared import codes
from src.shared.enums import EKindEvent, EStatusTask, ETypeMessage

SEM_FEATURE = "_sem"
PERIODOS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
ROTULO_PERIODO = {"24h": "últimas 24h", "7d": "últimos 7 dias", "30d": "últimos 30 dias"}
ROTULO_ORDEM = {"code": "code", "recentes": "mais recentes", "status": "fluxo de status"}
# As chaves são as de `events.repositorio.CONDICAO_TIPO`.
ROTULO_TIPO = {
    "mensagem": "mensagens",
    "status": "mudanças de status",
    "campo": "outros campos",
    "corpo": "corpo",
    "diff": "diffs",
    "criacao": "tasks criadas",
    "feature": "features",
}
TAMANHO_FEED = 50
# Ordem das tasks abertas numa feature: o que está sendo feito ou travado primeiro.
ORDEM_ABERTAS = ["em_andamento", "bloqueado", "aguardando_decisao", "parcial", "ideia"]
# Status que uma feature pode ter: 'aguardando_decisao' só existe em task.
FEATURE_STATUSES = ["ideia", "em_andamento", "parcial", "feito", "bloqueado"]
# Mensagens (ou eventos de sistema) seguidos do mesmo autor dentro desta janela
# viram um bloco só na conversa.
JANELA_GRUPO = timedelta(minutes=10)


def _base(person_id: int | None) -> dict[str, Any]:
    admin = person_id is None
    return {"base": "/web/admin" if admin else "/web", "admin": admin}


def ctx_nav(conn: sqlite3.Connection, person_id: int | None) -> list[dict[str, Any]]:
    """Projetos da barra lateral: os da pessoa (com não lidos) ou todos, pro admin."""
    if person_id is None:
        return [{"slug": p["slug"], "name": p["name"], "nao_lidos": 0} for p in indicadores.todos_projetos(conn)]
    itens = []
    for projeto in sorted(indicadores.projetos_da_pessoa(conn, person_id), key=lambda p: p["name"]):
        leitura = tasks_repositorio.leitura_do_projeto(conn, projeto["id"], person_id)
        itens.append(
            {
                "slug": projeto["slug"],
                "name": projeto["name"],
                "nao_lidos": sum(marca["nao_lidos"] for marca in leitura.values()),
            }
        )
    return itens


def ctx_painel(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, por: str
) -> dict[str, Any]:
    return {
        **_base(person_id),
        "aba": "painel",
        "projeto": projeto,
        "painel": indicadores.painel(conn, projeto, person_id),
        "grafico": indicadores.atividade(conn, projeto["id"], por),
    }


def _aplicar_filtros(
    conn: sqlite3.Connection, projeto: sqlite3.Row, tasks: list[dict[str, Any]], f: dict[str, Any]
) -> list[dict[str, Any]]:
    """Filtros da tela que não existem em `filtrar_tasks` (REST/MCP não os têm)."""
    if f["status"]:
        tasks = [t for t in tasks if t["status"] in f["status"]]
    if f["dono"]:
        tasks = [t for t in tasks if t["owner_id"] == int(f["dono"])]
    if f["sem_dono"]:
        tasks = [t for t in tasks if t["owner_id"] is None]
    if f["fazendo"]:
        tasks = [t for t in tasks if t["fazendo_agora"]]
    if f["paradas"]:
        tasks = [t for t in tasks if t["fazendo_agora"] and parada(t["updated_at"])]
    if f["atencao"]:
        com_pergunta = {p["code"] for p in perguntas_abertas(conn, projeto["id"], tasks)}
        tasks = [
            t for t in tasks if t["status"] in indicadores.PEDEM_ATENCAO or t["code"] in com_pergunta
        ]
    if f["periodo"]:
        corte = datetime.now().astimezone() - PERIODOS[f["periodo"]]
        tasks = [t for t in tasks if datetime.fromisoformat(t["updated_at"]) >= corte]
    return tasks


def _ordenar(tasks: list[dict[str, Any]], ordem: str) -> list[dict[str, Any]]:
    """`filtrar_tasks` já devolve por code; as outras ordens partem dela."""
    if ordem == "recentes":
        return sorted(tasks, key=lambda t: datetime.fromisoformat(t["updated_at"]), reverse=True)
    if ordem == "status":
        fluxo = {s.value: i for i, s in enumerate(EStatusTask)}
        return sorted(tasks, key=lambda t: fluxo[t["status"]])
    return tasks


def _rotulos_ativos(f: dict[str, Any], membros: list[sqlite3.Row]) -> list[str]:
    """Um rótulo por filtro em uso, pra barra acima da lista."""
    ativos = [f"busca \u201c{f['q']}\u201d"] if f["q"] else []
    ativos += [ROTULO_STATUS[s] for s in f["status"]]
    for chave, rotulo in (
        ("fazendo", "fazendo agora"),
        ("atencao", "precisam de atenção"),
        ("paradas", "paradas"),
        ("nao_lidas", "não lidas"),
        ("sem_dono", "sem dono"),
    ):
        if f[chave]:
            ativos.append(rotulo)
    if f["dono"]:
        ativos.append("dono " + next((m["name"] for m in membros if m["id"] == int(f["dono"])), f["dono"]))
    if f["feature"] == SEM_FEATURE:
        ativos.append("sem feature")
    elif f["feature"]:
        ativos.append(f"feature {code_curto(f['feature'])}")
    if f["tag"]:
        ativos.append(f"tag {f['tag']}")
    if f["periodo"]:
        ativos.append(ROTULO_PERIODO[f["periodo"]])
    return ativos


def _agrupar_por_feature(
    conn: sqlite3.Connection, projeto: sqlite3.Row, tasks: list[dict[str, Any]], filtrado: bool
) -> list[dict[str, Any]]:
    """Uma seção por feature, com o resumo dela, e as avulsas por último. Com
    filtro ativo, seção sem task some."""
    grupos = []
    for feature in indicadores.lista_de_features(conn, projeto["id"])["features"]:
        do_grupo = [t for t in tasks if t["feature"] and t["feature"]["code"] == feature["code"]]
        if do_grupo or not filtrado:
            grupos.append({"feature": feature, "tasks": do_grupo})
    avulsas = [t for t in tasks if t["feature"] is None]
    if avulsas:
        grupos.append({"feature": None, "tasks": avulsas})
    return grupos


def ctx_tasks(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, f: dict[str, Any]
) -> dict[str, Any]:
    """`f` vem de `web.filtros.filtros_tasks`."""
    f = {**f, "nao_lidas": f["nao_lidas"] and person_id is not None}
    feature = f["feature"]
    todas = tasks_repositorio.find_all(conn, projeto["id"], None)
    tasks = tasks_service.filtrar_tasks(
        conn,
        projeto,
        person_id,
        None,
        f["tag"] or None,
        f["q"] or None,
        f["nao_lidas"],
        feature if feature and feature != SEM_FEATURE else None,
        feature == SEM_FEATURE,
    )
    tasks = _ordenar(_aplicar_filtros(conn, projeto, tasks, f), f["ordem"])
    statuses = [s.value for s in EStatusTask]
    membros = projects_repositorio.membros_do_projeto(conn, projeto["id"])
    ativos = _rotulos_ativos(f, membros)
    camadas = f["agrupar"] == "feature" and f["visao"] == "lista"
    return {
        **_base(person_id),
        "aba": "tasks",
        "projeto": projeto,
        "tasks": tasks,
        "colunas": [(s, [t for t in tasks if t["status"] == s]) for s in statuses],
        "features": features_repositorio.find_all(conn, projeto["id"]),
        "membros": membros,
        "tags": sorted({tag for linha in todas for tag in json.loads(linha["tags"])}),
        "statuses": statuses,
        "filtros": f,
        "ativos": ativos,
        "grupos": _agrupar_por_feature(conn, projeto, tasks, bool(ativos)) if camadas else None,
        "total_geral": len(todas),
        "periodos": ROTULO_PERIODO,
        "ordens": ROTULO_ORDEM,
        "SEM_FEATURE": SEM_FEATURE,
    }


def ctx_features(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, status: str
) -> dict[str, Any]:
    """`status` filtra pelo status derivado da feature; vazio traz todas, da
    mais recentemente ativa pra mais antiga."""
    dados = indicadores.lista_de_features(conn, projeto["id"])
    features = sorted(dados["features"], key=lambda f: f["ultimo"], reverse=True)
    if status:
        features = [f for f in features if f["status"] == status]
    return {
        **_base(person_id),
        "aba": "features",
        "projeto": projeto,
        "features": features,
        "avulsas": dados["avulsas"],
        "filtro_status": status,
        "statuses": FEATURE_STATUSES,
        "ordem_status": [s.value for s in EStatusTask],
        "SEM_FEATURE": SEM_FEATURE,
    }


def ctx_feature(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, code: str
) -> dict[str, Any]:
    linha = features_repositorio.find_by_code(conn, projeto["id"], code)
    feature = features_service.serializar(conn, linha)
    tasks = tasks_service.filtrar_tasks(conn, projeto, person_id, None, None, None, False, feature["code"], False)
    abertas = sorted(
        (t for t in tasks if t["status"] != EStatusTask.feito.value),
        key=lambda t: ORDEM_ABERTAS.index(t["status"]),
    )
    return {
        **_base(person_id),
        "aba": "feature",
        "projeto": projeto,
        "feature": feature,
        "abertas": abertas,
        "feitas": [t for t in tasks if t["status"] == EStatusTask.feito.value],
        "participantes": indicadores.participantes_por_feature(conn, projeto["id"]).get(feature["code"], []),
        "eventos": eventos_service.feed_do_projeto(conn, projeto["id"], 10, feature=feature["code"])["eventos"],
        "nomes": nomes_das_pessoas(conn),
        "ordem_status": [s.value for s in EStatusTask],
    }


def nomes_das_pessoas(conn: sqlite3.Connection) -> dict[str, str]:
    return {str(linha["id"]): linha["name"] for linha in conn.execute("SELECT id, name FROM people")}


def ctx_atividade(
    conn: sqlite3.Connection, projeto: sqlite3.Row, person_id: int | None, f: dict[str, Any]
) -> dict[str, Any]:
    """`f` vem de `web.filtros.filtros_atividade`."""
    task_id = None
    if f["task"]:
        achada = codes.buscar_por_code(conn, "tasks", projeto["id"], f["task"], "T")
        # Code que não existe não casa com nenhum evento: feed vazio.
        task_id = achada["id"] if achada else -1
    desde = (
        (datetime.now().astimezone() - PERIODOS[f["periodo"]]).isoformat(timespec="seconds")
        if f["periodo"]
        else None
    )
    pagina = eventos_service.feed_do_projeto(
        conn,
        projeto["id"],
        TAMANHO_FEED,
        antes=f["antes"],
        pessoa=f["pessoa"] or None,
        agent=f["agent"] or None,
        tipo=f["tipo"] or None,
        task_id=task_id,
        feature=f["feature"] or None,
        desde=desde,
    )
    return {
        **_base(person_id),
        "aba": "atividade",
        "projeto": projeto,
        **pagina,
        "filtros": f,
        "consulta": urlencode({k: v for k, v in f.items() if v and k != "antes"}),
        "membros": projects_repositorio.membros_do_projeto(conn, projeto["id"]),
        "features": features_repositorio.find_all(conn, projeto["id"]),
        "nomes": nomes_das_pessoas(conn),
        "agents": ROTULO_AGENT,
        "tipos": ROTULO_TIPO,
        "periodos": ROTULO_PERIODO,
    }


def linha_do_tempo(eventos: list[dict[str, Any]], abertas: set[int]) -> list[dict[str, Any]]:
    """Eventos da task em blocos pra conversa: separador por dia, mensagens
    seguidas do mesmo autor juntas, eventos de sistema condensados juntos e
    cada diff num bloco próprio."""
    blocos: list[dict[str, Any]] = []
    dia_atual = None
    for evento in eventos:
        dia = evento["created_at"][:10]
        if dia != dia_atual:
            blocos.append({"tipo": "dia", "dia": dia})
            dia_atual = dia
        momento = datetime.fromisoformat(evento["created_at"])
        if evento["kind"] == EKindEvent.message_created:
            tipo = "mensagens"
        elif evento["kind"] == EKindEvent.diff_published:
            tipo = "diff"
        else:
            tipo = "sistema"
        autor = (evento["actor"]["person"], evento["actor"]["agent"])
        item = {**evento, "aberta": evento["seq"] in abertas}
        ultimo = blocos[-1]
        if (
            tipo != "diff"
            and ultimo["tipo"] == tipo
            and ultimo["autor"] == autor
            and momento - ultimo["fim"] <= JANELA_GRUPO
        ):
            ultimo["itens"].append(item)
            ultimo["fim"] = momento
        else:
            blocos.append(
                {
                    "tipo": tipo,
                    "autor": autor,
                    "actor": evento["actor"],
                    "inicio": evento["created_at"],
                    "fim": momento,
                    "itens": [item],
                }
            )
    return blocos


def ctx_task(
    conn: sqlite3.Connection, projeto: sqlite3.Row, code: str, person_id: int | None
) -> dict[str, Any]:
    task = tasks_service.montar_task(conn, projeto, code, person_id, com_corpo=True, marcar_lida=False)
    eventos = task["eventos"]
    abertas = {p["seq"] for p in perguntas_abertas(conn, projeto["id"], [task])}

    participantes: dict[str, dict[str, Any]] = {}
    for evento in eventos:
        ator = evento["actor"]
        dados = participantes.setdefault(ator["person"], {"person": ator["person"], "name": ator["name"], "agents": []})
        if ator["agent"] not in dados["agents"]:
            dados["agents"].append(ator["agent"])

    corpos = [e for e in eventos if e["kind"] == EKindEvent.body_updated]
    etapas = etapas_service.etapas_da_task(
        eventos, task["status"], datetime.now(datetime.fromisoformat(task["created_at"]).tzinfo)
    )
    return {
        **_base(person_id),
        "aba": "task",
        "projeto": projeto,
        "task": task,
        "nomes": nomes_das_pessoas(conn),
        "etapas": etapas,
        "resumo_etapas": etapas_service.resumo_das_etapas(etapas),
        "blocos": linha_do_tempo(eventos, abertas),
        "abertas": len(abertas),
        "participantes": list(participantes.values()),
        "diffs": [e for e in eventos if e["kind"] == EKindEvent.diff_published],
        "ultimo_corpo": corpos[-1] if corpos else None,
        "membros": projects_repositorio.membros_do_projeto(conn, projeto["id"]),
        "features": features_repositorio.find_all(conn, projeto["id"]),
        "statuses": [s.value for s in EStatusTask],
        "tipos_mensagem": [t.value for t in ETypeMessage],
    }


def ctx_corpo_diff(
    conn: sqlite3.Connection, projeto: sqlite3.Row, code: str, versao: int
) -> dict[str, Any]:
    task = tasks_repositorio.find_by_code(conn, projeto["id"], code)
    return {"diff": tasks_service.task_diff(conn, task["id"], code, versao - 1, versao)}
