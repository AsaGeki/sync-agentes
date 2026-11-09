"""Cliente HTTP do servidor sync-agents.

Usa `urllib` da stdlib de propósito: o bridge roda na máquina de quem conecta e
não deve exigir instalação de nada além do próprio pacote.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any

from sync_agents_mcp.git_context import ContextoRepo, ponto_atual

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
            except (OSError, http.client.HTTPException) as erro:
                # Inclui conexão derrubada e timeout depois do envio: a resposta
                # perdida é o caso que o `X-Operation-Id` existe pra cobrir.
                repetivel = metodo == "GET" or operation_id is not None
                if not repetivel or tentativa == TENTATIVAS_DE_REDE:
                    motivo = erro.reason if isinstance(erro, urllib.error.URLError) else erro
                    raise ErroApi(
                        0, f"Servidor inacessível em {self.base_url}: {motivo}"
                    ) from None
                time.sleep(0.5 * tentativa)
        if "application/json" not in tipo:
            return texto
        return json.loads(texto) if texto else None
