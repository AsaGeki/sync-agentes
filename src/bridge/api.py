"""Cliente HTTP do servidor sync-agents.

Usa `urllib` da stdlib de propósito: o bridge roda na máquina de quem conecta e
não deve exigir instalação de nada além do próprio pacote.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from src.bridge.git_context import ContextoRepo


class ErroApi(RuntimeError):
    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


class Api:
    def __init__(self, base_url: str, token: str, repo: ContextoRepo, agent: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.repo = repo
        self.agent = agent

    def _headers(self) -> dict[str, str]:
        cabecalhos = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Agent": self.agent,
        }
        if self.repo.branch:
            cabecalhos["X-Git-Branch"] = self.repo.branch
        if self.repo.commit_sha:
            cabecalhos["X-Git-Commit"] = self.repo.commit_sha
        return cabecalhos

    def request(
        self,
        metodo: str,
        caminho: str,
        corpo: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{caminho}"
        if query:
            limpo = {k: v for k, v in query.items() if v is not None}
            if limpo:
                url += "?" + urllib.parse.urlencode(limpo)
        dados = json.dumps(corpo, ensure_ascii=False).encode() if corpo is not None else None
        req = urllib.request.Request(url, data=dados, headers=self._headers(), method=metodo)
        try:
            with urllib.request.urlopen(req, timeout=30) as resposta:
                texto = resposta.read().decode("utf-8")
                tipo = resposta.headers.get("Content-Type", "")
        except urllib.error.HTTPError as erro:
            bruto = erro.read().decode("utf-8", errors="replace")
            try:
                detalhe = json.loads(bruto).get("detail", bruto)
            except json.JSONDecodeError:
                detalhe = bruto
            raise ErroApi(erro.code, detalhe) from None
        except urllib.error.URLError as erro:
            raise ErroApi(0, f"Servidor inacessível em {self.base_url}: {erro.reason}") from None
        if "application/json" not in tipo:
            return texto
        return json.loads(texto) if texto else None
