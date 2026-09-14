"""Cliente HTTP do servidor sync-agents.

Usa `urllib` da stdlib de propósito: o bridge roda na máquina de quem conecta e
não deve exigir instalação de nada além do próprio pacote.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from src.bridge.git_context import ContextoRepo

METODOS_MUTADORES = {"POST", "PUT", "PATCH"}
TENTATIVAS_DE_REDE = 3


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

    def _headers(self, operation_id: str | None) -> dict[str, str]:
        cabecalhos = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Agent": self.agent,
        }
        if self.repo.branch:
            cabecalhos["X-Git-Branch"] = self.repo.branch
        if self.repo.commit_sha:
            cabecalhos["X-Git-Commit"] = self.repo.commit_sha
        if operation_id:
            cabecalhos["X-Operation-Id"] = operation_id
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
        # Mesmo operation_id em toda tentativa: se a 1ª chegou no servidor mas a
        # resposta se perdeu, a repetição devolve o resultado gravado em vez de
        # aplicar a escrita de novo.
        operation_id = str(uuid.uuid4()) if metodo in METODOS_MUTADORES else None
        req = urllib.request.Request(
            url, data=dados, headers=self._headers(operation_id), method=metodo
        )
        for tentativa in range(1, TENTATIVAS_DE_REDE + 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resposta:
                    texto = resposta.read().decode("utf-8")
                    tipo = resposta.headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as erro:
                bruto = erro.read().decode("utf-8", errors="replace")
                try:
                    detalhe = json.loads(bruto).get("detail", bruto)
                except json.JSONDecodeError:
                    detalhe = bruto
                raise ErroApi(erro.code, detalhe) from None
            except urllib.error.URLError as erro:
                if operation_id is None or tentativa == TENTATIVAS_DE_REDE:
                    raise ErroApi(
                        0, f"Servidor inacessível em {self.base_url}: {erro.reason}"
                    ) from None
                time.sleep(0.5 * tentativa)
        if "application/json" not in tipo:
            return texto
        return json.loads(texto) if texto else None
