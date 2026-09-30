"""Etapas (status) por que uma task passou, reconstruídas dos eventos dela.

A task não guarda o status inicial: ele é o `valor_de` da primeira mudança de
status, ou o status atual se nunca mudou.
"""

from datetime import datetime
from typing import Any

from src.shared.enums import EKindEvent, EStatusTask


def etapas_da_task(
    eventos: list[dict[str, Any]], status_atual: str, agora: datetime
) -> list[dict[str, Any]]:
    """Uma entrada por etapa, da primeira à atual. `eventos` são envelopes da
    task em ordem; a etapa atual conta até `agora`."""
    if not eventos:
        return []
    mudancas = [
        e
        for e in eventos
        if e["kind"] == EKindEvent.task_field_changed and e["payload"]["campo"] == "status"
    ]
    inicial = mudancas[0]["payload"]["valor_de"] if mudancas else status_atual
    marcos = [(inicial, eventos[0])] + [(m["payload"]["valor_para"], m) for m in mudancas]

    etapas = []
    for i, (status, evento) in enumerate(marcos):
        inicio = datetime.fromisoformat(evento["created_at"])
        fim = datetime.fromisoformat(marcos[i + 1][1]["created_at"]) if i + 1 < len(marcos) else agora
        etapas.append(
            {
                "status": status,
                "inicio": evento["created_at"],
                "segundos": max((fim - inicio).total_seconds(), 0),
                "atual": i == len(marcos) - 1,
                "actor": evento["actor"],
            }
        )
    return etapas


def resumo_das_etapas(etapas: list[dict[str, Any]]) -> dict[str, float | None]:
    """`ate_feito`: da criação até a primeira vez em 'feito' (vazio se nasceu
    feita ou nunca fechou). `em_andamento`: soma das etapas em andamento."""
    primeiro_feito = next(
        (i for i, e in enumerate(etapas) if e["status"] == EStatusTask.feito.value), None
    )
    ate_feito = (
        sum(e["segundos"] for e in etapas[:primeiro_feito]) if primeiro_feito else None
    )
    andamento = [e["segundos"] for e in etapas if e["status"] == EStatusTask.em_andamento.value]
    return {"ate_feito": ate_feito, "em_andamento": sum(andamento) if andamento else None}
