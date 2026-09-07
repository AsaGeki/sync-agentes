import sqlite3
from typing import Any

from src.modules.events import repositorio
from src.shared.db import now


def registrar(conn: sqlite3.Connection, **campos: Any) -> int:
    campos.setdefault("created_at", now())
    return repositorio.insert(conn, **campos)


def hidratar(conn: sqlite3.Connection, seq: int) -> dict[str, Any]:
    linha = repositorio.buscar_por_seq(conn, seq)
    return {k: linha[k] for k in linha.keys() if linha[k] is not None}


def eventos_da_task(conn: sqlite3.Connection, task_id: int) -> list[dict[str, Any]]:
    return [hidratar(conn, seq) for seq in repositorio.seqs_da_task(conn, task_id)]


def mudancas_do_projeto(
    conn: sqlite3.Connection, projeto_id: int, desde: int, limite: int
) -> dict[str, Any]:
    seqs = repositorio.seqs_do_projeto(conn, projeto_id, desde, limite)
    eventos = [hidratar(conn, seq) for seq in seqs]
    return {
        "desde": desde,
        "cursor": eventos[-1]["seq"] if eventos else desde,
        "total": len(eventos),
        "eventos": eventos,
    }


def assinatura(evento: dict[str, Any]) -> str:
    """Quem escreveu: nome + tipo, e o responsavel dev quando o autor e IA."""
    if evento.get("author_type") == "ia" and evento.get("author_responsible"):
        return f"{evento['author_name']} (IA · {evento['author_responsible']})"
    tipo = "IA" if evento.get("author_type") == "ia" else "dev"
    return f"{evento['author_name']} ({tipo})"


def resumir(evento: dict[str, Any]) -> str:
    """Linha curta: e isso que o Monitor mostra como notificacao no chat do agente."""
    alvo = evento.get("task_code", "-")
    quem = assinatura(evento)
    prefixo = f"[{evento['project_slug']}] {alvo} · {quem}"
    if evento["kind"] == "mensagem":
        return f"{prefixo} · {evento['type']}: {evento['texto'].splitlines()[0]}"
    if evento["kind"] == "campo":
        de = evento.get("valor_de", "vazio")
        para = evento.get("valor_para", "vazio")
        return f"{prefixo} · {evento['campo']}: {de} -> {para}"
    if evento["kind"] == "corpo":
        return f"{prefixo} · corpo v{evento['version']}"
    return f"{prefixo} · task criada: {evento.get('texto', '')}"
