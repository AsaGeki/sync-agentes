"""Envelope que o bridge cola em toda resposta de tool (`nao_lidos`,
`nao_lidos_omitidos`, `nao_lidos_features`, `nao_lidos_indisponivel`) e o corpo
que `update_task` manda."""

from sync_agents_mcp import server
from sync_agents_mcp.api import ErroApi


class ApiFalsa:
    def __init__(self, aviso=None, erro=None):
        self.aviso = aviso
        self.erro = erro
        self.chamadas = []

    def request(self, metodo, caminho, corpo=None, **kw):
        self.chamadas.append((metodo, caminho, corpo))
        if caminho.endswith("/nao-lidos"):
            if self.erro:
                raise self.erro
            return self.aviso
        return {"ok": 1}


class SessaoFalsa:
    def __init__(self, api):
        self.api = api

    def erro_de_ambiente(self):
        return None

    def api_avulsa(self, ctx):
        return self.api


def _chamar(monkeypatch, aviso=None, erro=None):
    api = ApiFalsa(aviso, erro)
    monkeypatch.setattr(server, "SESSAO", SessaoFalsa(api))
    return server._chamar(None, "proj", lambda api_, slug: {"ok": 1})


def _aviso(n, total=None, features=None):
    tasks = [{"code": f"T-{i:03d}", "nao_lidos": 1} for i in range(n)]
    aviso = {"total": n if total is None else total, "tasks": tasks}
    if features:
        aviso["features"] = features
    return aviso


def test_sem_nao_lidos_devolve_so_o_resultado(monkeypatch):
    assert _chamar(monkeypatch, _aviso(0)) == {"ok": 1}


def test_com_nao_lidos_anexa_a_lista(monkeypatch):
    resp = _chamar(monkeypatch, _aviso(2))
    assert resp["ok"] == 1 and [t["code"] for t in resp["nao_lidos"]] == ["T-000", "T-001"]
    assert "nao_lidos_omitidos" not in resp and "nao_lidos_features" not in resp


def test_corte_informa_quantas_ficaram_de_fora(monkeypatch):
    resp = _chamar(monkeypatch, _aviso(20, total=27))
    assert len(resp["nao_lidos"]) == 20 and resp["nao_lidos_omitidos"] == 7


def test_features_nao_lidas_vem_em_campo_proprio(monkeypatch):
    features = {"nao_lidos": 2, "ultimo": "[p] F-001 · bia · feature criada: X"}
    resp = _chamar(monkeypatch, _aviso(1, features=features))
    assert resp["nao_lidos_features"] == features and len(resp["nao_lidos"]) == 1


def test_so_features_nao_lidas_sem_tasks(monkeypatch):
    features = {"nao_lidos": 1, "ultimo": "x"}
    resp = _chamar(monkeypatch, _aviso(0, features=features))
    assert resp == {"ok": 1, "nao_lidos_features": features}


def test_falha_ao_buscar_nao_lidos_nao_derruba_a_escrita(monkeypatch):
    resp = _chamar(monkeypatch, erro=ErroApi(500, "banco fora"))
    assert resp == {"ok": 1, "nao_lidos_indisponivel": "banco fora"}


# ---------- corpo do update_task ---------- #


def _update(monkeypatch, **campos):
    api = ApiFalsa(_aviso(0))
    monkeypatch.setattr(server, "SESSAO", SessaoFalsa(api))
    server.update_task(None, "T-001", project="proj", **campos)
    (patch,) = [c for c in api.chamadas if c[0] == "PATCH"]
    return patch[1], patch[2]


def test_update_manda_so_o_que_foi_informado(monkeypatch):
    caminho, corpo = _update(monkeypatch, title="Novo")
    assert caminho == "/projetos/proj/tasks/T-001" and corpo == {"title": "Novo"}


def test_update_so_com_status_nao_leva_owner_nem_nenhum_outro_campo(monkeypatch):
    _, corpo = _update(monkeypatch, status=server.EStatusTask.cancelada)
    assert corpo == {"status": "cancelada"}


def test_update_owner_zero_vira_null_explicito(monkeypatch):
    _, corpo = _update(monkeypatch, owner_id=0)
    assert corpo == {"owner_id": None} and "owner_id" in corpo


def test_update_owner_real_passa_direto(monkeypatch):
    _, corpo = _update(monkeypatch, owner_id=7, tags=[])
    assert corpo == {"owner_id": 7, "tags": []}


def test_update_feature_vazia_e_dependencias_vazias_continuam_validos(monkeypatch):
    _, corpo = _update(monkeypatch, feature="", dependencies=[])
    assert corpo == {"feature": "", "dependencies": []}
