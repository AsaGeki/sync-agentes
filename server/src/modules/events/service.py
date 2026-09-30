"""Trilha de eventos: gravação, leitura e resumo de uma linha.

`envelope()` é o formato público de um evento, igual em `/mudancas`, no
SSE, no relatório e na leitura de task.
"""

import json
import sqlite3
from typing import Any

from src.modules.events import repositorio
from src.shared.auth import ContextoGit
from src.shared.db import now
from src.shared.enums import EKindEvent


def registrar(conn: sqlite3.Connection, ctx: ContextoGit, **campos: Any) -> int:
    """Grava um evento carimbando qual ferramenta escreveu (`agent`) e em que
    ponto do git (`branch`/`commit_sha`)."""
    campos.setdefault("created_at", now())
    campos.setdefault("agent", ctx.agent.value)
    campos.setdefault("branch", ctx.branch)
    campos.setdefault("commit_sha", ctx.commit_sha)
    return repositorio.insert(conn, **campos)


def hidratar(conn: sqlite3.Connection, seq: int) -> dict[str, Any]:
    """Linha crua do evento mais quem assinou, task e projeto. Uso interno."""
    linha = repositorio.buscar_por_seq(conn, seq)
    return {k: linha[k] for k in linha.keys() if linha[k] is not None}


def _payload(evento: dict[str, Any], com_texto: bool) -> dict[str, Any]:
    """Os campos que só fazem sentido pra aquele `kind`."""
    kind = evento["kind"]
    if kind == EKindEvent.task_created:
        return {"title": evento.get("texto")}
    if kind in (EKindEvent.task_field_changed, EKindEvent.feature_field_changed):
        return {
            "campo": evento.get("campo"),
            "valor_de": evento.get("valor_de"),
            "valor_para": evento.get("valor_para"),
        }
    if kind == EKindEvent.feature_created:
        return {"title": evento.get("texto")}
    if kind == EKindEvent.feature_deleted:
        return {"code": evento.get("valor_de")}
    if kind == EKindEvent.body_updated:
        dados: dict[str, Any] = {"versao": evento.get("version")}
        if com_texto:
            dados["texto"] = evento.get("texto")
        return dados
    if kind == EKindEvent.message_created:
        return {"type": evento.get("type"), "texto": evento.get("texto")}
    if kind == EKindEvent.diff_published:
        dados = {
            "base_sha": evento.get("base_sha"),
            "head_sha": evento.get("commit_sha"),
            "arquivos": json.loads(evento["arquivos"]) if evento.get("arquivos") else [],
        }
        if com_texto:
            dados["patch"] = evento.get("texto")
        return dados
    return {}


def _code_da_feature(evento: dict[str, Any]) -> str | None:
    """Feature apagada perde o vínculo (`feature_id` vira NULL); aí vale o code
    gravado no próprio evento: `valor_para` no created, `texto` no
    field_changed, `valor_de` no deleted."""
    if evento.get("feature_code"):
        return evento["feature_code"]
    return {
        EKindEvent.feature_created: evento.get("valor_para"),
        EKindEvent.feature_field_changed: evento.get("texto"),
        EKindEvent.feature_deleted: evento.get("valor_de"),
    }.get(evento["kind"])


def linha_curta(valor: str | None, limite: int = 80) -> str | None:
    """Primeira linha do valor, cortada em `limite` - campo como `description`
    pode ter texto longo, e resumo é uma linha só."""
    if valor is None:
        return None
    primeira = valor.split("\n", 1)[0]
    if primeira == valor and len(valor) <= limite:
        return valor
    return primeira[:limite] + "…"


def envelope(evento: dict[str, Any], com_texto: bool = False) -> dict[str, Any]:
    """Formato público de um evento. `com_texto=False` omite o que é volumoso
    (corpo inteiro, patch)."""
    return {
        "seq": evento["seq"],
        "kind": evento["kind"],
        "created_at": evento["created_at"],
        "project": evento["project_slug"],
        "task": evento.get("task_code"),
        "feature": _code_da_feature(evento),
        "actor": {
            "person": evento["author_alias"],
            "name": evento["author_name"],
            "agent": evento.get("agent", "outro"),
        },
        "git": {"branch": evento.get("branch"), "commit": evento.get("commit_sha")},
        "payload": _payload(evento, com_texto),
        "resumo": resumir(evento),
    }


def eventos_da_task(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    return [
        envelope(hidratar(conn, seq), com_texto=True)
        for seq in repositorio.seqs_da_task(conn, task_id)
    ]


def mudancas_do_projeto(
    conn: sqlite3.Connection,
    projeto_id: int,
    desde: int,
    limite: int,
    exceto_autor: int | None = None,
) -> dict[str, Any]:
    """`exceto_autor` corta o próprio eco de quem está perguntando."""
    seqs = repositorio.seqs_do_projeto(conn, projeto_id, desde, limite, exceto_autor)
    eventos = [envelope(hidratar(conn, seq)) for seq in seqs]
    return {
        "desde": desde,
        "cursor": eventos[-1]["seq"] if eventos else desde,
        "total": len(eventos),
        "eventos": eventos,
    }


def feed_do_projeto(
    conn: sqlite3.Connection, projeto_id: int, limite: int, **filtros: Any
) -> dict[str, Any]:
    """Uma página do feed. `proximo` é o seq a passar em `antes` pra página
    seguinte, ou None quando não há mais."""
    seqs = repositorio.seqs_do_feed(conn, projeto_id, limite + 1, **filtros)
    return {
        "eventos": [envelope(hidratar(conn, seq)) for seq in seqs[:limite]],
        "proximo": seqs[limite - 1] if len(seqs) > limite else None,
    }


def assinatura(evento: dict[str, Any]) -> str:
    """Quem escreveu e por qual ferramenta."""
    agent = evento.get("agent", "outro")
    if agent == "human":
        return evento["author_alias"]
    return f"{evento['author_alias']} · {agent}"


def resumir(evento: dict[str, Any]) -> str:
    """Linha curta do evento, pronta pra mostrar como notificação."""
    kind = evento["kind"]
    alvo = evento.get("task_code") or _code_da_feature(evento) or "-"
    prefixo = f"[{evento['project_slug']}] {alvo} · {assinatura(evento)}"
    if evento.get("branch"):
        prefixo += f" ({evento['branch']})"
    if kind == EKindEvent.message_created:
        return f"{prefixo} · {evento['type']}: {evento['texto'].splitlines()[0]}"
    if kind in (EKindEvent.task_field_changed, EKindEvent.feature_field_changed):
        de = linha_curta(evento.get("valor_de")) or "vazio"
        para = linha_curta(evento.get("valor_para")) or "vazio"
        return f"{prefixo} · {evento['campo']}: {de} -> {para}"
    if kind == EKindEvent.body_updated:
        return f"{prefixo} · corpo v{evento['version']}"
    if kind == EKindEvent.diff_published:
        arquivos = json.loads(evento["arquivos"]) if evento.get("arquivos") else []
        base = (evento.get("base_sha") or "")[:7]
        head = (evento.get("commit_sha") or "")[:7]
        return f"{prefixo} · diff {base}..{head}: {len(arquivos)} arquivo(s)"
    if kind == EKindEvent.feature_created:
        return f"{prefixo} · feature criada: {evento.get('texto', '')}"
    if kind == EKindEvent.feature_deleted:
        return f"{prefixo} · feature apagada"
    return f"{prefixo} · task criada: {evento.get('texto', '')}"
