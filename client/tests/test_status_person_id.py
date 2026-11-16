"""`status` expõe o `person_id` (o `owner_id` de quem assina) e as descrições das
tools que recebem `owner_id` dizem de onde ele vem."""

from types import SimpleNamespace

from sync_agents_mcp import server
from sync_agents_mcp.api import ErroApi


class ApiFalsa:
    def __init__(self, eu=None, erro=None):
        self.eu = eu
        self.erro = erro

    def request(self, metodo, caminho, corpo=None, **kw):
        assert (metodo, caminho) == ("GET", "/me")
        if self.erro:
            raise self.erro
        return self.eu


class SessaoFalsa:
    def __init__(self, api):
        self.api = api
        self.repo = SimpleNamespace(name="loja-api", raiz="/x")
        self.projetos = [
            {"slug": "loja-api", "name": "Loja", "visibility": "public", "role": "owner"}
        ]

    def erro_de_ambiente(self):
        return None

    def conectar(self, ctx):
        return None


def _status(monkeypatch, api):
    monkeypatch.setattr(server, "SESSAO", SessaoFalsa(api))
    monkeypatch.setattr(server.git_context, "ponto_atual", lambda raiz: ("main", "abc123"))
    return server.status(None)


def test_status_devolve_o_person_id_de_quem_assina(monkeypatch):
    eu = {"id": 6, "email": "arthur@x.com", "alias": "arthur.macedo", "name": "Arthur Gabriel"}
    resp = _status(monkeypatch, ApiFalsa(eu))
    assert resp["person_id"] == 6 and resp["assino_como"] == "arthur.macedo"


def test_status_com_falha_na_api_nao_traz_person_id(monkeypatch):
    resp = _status(monkeypatch, ApiFalsa(erro=ErroApi(401, "token inválido")))
    assert resp == {"erro": "token inválido", "status": 401}


def test_descricoes_de_owner_id_apontam_pro_status_e_list_members():
    for tool in (server.create_task, server.update_task):
        assert "status" in tool.__doc__ and "person_id" in tool.__doc__
        assert "list_members" in tool.__doc__
