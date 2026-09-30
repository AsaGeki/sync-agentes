import sqlite3
from collections import Counter
from typing import Any

from src.modules.events import service as eventos_service
from src.modules.events.bus import publish
from src.modules.features import repositorio
from src.modules.features.models import FeatureIn, FeaturePatch
from src.modules.projects.service import exigir_acesso
from src.modules.tasks import repositorio as tasks_repositorio
from src.shared import codes
from src.shared.auth import ContextoGit
from src.shared.enums import EKindEvent, EStatusTask
from src.shared.erros import AlreadyExists, Invalid

TENTATIVAS_DE_CODIGO = 5


def status_derivado(statuses: list[str]) -> str:
    """Status da feature a partir das tasks dela. Avaliado nesta ordem: sem task
    ou todas em ideia, todas feito, alguma bloqueada, resto é parcial."""
    if all(s == EStatusTask.ideia.value for s in statuses):
        return EStatusTask.ideia.value
    if all(s == EStatusTask.feito.value for s in statuses):
        return EStatusTask.feito.value
    if any(s == EStatusTask.bloqueado.value for s in statuses):
        return EStatusTask.bloqueado.value
    return EStatusTask.parcial.value


def serializar(conn: sqlite3.Connection, feature: sqlite3.Row) -> dict[str, Any]:
    statuses = [t["status"] for t in repositorio.tasks_da_feature(conn, feature["id"])]
    contagem = Counter(statuses)
    return {
        "code": feature["code"],
        "title": feature["title"],
        "description": feature["description"],
        "status": status_derivado(statuses),
        "progresso": {"feito": contagem[EStatusTask.feito.value], "total": len(statuses)},
        "contagem_status": dict(contagem),
        "created_at": feature["created_at"],
        "updated_at": feature["updated_at"],
    }


async def create_feature(
    conn: sqlite3.Connection, slug: str, author_id: int, ctx: ContextoGit, dados: FeatureIn
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    # Dois lados criando ao mesmo tempo chegam no mesmo número: tenta o seguinte.
    for tentativa in range(TENTATIVAS_DE_CODIGO):
        code = codes.montar_code(repositorio.proximo_numero(conn, projeto["id"]), dados.title)
        try:
            with conn:
                feature_id = repositorio.insert(conn, projeto["id"], code, dados, author_id)
                seq = eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto["id"],
                    feature_id=feature_id,
                    author_id=author_id,
                    kind=EKindEvent.feature_created.value,
                    texto=dados.title,
                    valor_para=code,
                )
            break
        except sqlite3.IntegrityError:
            if tentativa == TENTATIVAS_DE_CODIGO - 1:
                raise AlreadyExists(f"Feature '{code}' já existe neste projeto") from None
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, **serializar(conn, repositorio.find_by_id(conn, feature_id))}


def list_features(conn: sqlite3.Connection, slug: str, person_id: int) -> list[dict[str, Any]]:
    projeto = exigir_acesso(conn, slug, person_id)
    return [serializar(conn, f) for f in repositorio.find_all(conn, projeto["id"])]


def read_feature(
    conn: sqlite3.Connection, slug: str, person_id: int, code: str
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, person_id)
    feature = repositorio.find_by_code(conn, projeto["id"], code)
    dados = serializar(conn, feature)
    dados["tasks"] = [
        {
            "code": t["code"],
            "title": t["title"],
            "status": t["status"],
            "owner": tasks_repositorio.owner_name(conn, t["owner_id"]),
        }
        for t in repositorio.tasks_da_feature(conn, feature["id"])
    ]
    return dados


async def update_feature(
    conn: sqlite3.Connection,
    slug: str,
    code: str,
    author_id: int,
    ctx: ContextoGit,
    dados: FeaturePatch,
) -> dict[str, Any]:
    projeto = exigir_acesso(conn, slug, author_id)
    feature = repositorio.find_by_code(conn, projeto["id"], code)
    mudancas = dados.model_dump(exclude_none=True)
    if not mudancas:
        raise Invalid("Nada pra atualizar")

    sequencias: list[int] = []
    with conn:
        for campo, valor in mudancas.items():
            antes = feature[campo]
            if antes == valor:
                continue
            repositorio.update_campo(conn, feature["id"], campo, valor)
            sequencias.append(
                eventos_service.registrar(
                    conn,
                    ctx,
                    project_id=projeto["id"],
                    feature_id=feature["id"],
                    author_id=author_id,
                    kind=EKindEvent.feature_field_changed.value,
                    texto=feature["code"],
                    campo=campo,
                    valor_de=antes,
                    valor_para=valor,
                )
            )
    for seq in sequencias:
        await publish(slug, eventos_service.hidratar(conn, seq))
    atual = repositorio.find_by_id(conn, feature["id"])
    return {"cursor": sequencias[-1] if sequencias else None, **serializar(conn, atual)}


async def delete_feature(
    conn: sqlite3.Connection, slug: str, code: str, author_id: int, ctx: ContextoGit
) -> dict[str, Any]:
    """Tasks da feature ficam avulsas (`ON DELETE SET NULL`)."""
    projeto = exigir_acesso(conn, slug, author_id)
    feature = repositorio.find_by_code(conn, projeto["id"], code)
    soltas = [t["code"] for t in repositorio.tasks_da_feature(conn, feature["id"])]
    with conn:
        seq = eventos_service.registrar(
            conn,
            ctx,
            project_id=projeto["id"],
            feature_id=feature["id"],
            author_id=author_id,
            kind=EKindEvent.feature_deleted.value,
            valor_de=feature["code"],
        )
        repositorio.delete(conn, feature["id"])
    await publish(slug, eventos_service.hidratar(conn, seq))
    return {"cursor": seq, "code": feature["code"], "tasks_soltas": soltas}
