"""Dono da task: `owner_id: null` explícito tira o dono, campo omitido não mexe, e a
tela distingue "não mudar" de "sem dono"."""

import pytest

from .test_web import _logar


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    code = mundo.task(ana, slug, "Com dono", owner_id=bia.id, tags=["x"])
    return mundo, ana, bia, slug, code


def _t(slug, code):
    return f"/projetos/{slug}/tasks/{code}"


def test_owner_null_explicito_tira_o_dono_e_gera_evento(cena):
    mundo, ana, bia, slug, code = cena
    resp = ana.patch(_t(slug, code), {"owner_id": None})
    assert resp.status_code == 200 and resp.json()["owner_id"] is None and resp.json()["owner"] is None
    ev = mundo.sql("SELECT valor_de, valor_para FROM events WHERE campo = 'owner_id'")
    assert [(r["valor_de"], r["valor_para"]) for r in ev] == [(str(bia.id), None)]


def test_campo_omitido_nao_mexe_no_dono(cena):
    mundo, ana, bia, slug, code = cena
    for corpo in ({"status": "feito"}, {"title": "Outro"}, {"tags": []}, {"feature": ""}):
        assert ana.patch(_t(slug, code), corpo).status_code == 200
        assert ana.get(_t(slug, code)).json()["owner_id"] == bia.id, corpo


def test_owner_null_junto_de_outros_campos(cena):
    mundo, ana, bia, slug, code = cena
    r = ana.patch(_t(slug, code), {"owner_id": None, "status": "parcial"})
    assert r.json()["owner_id"] is None and r.json()["status"] == "parcial"


def test_owner_null_sem_dono_nao_gera_evento(cena):
    mundo, ana, bia, slug, code = cena
    ana.patch(_t(slug, code), {"owner_id": None})
    antes = mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"]
    r = ana.patch(_t(slug, code), {"owner_id": None})
    assert r.status_code == 200 and r.json()["cursor"] is None
    assert mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"] == antes


def test_trocar_o_dono_continua_valendo_e_valida_membro(cena):
    mundo, ana, bia, slug, code = cena
    assert ana.patch(_t(slug, code), {"owner_id": ana.id}).json()["owner_id"] == ana.id
    intruso = mundo.pessoa("Intruso")
    assert ana.patch(_t(slug, code), {"owner_id": intruso.id}).status_code == 422
    assert ana.get(_t(slug, code)).json()["owner_id"] == ana.id


def test_patch_so_com_owner_null_nao_e_patch_vazio(cena):
    _, ana, _, slug, code = cena
    assert ana.patch(_t(slug, code), {}).status_code == 422
    assert ana.patch(_t(slug, code), {"owner_id": None}).status_code == 200


def test_tirar_dono_reflete_na_lista_e_no_aviso_de_nao_lidos(cena):
    mundo, ana, bia, slug, code = cena
    bia.get(_t(slug, code))
    ana.patch(_t(slug, code), {"owner_id": None})
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "owner_id" in item["ultimo"]
    assert ana.get(f"/projetos/{slug}/tasks").json()[0]["owner"] is None


# ---------- tela ---------- #


def _campos(owner_id, **extra):
    return {"status": "ideia", "owner_id": owner_id, "feature": "", "tags": "x", **extra}


def test_web_select_tem_sem_dono_e_nao_duplica_o_dono_atual(cena):
    mundo, ana, bia, slug, code = cena
    web = _logar(ana.token)
    html = web.get(f"/web/p/{slug}/t/{code}").text
    assert '<option value="0" >sem dono</option>' in html or '<option value="0" >sem dono' in html
    assert html.count(f'<option value="{bia.id}" selected>') == 1
    assert '<option value="" selected>' not in html


def test_web_sem_dono_vem_selecionado(cena):
    mundo, ana, bia, slug, code = cena
    ana.patch(_t(slug, code), {"owner_id": None})
    html = _logar(ana.token).get(f"/web/p/{slug}/t/{code}").text
    assert '<option value="0" selected>sem dono</option>' in html


def test_web_sem_dono_tira_o_dono(cena):
    mundo, ana, bia, slug, code = cena
    web = _logar(ana.token)
    assert web.post(f"/web/p/{slug}/t/{code}/campos", data=_campos("0")).status_code == 200
    assert ana.get(_t(slug, code)).json()["owner_id"] is None


def test_web_vazio_nao_muda_o_dono(cena):
    mundo, ana, bia, slug, code = cena
    web = _logar(ana.token)
    web.post(f"/web/p/{slug}/t/{code}/campos", data=_campos("", status="parcial"))
    t = ana.get(_t(slug, code)).json()
    assert t["owner_id"] == bia.id and t["status"] == "parcial"


def test_web_trocar_de_dono(cena):
    mundo, ana, bia, slug, code = cena
    web = _logar(ana.token)
    web.post(f"/web/p/{slug}/t/{code}/campos", data=_campos(str(ana.id)))
    assert ana.get(_t(slug, code)).json()["owner_id"] == ana.id


def test_web_dono_que_saiu_do_projeto_aparece_como_nao_mudar(cena):
    mundo, ana, bia, slug, code = cena
    mundo.sql("DELETE FROM memberships WHERE person_id = ?", (bia.id,))
    web = _logar(ana.token)
    html = web.get(f"/web/p/{slug}/t/{code}").text
    assert '<option value="" selected>' in html and "Bia" in html
    web.post(f"/web/p/{slug}/t/{code}/campos", data=_campos("", status="parcial"))
    assert ana.get(_t(slug, code)).json()["owner_id"] == bia.id
    web.post(f"/web/p/{slug}/t/{code}/campos", data=_campos("0"))
    assert ana.get(_t(slug, code)).json()["owner_id"] is None
