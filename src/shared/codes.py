"""Code legível de entidade do projeto (`T-007-slug`, `F-003-slug`): o número
endereça, o slug é pra reconhecer sem abrir. `tabela` e `prefixo` vêm sempre
de literal no código, nunca de entrada de usuário."""

import re
import sqlite3
import unicodedata

LIMITE_SLUG_CODE = 40


def slug_do_titulo(title: str) -> str:
    """Título sem acento, minúsculo, hifenizado. Corta na última palavra inteira
    que couber - palavra pela metade atrapalha quem lê."""
    texto = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    if len(texto) <= LIMITE_SLUG_CODE:
        return texto
    cortado = texto[:LIMITE_SLUG_CODE]
    if "-" in cortado:
        cortado = cortado.rsplit("-", 1)[0]
    return cortado.strip("-")


def numero_do_code(code: str, prefixo: str) -> str | None:
    """`T-7`, `T-007` e `T-007-qualquer-coisa` normalizam pra `T-007`."""
    achado = re.match(rf"^\s*[{prefixo}{prefixo.lower()}]-0*(\d+)", code)
    return f"{prefixo}-{int(achado.group(1)):03d}" if achado else None


def montar_code(numero: str, title: str) -> str:
    slug = slug_do_titulo(title)
    return f"{numero}-{slug}" if slug else numero


def proximo_numero(conn: sqlite3.Connection, tabela: str, projeto_id: int, prefixo: str) -> str:
    """Sempre acima do maior número já usado: contar linhas repetiria um número
    caso alguma tenha sido removida. `CAST(SUBSTR(code, 3))` para no primeiro
    hífen, então o slug no fim do code não atrapalha."""
    linha = conn.execute(
        f"SELECT MAX(CAST(SUBSTR(code, 3) AS INTEGER)) AS maior FROM {tabela}"
        f" WHERE project_id = ? AND code GLOB '{prefixo}-[0-9]*'",
        (projeto_id,),
    ).fetchone()
    return f"{prefixo}-{(linha['maior'] or 0) + 1:03d}"


def buscar_por_code(
    conn: sqlite3.Connection, tabela: str, projeto_id: int, code: str, prefixo: str
) -> sqlite3.Row | None:
    """Aceita o code inteiro ou só o número - o número é único no projeto, então
    não fica ambíguo."""
    linha = conn.execute(
        f"SELECT * FROM {tabela} WHERE project_id = ? AND code = ?", (projeto_id, code)
    ).fetchone()
    if linha is not None:
        return linha
    numero = numero_do_code(code, prefixo)
    if numero is None:
        return None
    return conn.execute(
        f"SELECT * FROM {tabela} WHERE project_id = ? AND (code = ? OR code GLOB ?)",
        (projeto_id, numero, f"{numero}-*"),
    ).fetchone()
