"""Infra dos testes: cada teste roda contra um SQLite descartável e fala com a
API por HTTP, como o bridge e a web fazem.

`SYNC_AGENTS_DB` e `ADMIN_TOKEN` são fixados antes de importar `src`: o `.env` do
projeto nunca é usado aqui e o `sync.db` real nunca é aberto.
"""

import itertools
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

ADMIN = "admin-de-teste"
_IMPORTACAO = Path(tempfile.mkdtemp(prefix="sync-agents-import-")) / "import.db"
os.environ["SYNC_AGENTS_DB"] = str(_IMPORTACAO)
os.environ["ADMIN_TOKEN"] = ADMIN

from fastapi.testclient import TestClient  # noqa: E402

from src.shared import db  # noqa: E402

assert db.DB_PATH == _IMPORTACAO and db.DB_PATH != SERVER / "sync.db"

from src.main import app  # noqa: E402

PASSADO = "2000-01-01T00:00:00+00:00"

_contador = itertools.count(1)


class Pessoa:
    def __init__(self, mundo: "Mundo", id_: int, email: str, token: str) -> None:
        self.mundo = mundo
        self.id = id_
        self.email = email
        self.token = token
        self.h = {"Authorization": f"Bearer {token}", "X-Agent": "claude-code"}

    def _h(self, kw: dict[str, Any]) -> dict[str, str]:
        return {**self.h, **kw.pop("headers", {})}

    def get(self, caminho: str, **kw: Any):
        return self.mundo.cliente.get(caminho, headers=self._h(kw), **kw)

    def post(self, caminho: str, json: Any = None, **kw: Any):
        return self.mundo.cliente.post(caminho, headers=self._h(kw), json=json, **kw)

    def patch(self, caminho: str, json: Any = None, **kw: Any):
        return self.mundo.cliente.patch(caminho, headers=self._h(kw), json=json, **kw)

    def put(self, caminho: str, json: Any = None, **kw: Any):
        return self.mundo.cliente.put(caminho, headers=self._h(kw), json=json, **kw)

    def delete(self, caminho: str, **kw: Any):
        return self.mundo.cliente.delete(caminho, headers=self._h(kw), **kw)


class Mundo:
    """Atalhos de cenário. Tudo passa pela API; só o relógio é mexido por SQL."""

    def __init__(self, cliente: TestClient) -> None:
        self.cliente = cliente
        self.admin = {"Authorization": f"Bearer {ADMIN}", "X-Agent": "claude-code"}

    def pessoa(self, nome: str = "Pessoa") -> Pessoa:
        n = next(_contador)
        email = f"{nome.lower()}{n}@exemplo.com"
        criada = self.cliente.post("/people", headers=self.admin, json={"email": email, "name": nome})
        assert criada.status_code == 201, criada.text
        emitido = self.cliente.post(f"/people/{criada.json()['id']}/token", headers=self.admin)
        assert emitido.status_code == 200, emitido.text
        return Pessoa(self, criada.json()["id"], email, emitido.json()["token"])

    def projeto(self, dono: Pessoa, nome: str = "Projeto", visibility: str = "team") -> str:
        sha = f"{next(_contador):040x}"
        resp = dono.post(
            "/projetos",
            {"name": f"{nome} {sha[-4:]}", "visibility": visibility, "repo": {"root_sha": sha, "name": "repo"}},
        )
        assert resp.status_code == 201, resp.text
        self.shas = getattr(self, "shas", {})
        self.shas[resp.json()["slug"]] = sha
        return resp.json()["slug"]

    def entrar(self, pessoa: Pessoa, slug: str, dono: Pessoa | None = None, em: str | None = PASSADO) -> None:
        """Põe a pessoa no projeto e, por padrão, recua a entrada pro passado -
        os testes de entrada tardia passam `em` explícito."""
        if dono is None:
            resp = pessoa.post(f"/projetos/{slug}/repos", {"root_sha": self.shas[slug], "name": "repo"})
        else:
            resp = dono.post(f"/projetos/{slug}/membros", {"email": pessoa.email})
        assert resp.status_code == 201, resp.text
        if em is not None:
            self.sql(
                "UPDATE memberships SET created_at = ? WHERE person_id = ?"
                " AND project_id = (SELECT id FROM projects WHERE slug = ?)",
                (em, pessoa.id, slug),
            )

    def task(self, autor: Pessoa, slug: str, titulo: str = "Tarefa", **extra: Any) -> str:
        resp = autor.post(f"/projetos/{slug}/tasks", {"title": titulo, **extra})
        assert resp.status_code == 201, resp.text
        return resp.json()["code"]

    def mensagem(self, autor: Pessoa, slug: str, code: str, tipo: str = "mudanca", texto: str = "texto") -> dict:
        resp = autor.post(f"/projetos/{slug}/tasks/{code}/mensagens", {"type": tipo, "texto": texto})
        assert resp.status_code == 201, resp.text
        return resp.json()

    def nao_lidos(self, pessoa: Pessoa, slug: str) -> dict:
        resp = pessoa.get(f"/projetos/{slug}/nao-lidos")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def sql(self, consulta: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = db.conectar()
        try:
            with conn:
                return conn.execute(consulta, params).fetchall()
        finally:
            conn.close()

    def datar_eventos(self, em: str) -> None:
        """Carimba todos os eventos existentes com `em`."""
        self.sql("UPDATE events SET created_at = ?", (em,))


@pytest.fixture
def mundo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Mundo]:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "teste.db")
    db.iniciar_banco()
    with TestClient(app) as cliente:
        yield Mundo(cliente)
