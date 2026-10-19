"""Interface web por HTTP: sessão por cookie, páginas, filtros, escape de HTML,
escrita pela tela e área admin."""

import pytest
from fastapi.testclient import TestClient

from src.main import app

from .conftest import ADMIN


def _logar(token: str, admin: bool = False) -> TestClient:
    c = TestClient(app, follow_redirects=False)
    r = c.post("/web/admin/login" if admin else "/web/login", data={"token": token})
    assert r.status_code == 303, r.text
    return c


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    ana.post(f"/projetos/{slug}/features", {"title": "Feat"})
    code = mundo.task(ana, slug, "Primeira", feature="F-1", tags=["api"], corpo="# Título\n\ntexto")
    mundo.mensagem(ana, slug, code, "pergunta", "tudo bem?")
    web_ana = _logar(ana.token)
    web_bia = _logar(bia.token)
    return mundo, ana, bia, slug, code, web_ana, web_bia


# ---------- sessão ---------- #


def test_sem_cookie_redireciona_pro_login(mundo):
    c = TestClient(app, follow_redirects=False)
    for caminho in ("/web", "/web/p/x", "/web/p/x/tasks", "/web/p/x/t/T-1", "/web/stream"):
        r = c.get(caminho)
        assert r.status_code == 303 and r.headers["location"] == "/web/login", caminho
    assert c.get("/web/login").status_code == 200
    assert c.get("/").headers["location"] == "/web"


def test_login_token_errado_401_sem_cookie_e_certo_grava_cookie_seguro(mundo):
    ana = mundo.pessoa("Ana")
    c = TestClient(app, follow_redirects=False)
    ruim = c.post("/web/login", data={"token": "errado"})
    assert ruim.status_code == 401 and "set-cookie" not in ruim.headers
    assert c.post("/web/login", data={}).status_code == 422
    ok = c.post("/web/login", data={"token": f"  {ana.token}  "})  # espaços sobrando
    assert ok.status_code == 303 and ok.headers["location"] == "/web"
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/web" in cookie
    assert c.get("/web").status_code == 200


def test_logout_limpa_e_token_reemitido_derruba_a_sessao(mundo):
    ana = mundo.pessoa("Ana")
    c = _logar(ana.token)
    assert c.get("/web").status_code == 200
    mundo.cliente.post(f"/people/{ana.id}/token", headers=mundo.admin)
    r = c.get("/web")
    assert r.status_code == 303 and r.headers["location"] == "/web/login"
    c2 = _logar(mundo.cliente.post(f"/people/{ana.id}/token", headers=mundo.admin).json()["token"])
    assert c2.get("/web").status_code == 200
    c2.post("/web/logout")
    assert c2.get("/web").status_code == 303


def test_cookie_de_pessoa_nao_abre_admin_e_vice_versa(mundo):
    ana = mundo.pessoa("Ana")
    pessoa = _logar(ana.token)
    r = pessoa.get("/web/admin/people")
    assert r.status_code == 303 and r.headers["location"] == "/web/admin/login"
    admin = _logar(ADMIN, admin=True)
    assert admin.get("/web/admin/people").status_code == 200
    r = admin.get("/web")
    assert r.status_code == 303 and r.headers["location"] == "/web/login"


def test_login_admin_errado(mundo):
    c = TestClient(app, follow_redirects=False)
    assert c.post("/web/admin/login", data={"token": "x"}).status_code == 401
    assert c.get("/web/admin/people").status_code == 303


# ---------- páginas ---------- #


def test_todas_as_paginas_do_membro_respondem_200(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    paginas = [
        "/web", f"/web/p/{slug}", f"/web/p/{slug}?por=agent", f"/web/p/{slug}/tasks",
        f"/web/p/{slug}/features", f"/web/p/{slug}/f/F-1", f"/web/p/{slug}/atividade",
        f"/web/p/{slug}/atividade/mais", f"/web/p/{slug}/t/{code}", f"/web/p/{slug}/t/T-1",
        f"/web/p/{slug}/t/{code}/corpo-diff?versao=1",
    ]
    for web in (web_ana, web_bia):
        for caminho in paginas:
            r = web.get(caminho)
            assert r.status_code == 200, (caminho, r.status_code, r.text[:300])


def test_nao_membro_recebe_404_em_tudo(cena):
    mundo, ana, bia, slug, code, *_ = cena
    web = _logar(mundo.pessoa("Intruso").token)
    for caminho in (
        f"/web/p/{slug}", f"/web/p/{slug}/tasks", f"/web/p/{slug}/features", f"/web/p/{slug}/f/F-1",
        f"/web/p/{slug}/atividade", f"/web/p/{slug}/t/{code}", f"/web/p/{slug}/t/{code}/corpo-diff?versao=1",
    ):
        assert web.get(caminho).status_code == 404, caminho
    assert web.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "mudanca", "texto": "x"}).status_code == 404
    assert web.post(f"/web/p/{slug}/t/{code}/campos", data={"status": "feito"}).status_code == 404
    assert web.get("/web").status_code == 200  # a home mostra só o que é dela
    assert slug not in web.get("/web").text


def test_inexistentes_dao_pagina_de_erro_e_nao_500(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    for caminho in (
        "/web/p/nao-existe", f"/web/p/{slug}/t/T-99", f"/web/p/{slug}/f/F-99",
        f"/web/p/{slug}/t/{code}/corpo-diff?versao=99",
    ):
        r = web_ana.get(caminho)
        assert r.status_code in (200, 404), (caminho, r.status_code)
    assert web_ana.get(f"/web/p/{slug}/t/T-99").status_code == 404
    assert web_ana.get(f"/web/p/{slug}/t/{code}/corpo-diff?versao=0").status_code == 422
    assert web_ana.get(f"/web/p/{slug}/t/{code}/corpo-diff").status_code == 422


# ---------- filtros ---------- #


FILTROS = [
    {}, {"status": "feito"}, {"status": ["ideia", "feito"]}, {"feature": "F-1"}, {"tag": "api"}, {"q": "Primeira"},
    {"q": "%"}, {"q": "'; DROP TABLE tasks;--"}, {"dono": "1"}, {"sem_dono": True}, {"fazendo": True},
    {"atencao": True}, {"paradas": True}, {"nao_lidas": True}, {"periodo": "24h"}, {"periodo": "7d"},
    {"periodo": "30d"}, {"ordem": "titulo"}, {"ordem": "dono"}, {"ordem": "recentes"}, {"ordem": "status"},
    {"visao": "quadro"}, {"agrupar": "feature"}, {"agrupar": "status"}, {"visao": "quadro", "agrupar": "feature"},
    {"status": "feito", "tag": "api", "q": "x", "nao_lidas": True, "ordem": "recentes", "agrupar": "feature"},
]


@pytest.mark.parametrize("params", FILTROS, ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()) or "vazio")
def test_filtros_da_lista_de_tasks(cena, params):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    for web in (web_ana, web_bia):
        r = web.get(f"/web/p/{slug}/tasks", params=params)
        assert r.status_code == 200, r.text[:300]
    assert mundo.sql("SELECT COUNT(*) AS n FROM tasks")[0]["n"] == 1


@pytest.mark.parametrize(
    "params",
    [{"status": "xyz"}, {"dono": "abc"}, {"periodo": "1y"}, {"ordem": "x"}, {"visao": "x"}, {"agrupar": "x"}],
)
def test_filtros_invalidos_422(cena, params):
    _, _, _, slug, _, web_ana, _ = cena
    assert web_ana.get(f"/web/p/{slug}/tasks", params=params).status_code == 422


def test_filtro_nao_lidas_so_mostra_o_que_a_pessoa_nao_leu(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    assert "Primeira" in web_bia.get(f"/web/p/{slug}/tasks", params={"nao_lidas": True}).text
    assert "Primeira" not in web_ana.get(f"/web/p/{slug}/tasks", params={"nao_lidas": True}).text


def test_filtros_da_atividade(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    for params in (
        {}, {"pessoa": "ana"}, {"agent": "claude"}, {"agent": "human"}, {"tipo": "mensagem"}, {"tipo": "status"},
        {"tipo": "campo"}, {"tipo": "corpo"}, {"tipo": "diff"}, {"tipo": "criacao"}, {"tipo": "feature"},
        {"task": code}, {"feature": "F-1"}, {"periodo": "24h"}, {"antes": 1}, {"antes": 999999},
    ):
        for rota in ("atividade", "atividade/mais"):
            r = web_ana.get(f"/web/p/{slug}/{rota}", params=params)
            assert r.status_code == 200, (rota, params, r.status_code)
    assert web_ana.get(f"/web/p/{slug}/atividade", params={"agent": "x"}).status_code == 422
    assert web_ana.get(f"/web/p/{slug}/atividade", params={"tipo": "x"}).status_code == 422
    assert web_ana.get(f"/web/p/{slug}/atividade", params={"antes": -1}).status_code == 422


def test_atividade_pagina_de_50_em_50(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    for i in range(60):
        mundo.mensagem(ana, slug, code, "mudanca", f"msg-numero-{i:03d}")
    pagina = web_ana.get(f"/web/p/{slug}/atividade").text
    assert "msg-numero-059" in pagina and "msg-numero-000" not in pagina
    ultimo = mundo.sql("SELECT MIN(seq) AS m FROM events WHERE seq > (SELECT MAX(seq) - 50 FROM events)")[0]["m"]
    mais = web_ana.get(f"/web/p/{slug}/atividade/mais", params={"antes": ultimo}).text
    assert "msg-numero-000" in mais


# ---------- ler na web não marca lido ---------- #


def test_abrir_a_task_na_web_nao_tira_do_nao_lido_da_ia(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    assert mundo.nao_lidos(bia, slug)["total"] == 1
    assert web_bia.get(f"/web/p/{slug}/t/{code}").status_code == 200
    assert mundo.nao_lidos(bia, slug)["total"] == 1
    assert web_bia.get(f"/web/p/{slug}/tasks").status_code == 200
    assert mundo.nao_lidos(bia, slug)["total"] == 1
    bia.get(f"/projetos/{slug}/tasks/{code}")
    assert mundo.nao_lidos(bia, slug)["total"] == 0


def test_contadores_da_web_refletem_nao_lidos(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    assert "contador" in web_bia.get(f"/web/p/{slug}/tasks").text
    assert "tem-notificacoes" in web_bia.get(f"/web/p/{slug}").text
    assert "tem-notificacoes" not in web_ana.get(f"/web/p/{slug}").text


def test_contador_da_web_nao_conta_historico_de_quem_acabou_de_entrar(cena):
    mundo, ana, bia, slug, code, *_ = cena
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")
    leo = mundo.pessoa("Leo")
    mundo.entrar(leo, slug, em="2026-02-01T10:00:00+00:00")
    web = _logar(leo.token)
    assert "tem-notificacoes" not in web.get(f"/web/p/{slug}").text
    assert "tem-notificacoes" not in web.get(f"/web/p/{slug}/tasks").text
    assert "tile-nao-lidos" not in web.get(f"/web/p/{slug}").text or ">0<" in web.get(f"/web/p/{slug}").text


# ---------- escrita pela tela ---------- #


def test_editar_campos_pela_tela(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    r = web_ana.post(
        f"/web/p/{slug}/t/{code}/campos",
        data={"status": "em_andamento", "owner_id": str(bia.id), "feature": "F-1", "tags": "api, ui ,,"},
    )
    assert r.status_code == 200, r.text[:300]
    t = ana.get(f"/projetos/{slug}/tasks/{code}").json()
    assert t["status"] == "em_andamento" and t["owner_id"] == bia.id
    assert t["tags"] == ["api", "ui"] and t["feature"]["code"].startswith("F-001")
    ev = [e for e in t["eventos"] if e["kind"] == "task.field_changed"]
    assert {e["actor"]["agent"] for e in ev} == {"human"}


def test_editar_campos_vazios_limpam_feature_e_tags(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={"status": "ideia", "owner_id": "", "feature": "", "tags": ""})
    t = ana.get(f"/projetos/{slug}/tasks/{code}").json()
    assert t["feature"] is None and t["tags"] == []


def test_editar_campos_entrada_invalida_nao_vira_500(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    base = {"status": "ideia", "owner_id": "", "feature": "F-1", "tags": ""}
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={**base, "status": "xyz"}).status_code == 422
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={**base, "owner_id": "abc"}).status_code == 422
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={**base, "owner_id": "9" * 30}).status_code == 422
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={**base, "owner_id": "99999"}).status_code in (404, 422)
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={**base, "feature": "F-99"}).status_code == 404
    assert web_ana.post(f"/web/p/{slug}/t/{code}/campos", data={"owner_id": ""}).status_code == 422


def test_editar_campos_respeita_dependencia_pela_tela(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    topo = mundo.task(ana, slug, "Topo", dependencies=[code])
    r = web_ana.post(
        f"/web/p/{slug}/t/{topo}/campos",
        data={"status": "feito", "owner_id": "", "feature": "", "tags": ""},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 409 and "#erro" in r.headers.get("hx-retarget", "")
    assert ana.get(f"/projetos/{slug}/tasks/{topo}").json()["status"] == "ideia"


def test_enviar_mensagem_pela_tela(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    r = web_bia.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "resposta", "texto": "tudo certo"})
    assert r.status_code == 200 and "tudo certo" in r.text
    ev = ana.get(f"/projetos/{slug}/tasks/{code}").json()["eventos"][-1]
    assert ev["payload"] == {"type": "resposta", "texto": "tudo certo"} and ev["actor"]["agent"] == "human"
    assert web_bia.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "resposta", "texto": ""}).status_code == 422
    assert web_bia.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "x", "texto": "y"}).status_code == 422
    assert web_bia.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "resposta"}).status_code == 422


def test_resposta_pela_tela_fecha_a_pergunta_aberta(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    web_bia.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "resposta", "texto": "sim"})
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json"}).json()
    assert rel["perguntas_abertas"] == []


def test_escrita_na_tela_aparece_pra_ia_como_nao_lido_do_outro(cena):
    mundo, ana, bia, slug, code, web_ana, web_bia = cena
    bia.get(f"/projetos/{slug}/tasks/{code}")
    web_ana.post(f"/web/p/{slug}/t/{code}/mensagens", data={"tipo": "decisao", "texto": "fechado"})
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "ana · " not in item["ultimo"] or "decisao: fechado" in item["ultimo"]
    assert "decisao: fechado" in item["ultimo"]


# ---------- escape de HTML ---------- #


PAYLOADS = ['<script>alert("xss1")</script>', '"><img src=x onerror=alert("xss2")>', "<b>negrito</b>"]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_html_dos_usuarios_e_escapado_em_todas_as_telas(mundo, payload):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana, nome=payload)
    ana.post(f"/projetos/{slug}/features", {"title": payload, "description": payload})
    code = mundo.task(ana, slug, payload, tags=[payload], feature="F-1", corpo=payload + "\n\n" + payload)
    mundo.mensagem(ana, slug, code, "pergunta", payload)
    ana.patch(f"/projetos/{slug}", {"description": payload})
    web = _logar(ana.token)
    paginas = [
        "/web", f"/web/p/{slug}", f"/web/p/{slug}/tasks", f"/web/p/{slug}/tasks?agrupar=feature",
        f"/web/p/{slug}/tasks?visao=quadro", f"/web/p/{slug}/features", f"/web/p/{slug}/f/F-1",
        f"/web/p/{slug}/atividade", f"/web/p/{slug}/t/{code}", f"/web/p/{slug}/t/{code}/corpo-diff?versao=1",
    ]
    for caminho in paginas:
        corpo = web.get(caminho).text
        assert "<script>alert" not in corpo, caminho
        assert "<img src=x" not in corpo, caminho
        assert "<b>negrito</b>" not in corpo, caminho
    adm = _logar(ADMIN, admin=True)
    for caminho in ("/web/admin/projetos", f"/web/admin/p/{slug}", f"/web/admin/p/{slug}/t/{code}"):
        corpo = adm.get(caminho).text
        assert "<script>alert" not in corpo and "<img src=x" not in corpo, caminho


def test_nome_de_pessoa_com_html_e_escapado_no_admin_e_na_web(mundo):
    r = mundo.cliente.post(
        "/people", json={"email": "xss@x.com", "name": "<script>alert(9)</script>"}, headers=mundo.admin
    )
    pid = r.json()["id"]
    token = mundo.cliente.post(f"/people/{pid}/token", headers=mundo.admin).json()["token"]
    adm = _logar(ADMIN, admin=True)
    assert "<script>alert(9)" not in adm.get("/web/admin/people").text
    assert "<script>alert(9)" not in _logar(token).get("/web").text


def test_markdown_nao_gera_link_javascript(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    ana.put(f"/projetos/{slug}/tasks/{code}/corpo", {"texto": "[clique](javascript:alert(1)) e [ok](https://x.com)"})
    corpo = web_ana.get(f"/web/p/{slug}/t/{code}").text
    assert 'href="javascript:' not in corpo.lower()
    assert 'href="https://x.com"' in corpo


# ---------- admin ---------- #


def test_admin_cria_pessoa_emite_token_e_token_so_aparece_na_resposta(mundo):
    adm = _logar(ADMIN, admin=True)
    r = adm.post("/web/admin/people", data={"email": "nova@x.com", "name": "Nova"})
    assert r.status_code == 200 and "nova@x.com" in r.text
    pid = mundo.sql("SELECT id FROM people WHERE email = 'nova@x.com'")[0]["id"]
    emitido = adm.post(f"/web/admin/people/{pid}/token")
    assert emitido.status_code == 200
    token = mundo.cliente.post(f"/people/{pid}/token", headers=mundo.admin).json()["token"]
    assert token not in adm.get("/web/admin/people").text
    assert adm.post("/web/admin/people", data={"email": "nova@x.com", "name": "Dup"}).status_code == 409
    assert adm.post("/web/admin/people", data={"email": "ruim", "name": "x"}).status_code == 422
    assert adm.post(f"/web/admin/people/{pid}", data={"email": "outra@x.com", "name": "N"}).status_code == 200


def test_admin_le_projeto_sem_marcar_lido_nem_mostrar_nao_lidos(cena):
    mundo, ana, bia, slug, code, *_ = cena
    adm = _logar(ADMIN, admin=True)
    for caminho in (
        "/web/admin/projetos", f"/web/admin/p/{slug}", f"/web/admin/p/{slug}/tasks", f"/web/admin/p/{slug}/features",
        f"/web/admin/p/{slug}/f/F-1", f"/web/admin/p/{slug}/atividade", f"/web/admin/p/{slug}/atividade/mais",
        f"/web/admin/p/{slug}/t/{code}", f"/web/admin/p/{slug}/t/{code}/corpo-diff?versao=1",
    ):
        assert adm.get(caminho).status_code == 200, caminho
    assert mundo.nao_lidos(bia, slug)["total"] == 1
    assert mundo.sql("SELECT COUNT(*) AS n FROM task_reads")[0]["n"] == 0
    assert adm.get("/web/admin/p/nao-existe").status_code == 404


def test_admin_membros_e_pedidos(mundo):
    ana, bia, leo = mundo.pessoa("Ana"), mundo.pessoa("Bia"), mundo.pessoa("Leo")
    slug = mundo.projeto(ana, visibility="private")
    adm = _logar(ADMIN, admin=True)
    assert adm.post(f"/web/admin/p/{slug}/membros", data={"email": bia.email}).status_code == 200
    assert adm.post(f"/web/admin/p/{slug}/membros", data={"email": "ninguem@x.com"}).status_code == 404
    pedido = leo.post(f"/projetos/{slug}/pedidos").json()
    assert adm.post(f"/web/admin/p/{slug}/pedidos/{pedido['id']}/aceitar").status_code == 200
    assert adm.post(f"/web/admin/p/{slug}/pedidos/{pedido['id']}/aceitar").status_code == 404
    assert adm.post(f"/web/admin/p/{slug}/pedidos/{pedido['id']}/abracar").status_code == 422
    assert leo.get(f"/projetos/{slug}/tasks").status_code == 200


def test_admin_apagar_projeto_manda_hx_redirect(cena):
    mundo, ana, bia, slug, *_ = cena
    adm = _logar(ADMIN, admin=True)
    r = adm.post(f"/web/admin/p/{slug}/apagar")
    assert r.status_code == 204 and r.headers["hx-redirect"] == "/web/admin/projetos"
    assert mundo.sql("SELECT COUNT(*) AS n FROM projects")[0]["n"] == 0


def test_rotas_de_escrita_do_admin_exigem_sessao_admin(cena):
    mundo, ana, bia, slug, code, web_ana, _ = cena
    anonimo = TestClient(app, follow_redirects=False)
    for c in (anonimo, web_ana):
        r = c.post(f"/web/admin/p/{slug}/apagar")
        assert r.status_code == 303 and "/web/admin/login" in r.headers["location"]
        assert c.post("/web/admin/people", data={"email": "a@b.com", "name": "x"}).status_code == 303
    assert mundo.sql("SELECT COUNT(*) AS n FROM projects")[0]["n"] == 1


def test_htmx_sem_sessao_vira_hx_redirect(mundo):
    c = TestClient(app, follow_redirects=False)
    r = c.get("/web/p/x/tasks", headers={"HX-Request": "true"})
    assert r.status_code == 204 and r.headers["hx-redirect"] == "/web/login"


# ---------- estáticos e tempo real ---------- #


def test_estaticos_servidos(mundo):
    c = TestClient(app)
    for caminho in ("/web/static/app.css", "/web/static/htmx.min.js", "/web/static/tela.js"):
        r = c.get(caminho)
        assert r.status_code == 200 and len(r.content) > 100, caminho
    assert c.get("/web/static/nao-existe.js").status_code == 404
    assert c.get("/web/static/../main.py").status_code in (400, 404)
    assert c.get("/web/static/%2e%2e/main.py").status_code in (400, 404)


def test_banco_nao_e_servido(mundo):
    c = TestClient(app)
    for caminho in ("/sync.db", "/web/static/sync.db", "/.env", "/web/.env"):
        assert c.get(caminho).status_code == 404, caminho

