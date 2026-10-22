"""Features (código, status derivado, tasks soltas) e a trilha de eventos
(`/mudancas`, relatório)."""

import pytest


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    return mundo, ana, bia, slug


def _f(slug, code=""):
    return f"/projetos/{slug}/features/{code}".rstrip("/")


def _t(slug, code=""):
    return f"/projetos/{slug}/tasks/{code}".rstrip("/")


# ---------- features ---------- #


def test_criar_feature_code_e_validacao(cena):
    _, ana, _, slug = cena
    f = ana.post(_f(slug), {"title": "Login social", "description": "oauth"})
    assert f.status_code == 201
    dados = f.json()
    assert dados["code"] == "F-001-login-social" and dados["status"] == "ideia"
    assert dados["progresso"] == {"feito": 0, "total": 0}
    assert ana.post(_f(slug), {"title": ""}).status_code == 422
    assert ana.post(_f(slug), {"title": "Outra"}).json()["code"].startswith("F-002")


def test_feature_acha_por_numero_e_404(cena):
    _, ana, _, slug = cena
    ana.post(_f(slug), {"title": "A"})
    for forma in ("F-1", "F-001", "f-1", "F-001-a"):
        assert ana.get(_f(slug, forma)).status_code == 200, forma
    assert ana.get(_f(slug, "F-2")).status_code == 404
    assert ana.get(_f(slug, "banana")).status_code == 404


@pytest.mark.parametrize(
    ("statuses", "esperado"),
    [
        ([], "ideia"),
        (["ideia", "ideia"], "ideia"),
        (["feito", "feito"], "feito"),
        (["feito", "ideia"], "parcial"),
        (["feito", "bloqueado"], "bloqueado"),
        (["em_andamento", "bloqueado"], "bloqueado"),
        (["em_andamento", "ideia"], "em_andamento"),
        (["parcial", "ideia"], "parcial"),
        (["aguardando_decisao", "feito"], "parcial"),
        (["aguardando_decisao"], "parcial"),
    ],
)
def test_status_derivado_da_feature(cena, statuses, esperado):
    mundo, ana, _, slug = cena
    ana.post(_f(slug), {"title": "F"})
    for i, st in enumerate(statuses):
        mundo.task(ana, slug, f"t{i}", status=st, feature="F-1")
    assert ana.get(_f(slug, "F-1")).json()["status"] == esperado


def test_progresso_e_contagem_da_feature(cena):
    mundo, ana, _, slug = cena
    ana.post(_f(slug), {"title": "F"})
    mundo.task(ana, slug, "a", status="feito", feature="F-1")
    mundo.task(ana, slug, "b", feature="F-1")
    f = ana.get(_f(slug, "F-1")).json()
    assert f["progresso"] == {"feito": 1, "total": 2}
    assert f["contagem_status"] == {"feito": 1, "ideia": 1}
    assert [t["status"] for t in f["tasks"]] == ["feito", "ideia"]


def test_update_feature_e_eventos(cena):
    mundo, ana, _, slug = cena
    ana.post(_f(slug), {"title": "Velha"})
    assert ana.patch(_f(slug, "F-1"), {}).status_code == 422
    r = ana.patch(_f(slug, "F-1"), {"title": "Nova", "description": "d"})
    assert r.status_code == 200 and r.json()["title"] == "Nova"
    assert r.json()["code"] == "F-001-velha"  # code não acompanha o título
    igual = ana.patch(_f(slug, "F-1"), {"title": "Nova"})
    assert igual.status_code == 200 and igual.json()["cursor"] is None
    assert ana.patch(_f(slug, "F-9"), {"title": "x"}).status_code == 404


def test_mover_e_tirar_task_de_feature(cena):
    mundo, ana, _, slug = cena
    ana.post(_f(slug), {"title": "A"})
    ana.post(_f(slug), {"title": "B"})
    code = mundo.task(ana, slug, feature="F-1")
    assert ana.patch(_t(slug, code), {"feature": "F-2"}).json()["feature"]["code"].startswith("F-002")
    assert ana.patch(_t(slug, code), {"feature": ""}).json()["feature"] is None
    assert ana.patch(_t(slug, code), {"feature": "F-9"}).status_code == 404
    campos = [r["valor_para"] for r in mundo.sql("SELECT valor_para FROM events WHERE campo = 'feature'")]
    assert campos == ["F-002-b", None]


def test_apagar_feature_solta_as_tasks_e_registra_evento(cena):
    mundo, ana, _, slug = cena
    ana.post(_f(slug), {"title": "Some"})
    code = mundo.task(ana, slug, feature="F-1")
    resp = ana.delete(_f(slug, "F-1"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["tasks_soltas"] == [code]
    assert ana.get(_t(slug, code)).json()["feature"] is None
    assert ana.get(_f(slug, "F-1")).status_code == 404
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json"}).json()
    assert rel["features_apagadas"] == ["F-001-some"]


def test_feature_de_outro_projeto_nao_e_alcancavel(cena):
    mundo, ana, _, slug = cena
    outro = mundo.projeto(ana, "Outro")
    ana.post(_f(outro), {"title": "Alheia"})
    assert ana.get(_f(slug, "F-1")).status_code == 404
    assert ana.post(_t(slug), {"title": "x", "feature": "F-1"}).status_code == 404


# ---------- /mudancas ---------- #


def test_mudancas_cursor_limite_e_de_outros(cena):
    mundo, ana, bia, slug = cena
    a = mundo.task(ana, slug, "A")
    mundo.mensagem(bia, slug, a, "mudanca", "da bia")
    mundo.mensagem(ana, slug, a, "mudanca", "da ana")
    tudo = ana.get(f"/projetos/{slug}/mudancas").json()
    assert tudo["total"] == 3 and tudo["cursor"] == tudo["eventos"][-1]["seq"]
    primeira = ana.get(f"/projetos/{slug}/mudancas", params={"limite": 2}).json()
    assert primeira["total"] == 2
    resto = ana.get(f"/projetos/{slug}/mudancas", params={"desde": primeira["cursor"]}).json()
    assert resto["total"] == 1
    vazio = ana.get(f"/projetos/{slug}/mudancas", params={"desde": tudo["cursor"]}).json()
    assert vazio["total"] == 0 and vazio["cursor"] == tudo["cursor"]
    outros = ana.get(f"/projetos/{slug}/mudancas", params={"de_outros": True}).json()
    assert [e["actor"]["person"].startswith("bia") for e in outros["eventos"]] == [True]


def test_mudancas_valida_parametros(cena):
    _, ana, _, slug = cena
    for params in ({"desde": -1}, {"limite": 0}, {"limite": 5000}, {"desde": "x"}):
        assert ana.get(f"/projetos/{slug}/mudancas", params=params).status_code == 422, params


def test_mudancas_nao_mistura_projetos(cena):
    mundo, ana, _, slug = cena
    outro = mundo.projeto(ana, "Outro")
    mundo.task(ana, outro, "so no outro")
    assert ana.get(f"/projetos/{slug}/mudancas").json()["total"] == 0


def test_envelope_do_evento_tem_git_e_resumo(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    r = ana.post(
        f"{_t(slug, code)}/mensagens",
        {"type": "decisao", "texto": "linha 1\nlinha 2"},
        headers={"X-Git-Branch": "feat/x", "X-Git-Commit": "c" * 40},
    ).json()
    assert r["git"] == {"branch": "feat/x", "commit": "c" * 40}
    assert r["resumo"].endswith("decisao: linha 1") and "(feat/x)" in r["resumo"]


# ---------- relatório ---------- #


def test_relatorio_json_e_markdown(cena):
    mundo, ana, bia, slug = cena
    ana.post(_f(slug), {"title": "Feat"})
    code = mundo.task(ana, slug, "Com corpo", feature="F-1", status="em_andamento")
    ana.put(f"{_t(slug, code)}/corpo", {"texto": "a\nb\n"})
    bia.patch(_t(slug, code), {"status": "bloqueado"})
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json"}).json()
    assert rel["contagem_status"] == {"bloqueado": 1}
    assert rel["cursor"] == rel["eventos"][-1]["seq"]
    assert sum(rel["contagem_autor"].values()) == len(rel["eventos"])
    md = ana.get(f"/projetos/{slug}/relatorio")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "Com corpo" in md.text and "Diff do corpo" in md.text and "bloqueado" in md.text
    sem_diff = ana.get(f"/projetos/{slug}/relatorio", params={"com_diff": False}).text
    assert "Diff do corpo" not in sem_diff


def test_relatorio_desde_filtra_a_janela_e_formato_invalido(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    corte = ana.get(f"/projetos/{slug}/mudancas").json()["cursor"]
    mundo.mensagem(ana, slug, code, "mudanca", "nova")
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json", "desde": corte}).json()
    assert len(rel["eventos"]) == 1 and rel["desde"] == corte
    assert ana.get(f"/projetos/{slug}/relatorio", params={"formato": "xml"}).status_code == 422


def test_relatorio_de_projeto_vazio(cena):
    _, ana, _, slug = cena
    md = ana.get(f"/projetos/{slug}/relatorio")
    assert md.status_code == 200 and "Nenhuma task" in md.text


def test_relatorio_markdown_com_titulo_estranho_nao_quebra(cena):
    mundo, ana, _, slug = cena
    mundo.task(ana, slug, "Título com `crase` | pipe <b>html</b> e emoji 🚀", corpo="x\n")
    assert ana.get(f"/projetos/{slug}/relatorio").status_code == 200


# ---------- stream (SSE) ---------- #


def test_stream_exige_token_e_membership(cena):
    mundo, ana, _, slug = cena
    intruso = mundo.pessoa("Intruso")
    c = mundo.cliente
    assert c.get("/stream", params={"projeto": slug}).status_code == 401
    assert c.get("/stream", params={"projeto": slug, "token": "errado"}).status_code == 401
    assert c.get("/stream", params={"projeto": slug}, headers={"Authorization": ana.h["Authorization"]}).status_code == 400
    assert c.get("/stream", params={"projeto": slug}, headers=intruso.h).status_code == 404
    assert c.get("/stream", params={"projeto": "nada"}, headers=ana.h).status_code == 404


# ---------- saúde ---------- #


def test_health_e_changelog(mundo):
    h = mundo.cliente.get("/health").json()
    assert h["online"] is True and h["bancoConectado"] is True
    assert mundo.cliente.get("/changelog").status_code == 200
