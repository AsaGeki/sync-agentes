"""Trilha de eventos: gravação, envelope de leitura e resumo de uma linha.

O **envelope** (`envelope()`) é o formato público de um evento - o mesmo em
`/mudancas`, no WebSocket, no relatório e na leitura de task. Quem consome não
precisa conhecer as colunas do banco: lê `kind`, `actor`, `git` e `payload`.
"""

import json
import sqlite3
from typing import Any

from src.modules.events import repositorio
from src.shared.auth import ContextoGit
from src.shared.db import now
from src.shared.enums import EKindEvent


def registrar(conn: sqlite3.Connection, ctx: ContextoGit, **campos: Any) -> int:
    """Grava um evento carimbando de onde ele saiu: qual ferramenta escreveu
    (`agent`) e em que ponto do git (`branch`/`commit_sha`). É esse carimbo que
    faz o relatório amarrar conversa a código."""
    campos.setdefault("created_at", now())
    campos.setdefault("agent", ctx.agent.value)
    campos.setdefault("branch", ctx.branch)
    campos.setdefault("commit_sha", ctx.commit_sha)
    return repositorio.insert(conn, **campos)


def hidratar(conn: sqlite3.Connection, seq: int) -> dict[str, Any]:
    """Linha crua do evento mais quem assinou, task e projeto. Uso interno - o
    que sai pra fora é `envelope()`."""
    linha = repositorio.buscar_por_seq(conn, seq)
    return {k: linha[k] for k in linha.keys() if linha[k] is not None}


def _payload(evento: dict[str, Any], com_texto: bool) -> dict[str, Any]:
    """Os campos que só fazem sentido pra aquele `kind`."""
    kind = evento["kind"]
    if kind == EKindEvent.task_created:
        return {"title": evento.get("texto")}
    if kind == EKindEvent.task_field_changed:
        return {
            "campo": evento.get("campo"),
            "valor_de": evento.get("valor_de"),
            "valor_para": evento.get("valor_para"),
        }
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


def envelope(evento: dict[str, Any], com_texto: bool = False) -> dict[str, Any]:
    """Formato público de um evento. `com_texto=False` deixa de fora o que é
    volumoso (corpo inteiro, patch) - listagem não precisa carregar isso."""
    return {
        "seq": evento["seq"],
        "kind": evento["kind"],
        "created_at": evento["created_at"],
        "project": evento["project_slug"],
        "task": evento.get("task_code"),
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
    """`exceto_autor` corta o próprio eco: quem pergunta o que mudou quer saber
    do outro lado, não do que acabou de escrever."""
    seqs = repositorio.seqs_do_projeto(conn, projeto_id, desde, limite, exceto_autor)
    eventos = [envelope(hidratar(conn, seq)) for seq in seqs]
    return {
        "desde": desde,
        "cursor": eventos[-1]["seq"] if eventos else desde,
        "total": len(eventos),
        "eventos": eventos,
    }


def assinatura(evento: dict[str, Any]) -> str:
    """Quem escreveu e por qual ferramenta. Autor é sempre uma pessoa - a IA é o
    `agent`, não um autor separado."""
    agent = evento.get("agent", "outro")
    if agent == "human":
        return evento["author_alias"]
    return f"{evento['author_alias']} · {agent}"


def resumir(evento: dict[str, Any]) -> str:
    """Linha curta: é isso que o Monitor mostra como notificação no chat do agente."""
    alvo = evento.get("task_code", "-")
    prefixo = f"[{evento['project_slug']}] {alvo} · {assinatura(evento)}"
    if evento.get("branch"):
        prefixo += f" ({evento['branch']})"
    kind = evento["kind"]
    if kind == EKindEvent.message_created:
        return f"{prefixo} · {evento['type']}: {evento['texto'].splitlines()[0]}"
    if kind == EKindEvent.task_field_changed:
        de = evento.get("valor_de", "vazio")
        para = evento.get("valor_para", "vazio")
        return f"{prefixo} · {evento['campo']}: {de} -> {para}"
    if kind == EKindEvent.body_updated:
        return f"{prefixo} · corpo v{evento['version']}"
    if kind == EKindEvent.diff_published:
        arquivos = json.loads(evento["arquivos"]) if evento.get("arquivos") else []
        base = (evento.get("base_sha") or "")[:7]
        head = (evento.get("commit_sha") or "")[:7]
        return f"{prefixo} · diff {base}..{head}: {len(arquivos)} arquivo(s)"
    return f"{prefixo} · task criada: {evento.get('texto', '')}"
