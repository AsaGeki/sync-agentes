import sqlite3
from typing import Any

from app.db import agora


def registrar_evento(conn: sqlite3.Connection, **campos: Any) -> int:
    campos.setdefault("criado_em", agora())
    colunas = ", ".join(campos)
    marcadores = ", ".join("?" for _ in campos)
    cursor = conn.execute(
        f"INSERT INTO eventos ({colunas}) VALUES ({marcadores})", tuple(campos.values())
    )
    return int(cursor.lastrowid)


def hidratar_evento(conn: sqlite3.Connection, seq: int) -> dict[str, Any]:
    linha = conn.execute(
        """
        SELECT e.*, a.nome AS autor_nome, a.tipo AS autor_tipo,
               r.nome AS autor_responsavel, t.codigo AS task_codigo,
               t.titulo AS task_titulo, p.slug AS projeto_slug
          FROM eventos e
          JOIN autores  a ON a.id = e.autor_id
          LEFT JOIN autores r ON r.id = a.responsavel_id
          LEFT JOIN tasks   t ON t.id = e.task_id
          JOIN projetos p ON p.id = e.projeto_id
         WHERE e.seq = ?
        """,
        (seq,),
    ).fetchone()
    return {k: linha[k] for k in linha.keys() if linha[k] is not None}


def assinatura(evento: dict[str, Any]) -> str:
    """Quem escreveu: nome + tipo, e o responsavel humano quando o autor e IA."""
    if evento.get("autor_tipo") == "ia" and evento.get("autor_responsavel"):
        return f"{evento['autor_nome']} (IA · {evento['autor_responsavel']})"
    tipo = "IA" if evento.get("autor_tipo") == "ia" else "humano"
    return f"{evento['autor_nome']} ({tipo})"


def resumir_evento(evento: dict[str, Any]) -> str:
    """Linha curta: e isso que o Monitor mostra como notificacao no chat do agente."""
    alvo = evento.get("task_codigo", "-")
    quem = assinatura(evento)
    prefixo = f"[{evento['projeto_slug']}] {alvo} · {quem}"
    if evento["kind"] == "mensagem":
        return f"{prefixo} · {evento['tipo']}: {evento['texto'].splitlines()[0]}"
    if evento["kind"] == "campo":
        de = evento.get("valor_de", "vazio")
        para = evento.get("valor_para", "vazio")
        return f"{prefixo} · {evento['campo']}: {de} -> {para}"
    if evento["kind"] == "corpo":
        return f"{prefixo} · corpo v{evento['versao']}"
    if evento["kind"] == "dependencia":
        return f"{prefixo} · depende de {evento['valor_para']}"
    return f"{prefixo} · task criada: {evento.get('texto', '')}"
