"""Cliente HTTP do servidor sync-agents (httpx, que já vem com o SDK do MCP)."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from sync_agents_mcp.git_context import ContextoRepo, ponto_atual

# O httpx loga cada requisição em INFO no stderr, que o cliente MCP mostra como ruído.
logging.getLogger("httpx").setLevel(logging.WARNING)

METODOS_MUTADORES = {"POST", "PUT", "PATCH", "DELETE"}
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
        self.http = httpx.Client(base_url=self.base_url, timeout=30)

    def _headers(self, operation_id: str | None) -> dict[str, str]:
        cabecalhos = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "X-Agent": self.agent,
        }
        # Escrita carimba o ponto do git de agora, não o do início da sessão.
        branch, commit = (
            ponto_atual(self.repo.raiz)
            if operation_id
            else (self.repo.branch, self.repo.commit_sha)
        )
        if branch:
            cabecalhos["X-Git-Branch"] = branch
        if commit:
            cabecalhos["X-Git-Commit"] = commit
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
        params = {k: v for k, v in (query or {}).items() if v is not None}
        # Mesmo operation_id em toda tentativa: se a 1ª chegou no servidor mas a
        # resposta se perdeu, a repetição devolve o resultado gravado em vez de
        # aplicar a escrita de novo.
        operation_id = str(uuid.uuid4()) if metodo in METODOS_MUTADORES else None
        cabecalhos = self._headers(operation_id)
        for tentativa in range(1, TENTATIVAS_DE_REDE + 1):
            try:
                resposta = self.http.request(metodo, caminho, json=corpo, params=params, headers=cabecalhos)
                break
            except httpx.TransportError as erro:
                # Inclui conexão derrubada e timeout depois do envio: a resposta
                # perdida é o caso que o `X-Operation-Id` existe pra cobrir.
                repetivel = metodo == "GET" or operation_id is not None
                if not repetivel or tentativa == TENTATIVAS_DE_REDE:
                    raise ErroApi(0, f"Servidor inacessível em {self.base_url}: {erro}") from None
                time.sleep(0.5 * tentativa)
        if resposta.is_error:
            try:
                detalhe = resposta.json().get("detail", resposta.text)
            except ValueError:
                detalhe = resposta.text
            raise ErroApi(resposta.status_code, detalhe)
        if "application/json" not in resposta.headers.get("Content-Type", ""):
            return resposta.text
        return resposta.json() if resposta.content else None
