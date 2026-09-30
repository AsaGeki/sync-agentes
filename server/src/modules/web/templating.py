import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

from src.modules.events.relatorio import ROTULO_STATUS
from src.shared import codes

PASTA_WEB = Path(__file__).parent

templates = Jinja2Templates(directory=PASTA_WEB / "templates")

# `html: False` escapa HTML cru do texto: corpo e mensagem vêm de qualquer membro.
_MD = MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])

ROTULO_AGENT = {"human": "humano", "claude": "claude", "codex": "codex", "outro": "outro"}

ROTULO_MENSAGEM = {
    "mudanca": "mudança",
    "pergunta": "pergunta",
    "resposta": "resposta",
    "decisao": "decisão",
    "bloqueio": "bloqueio",
}


def quando(iso: str | None) -> str:
    if not iso:
        return "-"
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MESES_LONGOS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]


def relativo(iso: str | None) -> str:
    """"agora", "há 12 min", "hoje 14:03", "ontem 09:10", "24 set 14:03"."""
    if not iso:
        return "-"
    momento = datetime.fromisoformat(iso)
    agora = datetime.now(momento.tzinfo)
    segundos = (agora - momento).total_seconds()
    if segundos < 60:
        return "agora"
    if segundos < 3600:
        return f"há {int(segundos // 60)} min"
    if momento.date() == agora.date():
        return f"hoje {momento:%H:%M}"
    if momento.date() == agora.date() - timedelta(days=1):
        return f"ontem {momento:%H:%M}"
    if momento.year == agora.year:
        return f"{momento.day} {MESES[momento.month - 1]} {momento:%H:%M}"
    return f"{momento.day} {MESES[momento.month - 1]} {momento.year}"


def duracao(segundos: float | None) -> str:
    """"2d 4h", "3h 12min", "45min": só as duas maiores unidades."""
    if segundos is None:
        return "-"
    total = int(segundos)
    if total < 60:
        return "< 1 min"
    dias, resto = divmod(total, 86400)
    horas, resto = divmod(resto, 3600)
    minutos = resto // 60
    if dias:
        return f"{dias}d {horas}h" if horas else f"{dias}d"
    if horas:
        return f"{horas}h {minutos}min" if minutos else f"{horas}h"
    return f"{minutos}min"


LIMITE_PARADA = timedelta(hours=4)


def parada(iso: str | None) -> bool:
    """Task em andamento sem nenhum evento há mais que `LIMITE_PARADA`."""
    if not iso:
        return False
    momento = datetime.fromisoformat(iso)
    return datetime.now(momento.tzinfo) - momento > LIMITE_PARADA


def rotulo_dia(dia: str) -> str:
    """Separador de dia da conversa: "Hoje", "Ontem", "24 de setembro"."""
    data = datetime.fromisoformat(dia).date()
    hoje = datetime.now().date()
    if data == hoje:
        return "Hoje"
    if data == hoje - timedelta(days=1):
        return "Ontem"
    sufixo = "" if data.year == hoje.year else f" de {data.year}"
    return f"{data.day} de {MESES_LONGOS[data.month - 1]}{sufixo}"


def code_curto(code: str) -> str:
    """`T-023-janela-de-horario` vira `T-023`; o título já diz o resto."""
    return codes.numero_do_code(code, code[0]) or code


def iniciais(nome: str | None) -> str:
    partes = (nome or "?").replace(".", " ").split()
    return "".join(p[0] for p in partes[:2]).upper()


def cor_avatar(chave: str | None) -> str:
    """Classe de cor estável por pessoa, das 8 da paleta."""
    return f"av{int(hashlib.md5((chave or '').encode()).hexdigest(), 16) % 8 + 1}"


def json_lista(valor: str | None) -> str:
    """Lista gravada como JSON (tags) em texto corrido."""
    return ", ".join(json.loads(valor)) if valor else ""


def link_remote(remote: str | None) -> str | None:
    """URL navegável do remote git (`https://...` ou `git@host:org/repo.git`)."""
    if not remote:
        return None
    if remote.startswith("git@") and ":" in remote:
        host, caminho = remote[4:].split(":", 1)
        remote = f"https://{host}/{caminho}"
    if not remote.startswith(("http://", "https://")):
        return None
    return remote.removesuffix(".git")


def linhas_diff(texto: str | None) -> list[tuple[str, str]]:
    """Cada linha de um diff unificado com a classe CSS que a colore."""
    linhas = []
    for linha in (texto or "").splitlines():
        if linha.startswith(("+++", "---", "diff ", "index ")):
            classe = "meta"
        elif linha.startswith("@@"):
            classe = "hunk"
        elif linha.startswith("+"):
            classe = "add"
        elif linha.startswith("-"):
            classe = "del"
        else:
            classe = ""
        linhas.append((classe, linha))
    return linhas


def markdown(texto: str | None) -> Markup:
    return Markup(_MD.render(texto or ""))


def markdown_linha(texto: str | None) -> Markup:
    """Markdown só de trecho em linha (negrito, código), pra prévia de uma linha."""
    return Markup(_MD.renderInline(texto or ""))


templates.env.filters["quando"] = quando
templates.env.filters["relativo"] = relativo
templates.env.filters["parada"] = parada
templates.env.filters["duracao"] = duracao
templates.env.filters["json_lista"] = json_lista
templates.env.filters["link_remote"] = link_remote
templates.env.filters["rotulo_dia"] = rotulo_dia
templates.env.filters["code_curto"] = code_curto
templates.env.filters["iniciais"] = iniciais
templates.env.filters["cor_avatar"] = cor_avatar
templates.env.filters["markdown"] = markdown
templates.env.filters["markdown_linha"] = markdown_linha
templates.env.filters["linhas_diff"] = linhas_diff
templates.env.globals["ROTULO_STATUS"] = ROTULO_STATUS
templates.env.globals["ROTULO_AGENT"] = ROTULO_AGENT
templates.env.globals["ROTULO_MENSAGEM"] = ROTULO_MENSAGEM
