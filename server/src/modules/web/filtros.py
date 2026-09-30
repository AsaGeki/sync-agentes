"""Filtros lidos da query string: lista de tasks e feed de atividade. Dependências
compartilhadas pela área da pessoa e pela do admin."""

from typing import Any

from fastapi import Query

from src.modules.events.repositorio import CONDICAO_TIPO
from src.shared.enums import EAgent, EStatusTask

PADRAO_PERIODO = "^(|24h|7d|30d)$"


def filtros_tasks(
    status: list[EStatusTask] = Query([]),
    feature: str = "",
    tag: str = "",
    q: str = "",
    dono: str = Query("", pattern=r"^\d*$"),
    sem_dono: bool = False,
    fazendo: bool = False,
    atencao: bool = False,
    paradas: bool = False,
    nao_lidas: bool = False,
    periodo: str = Query("", pattern=PADRAO_PERIODO),
    ordem: str = Query("code", pattern="^(code|recentes|status)$"),
    visao: str = Query("lista", pattern="^(lista|quadro)$"),
    agrupar: str = Query("", pattern="^(|feature)$"),
) -> dict[str, Any]:
    return {
        "status": [s.value for s in status],
        "feature": feature,
        "tag": tag,
        "q": q,
        "dono": dono,
        "sem_dono": sem_dono,
        "fazendo": fazendo,
        "atencao": atencao,
        "paradas": paradas,
        "nao_lidas": nao_lidas,
        "periodo": periodo,
        "ordem": ordem,
        "visao": visao,
        "agrupar": agrupar,
    }


def filtros_atividade(
    pessoa: str = "",
    agent: str = Query("", pattern="^(|" + "|".join(a.value for a in EAgent) + ")$"),
    tipo: str = Query("", pattern="^(|" + "|".join(CONDICAO_TIPO) + ")$"),
    task: str = "",
    feature: str = "",
    periodo: str = Query("", pattern=PADRAO_PERIODO),
    antes: int = Query(0, ge=0),
) -> dict[str, Any]:
    return {
        "pessoa": pessoa,
        "agent": agent,
        "tipo": tipo,
        "task": task,
        "feature": feature,
        "periodo": periodo,
        "antes": antes,
    }
