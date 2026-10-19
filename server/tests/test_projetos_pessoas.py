"""Pessoas, tokens, projetos, membros, pedidos de acesso e repositórios."""

import pytest

from .conftest import ADMIN


def _admin(mundo):
    return mundo.admin


# ---------- pessoas e tokens ---------- #


def test_rotas_de_admin_exigem_token_de_admin(mundo):
    ana = mundo.pessoa("Ana")
    c = mundo.cliente
    corpo = {"email": "x@y.com", "name": "X"}
    assert c.post("/people", json=corpo).status_code == 401
    assert c.post("/people", json=corpo, headers={"Authorization": "Bearer errado"}).status_code == 401
    assert c.post("/people", json=corpo, headers=ana.h).status_code == 401  # token pessoal não é admin
    assert c.get("/people").status_code == 401
    assert c.get("/people", headers=ana.h).status_code == 401
    assert c.patch(f"/people/{ana.id}", json={"name": "Z"}, headers=ana.h).status_code == 401
    assert c.delete(f"/people/{ana.id}", headers=ana.h).status_code == 401
    assert c.post(f"/people/{ana.id}/token", headers=ana.h).status_code == 401
    assert c.post("/people", json=corpo, headers={"Authorization": f"Basic {ADMIN}"}).status_code == 401


def test_criar_pessoa_validacoes_e_alias(mundo):
    c, h = mundo.cliente, mundo.admin
    ok = c.post("/people", json={"email": "Arthur.Macedo@Empresa.com", "name": "Arthur"}, headers=h)
    assert ok.status_code == 201
    assert ok.json()["alias"] == "arthur.macedo" and ok.json()["email"] == "arthur.macedo@empresa.com"
    assert c.post("/people", json={"email": "arthur.macedo@empresa.com", "name": "Outro"}, headers=h).status_code == 409
    for ruim in ("sem-arroba", "a@b", "a b@c.com", "@c.com", ""):
        assert c.post("/people", json={"email": ruim, "name": "X"}, headers=h).status_code == 422, ruim
    assert c.post("/people", json={"email": "ok@ok.com", "name": ""}, headers=h).status_code == 422


def test_email_com_caixa_diferente_conflita(mundo):
    c, h = mundo.cliente, mundo.admin
    c.post("/people", json={"email": "ana@x.com", "name": "Ana"}, headers=h)
    resp = c.post("/people", json={"email": "ANA@x.com", "name": "Ana 2"}, headers=h)
    assert resp.status_code == 409, resp.text


def test_token_reemitido_invalida_o_anterior(mundo):
    ana = mundo.pessoa("Ana")
    antigo = ana.token
    novo = mundo.cliente.post(f"/people/{ana.id}/token", headers=mundo.admin).json()["token"]
    assert novo != antigo
    assert mundo.cliente.get("/me", headers={"Authorization": f"Bearer {antigo}"}).status_code == 401
    assert mundo.cliente.get("/me", headers={"Authorization": f"Bearer {novo}"}).status_code == 200


def test_token_de_pessoa_inexistente_404_e_guarda_so_o_hash(mundo):
    assert mundo.cliente.post("/people/9999/token", headers=mundo.admin).status_code == 404
    ana = mundo.pessoa("Ana")
    guardado = mundo.sql("SELECT token_hash FROM people WHERE id = ?", (ana.id,))[0]["token_hash"]
    assert guardado and guardado != ana.token and ana.token not in guardado


def test_me_e_tokens_malformados(mundo):
    ana = mundo.pessoa("Ana")
    r = mundo.cliente.get("/me", headers=ana.h)
    assert r.status_code == 200 and r.json()["id"] == ana.id and "token" not in r.json()
    c = mundo.cliente
    assert c.get("/me").status_code == 401
    assert c.get("/me", headers={"Authorization": "Bearer"}).status_code == 401
    assert c.get("/me", headers={"Authorization": "Bearer "}).status_code == 401
    assert c.get("/me", headers={"Authorization": ana.token}).status_code == 401
    assert c.get("/me", headers={"Authorization": f"bearer {ana.token}"}).status_code == 200


def test_pessoa_sem_token_nao_autentica(mundo):
    mundo.cliente.post("/people", json={"email": "sem@token.com", "name": "Sem"}, headers=mundo.admin)
    assert mundo.cliente.get("/me", headers={"Authorization": "Bearer None"}).status_code == 401
    assert mundo.cliente.get("/me", headers={"Authorization": "Bearer null"}).status_code == 401


def test_listar_pessoas_mostra_tem_token_sem_vazar_hash(mundo):
    mundo.pessoa("Ana")
    mundo.cliente.post("/people", json={"email": "sem@token.com", "name": "Sem"}, headers=mundo.admin)
    lista = mundo.cliente.get("/people", headers=mundo.admin).json()
    assert {p["email"].split("@")[0][:3]: p["tem_token"] for p in lista} == {"ana": True, "sem": False}
    assert all("token_hash" not in p for p in lista)


def test_patch_pessoa_e_conflito_de_email(mundo):
    a, b = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    c, h = mundo.cliente, mundo.admin
    assert c.patch(f"/people/{a.id}", json={"name": "Ana Maria"}, headers=h).status_code == 200
    resp = c.patch(f"/people/{a.id}", json={"email": b.email}, headers=h)
    assert resp.status_code == 409, resp.text
    assert c.patch(f"/people/{a.id}", json={}, headers=h).status_code == 422
    assert c.patch("/people/9999", json={"name": "X"}, headers=h).status_code == 404


def test_apagar_pessoa_com_historico_nao_vira_500(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    mundo.task(ana, slug)
    resp = mundo.cliente.delete(f"/people/{ana.id}", headers=mundo.admin)
    assert resp.status_code == 409, resp.text


def test_apagar_pessoa_sem_historico_e_pessoa_inexistente(mundo):
    ana = mundo.pessoa("Ana")
    assert mundo.cliente.delete(f"/people/{ana.id}", headers=mundo.admin).status_code == 204
    assert mundo.cliente.get("/me", headers=ana.h).status_code == 401
    assert mundo.cliente.delete("/people/9999", headers=mundo.admin).status_code == 404


# ---------- projetos ---------- #


def test_criar_projeto_vira_owner_e_slug_nao_colide(mundo):
    ana = mundo.pessoa("Ana")
    corpo = {"name": "Meu App", "visibility": "team", "repo": {"root_sha": "a" * 40, "name": "r"}}
    p1 = ana.post("/projetos", corpo).json()
    p2 = ana.post("/projetos", {**corpo, "repo": {"root_sha": "b" * 40, "name": "r"}}).json()
    assert p1["role"] == "owner" and p1["slug"] == "meu-app"
    assert p2["slug"] != p1["slug"] and p2["slug"].startswith("meu-app")


def test_slug_de_nome_so_simbolos_e_nome_acentuado(mundo):
    ana = mundo.pessoa("Ana")
    base = {"visibility": "team"}
    a = ana.post("/projetos", {**base, "name": "!!!", "repo": {"root_sha": "a" * 7, "name": "r"}}).json()
    assert a["slug"] == "projeto"
    b = ana.post("/projetos", {**base, "name": "Gestão de Pátio", "repo": {"root_sha": "b" * 7, "name": "r"}})
    assert b.status_code == 201 and b.json()["slug"] == "gestao-de-patio"


def test_criar_projeto_valida_entrada(mundo):
    ana = mundo.pessoa("Ana")
    ok_repo = {"root_sha": "a" * 40, "name": "r"}
    assert ana.post("/projetos", {"name": "", "visibility": "team", "repo": ok_repo}).status_code == 422
    assert ana.post("/projetos", {"name": "x", "visibility": "publico", "repo": ok_repo}).status_code == 422
    assert ana.post("/projetos", {"name": "x", "visibility": "team"}).status_code == 422
    for sha in ("xyz", "abc", "A" * 40, "a" * 41):
        resp = ana.post("/projetos", {"name": "x", "visibility": "team", "repo": {"root_sha": sha, "name": "r"}})
        assert resp.status_code == 422, sha


def test_mesmo_repo_em_dois_projetos_e_resolve_devolve_os_dois(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    sha = "c" * 40
    for nome in ("Um", "Dois"):
        ana.post("/projetos", {"name": nome, "visibility": "team", "repo": {"root_sha": sha, "name": "r"}})
    resp = bia.post("/repos/resolve", {"root_sha": sha, "name": "r"})
    assert resp.status_code == 200
    assert sorted(p["slug"] for p in resp.json()) == ["dois", "um"]
    assert {p["role"] for p in resp.json()} == {"member"}


def test_resolve_repo_desconhecido_404_e_privado_vem_sem_role(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    assert bia.post("/repos/resolve", {"root_sha": "d" * 40, "name": "r"}).status_code == 404
    slug = mundo.projeto(ana, visibility="private")
    (item,) = bia.post("/repos/resolve", {"root_sha": mundo.shas[slug], "name": "r"}).json()
    assert item["role"] is None and "repos" not in item and "created_by" not in item
    assert bia.get(f"/projetos/{slug}/tasks").status_code == 404


def test_resolve_repo_repetido_e_idempotente(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    for _ in range(3):
        assert bia.post("/repos/resolve", {"root_sha": mundo.shas[slug], "name": "r"}).status_code == 200
    membros = ana.get(f"/projetos/{slug}/membros").json()
    assert len(membros) == 2


def test_listar_projetos_mostra_existencia_mas_nao_vaza_privado(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    publico = mundo.projeto(ana, "Publico")
    privado = mundo.projeto(ana, "Privado", visibility="private")
    lista = {p["slug"]: p for p in bia.get("/projetos").json()}
    assert set(lista) == {publico, privado}
    assert lista[privado]["role"] is None and "repos" not in lista[privado]
    assert lista[publico]["role"] is None  # team: existe, mas entrar é via repo
    mundo.entrar(bia, publico)
    assert {p["slug"]: p["role"] for p in bia.get("/projetos").json()}[publico] == "member"


def test_projeto_inexistente_ou_sem_acesso_da_o_mesmo_404(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    slug = mundo.projeto(ana, visibility="private")
    for rota in ("tasks", "membros", "features", "mudancas", "relatorio", "nao-lidos", "pedidos"):
        a = bia.get(f"/projetos/{slug}/{rota}")
        b = bia.get(f"/projetos/nao-existe/{rota}")
        assert a.status_code == b.status_code == 404, rota
        assert a.json() == b.json() or "existe" in a.json()["detail"], rota


def test_escrita_em_projeto_sem_acesso_e_barrada(mundo):
    ana, intruso = mundo.pessoa("Ana"), mundo.pessoa("Intruso")
    slug = mundo.projeto(ana)
    code = mundo.task(ana, slug)
    assert intruso.post(f"/projetos/{slug}/tasks", {"title": "x"}).status_code == 404
    assert intruso.patch(f"/projetos/{slug}/tasks/{code}", {"status": "feito"}).status_code == 404
    msg = {"type": "mudanca", "texto": "x"}
    assert intruso.post(f"/projetos/{slug}/tasks/{code}/mensagens", msg).status_code == 404
    assert intruso.put(f"/projetos/{slug}/tasks/{code}/corpo", {"texto": "x"}).status_code == 404
    assert intruso.post(f"/projetos/{slug}/features", {"title": "x"}).status_code == 404
    assert intruso.patch(f"/projetos/{slug}", {"name": "x"}).status_code == 404


def test_update_projeto_visibilidade_so_owner_e_patch_vazio(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    assert bia.patch(f"/projetos/{slug}", {"visibility": "private"}).status_code == 403
    assert bia.patch(f"/projetos/{slug}", {"name": "Novo nome"}).status_code == 200
    assert ana.patch(f"/projetos/{slug}", {"visibility": "private"}).status_code == 200
    assert ana.patch(f"/projetos/{slug}", {}).status_code == 422
    assert ana.patch(f"/projetos/{slug}", {"status": "invalido"}).status_code == 422
    assert ana.patch(f"/projetos/{slug}", {"status": "arquivado"}).json()["status"] == "arquivado"


def test_apagar_projeto_so_admin_e_cascata(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    mundo.task(ana, slug)
    assert ana.delete(f"/projetos/{slug}").status_code == 401
    assert mundo.cliente.delete(f"/projetos/{slug}", headers=mundo.admin).status_code == 204
    for tabela in ("tasks", "events", "memberships", "project_repos", "task_reads"):
        assert mundo.sql(f"SELECT COUNT(*) AS n FROM {tabela}")[0]["n"] == 0, tabela
    assert mundo.cliente.delete(f"/projetos/{slug}", headers=mundo.admin).status_code == 404


# ---------- vincular repo ---------- #


def test_vincular_repo_team_entra_como_membro_e_e_idempotente(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    novo = {"root_sha": "e" * 40, "name": "segundo"}
    for _ in range(2):
        assert bia.post(f"/projetos/{slug}/repos", novo).status_code == 201
    repos = ana.get("/projetos").json()[0]["repos"]
    assert len(repos) == 2
    assert bia.get(f"/projetos/{slug}/tasks").status_code == 200


def test_vincular_repo_em_projeto_privado_exige_ser_membro(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    slug = mundo.projeto(ana, visibility="private")
    assert bia.post(f"/projetos/{slug}/repos", {"root_sha": "f" * 40, "name": "r"}).status_code == 404
    assert bia.get(f"/projetos/{slug}/tasks").status_code == 404
    assert ana.post(f"/projetos/{slug}/repos", {"root_sha": "f" * 40, "name": "r"}).status_code == 201


# ---------- membros e pedidos ---------- #


def test_owner_convida_membro_e_regras_do_convite(mundo):
    ana, bia, leo = mundo.pessoa("Ana"), mundo.pessoa("Bia"), mundo.pessoa("Leo")
    slug = mundo.projeto(ana, visibility="private")
    assert ana.post(f"/projetos/{slug}/membros", {"email": bia.email}).status_code == 201
    assert ana.post(f"/projetos/{slug}/membros", {"email": bia.email}).status_code == 201  # idempotente
    assert bia.post(f"/projetos/{slug}/membros", {"email": leo.email}).status_code == 403  # membro não convida
    assert ana.post(f"/projetos/{slug}/membros", {"email": "ninguem@x.com"}).status_code == 404
    assert leo.post(f"/projetos/{slug}/membros", {"email": leo.email}).status_code == 404
    papeis = {m["email"]: m["role"] for m in ana.get(f"/projetos/{slug}/membros").json()}
    assert papeis == {ana.email: "owner", bia.email: "member"}


def test_convite_nao_rebaixa_owner(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    ana.post(f"/projetos/{slug}/membros", {"email": ana.email})
    assert {m["email"]: m["role"] for m in ana.get(f"/projetos/{slug}/membros").json()}[ana.email] == "owner"


def test_fluxo_de_pedido_de_acesso_aceitar_recusar_e_repetir(mundo):
    ana, bia, leo = mundo.pessoa("Ana"), mundo.pessoa("Bia"), mundo.pessoa("Leo")
    slug = mundo.projeto(ana, visibility="private")
    p_bia = bia.post(f"/projetos/{slug}/pedidos")
    assert p_bia.status_code == 201 and p_bia.json()["status"] == "pending"
    assert bia.post(f"/projetos/{slug}/pedidos").status_code == 409  # já pendente
    p_leo = leo.post(f"/projetos/{slug}/pedidos").json()
    pendentes = ana.get(f"/projetos/{slug}/pedidos").json()
    assert {p["person_id"] for p in pendentes} == {bia.id, leo.id}
    assert bia.get(f"/projetos/{slug}/pedidos").status_code == 404  # quem pede ainda não é membro
    assert ana.post(f"/projetos/{slug}/pedidos/{p_bia.json()['id']}/aceitar").json()["status"] == "accepted"
    assert ana.post(f"/projetos/{slug}/pedidos/{p_bia.json()['id']}/aceitar").status_code == 404
    assert ana.post(f"/projetos/{slug}/pedidos/{p_leo['id']}/recusar").json()["status"] == "rejected"
    assert ana.post(f"/projetos/{slug}/pedidos/{p_leo['id']}/aceitar").status_code == 404
    assert bia.get(f"/projetos/{slug}/tasks").status_code == 200
    assert leo.get(f"/projetos/{slug}/tasks").status_code == 404
    assert bia.post(f"/projetos/{slug}/pedidos").status_code == 409  # já é membro
    assert leo.post(f"/projetos/{slug}/pedidos").status_code == 201  # recusado pode pedir de novo


def test_membro_comum_nao_resolve_pedidos(mundo):
    ana, bia, leo = mundo.pessoa("Ana"), mundo.pessoa("Bia"), mundo.pessoa("Leo")
    slug = mundo.projeto(ana, visibility="private")
    mundo.entrar(bia, slug, dono=ana)
    pedido = leo.post(f"/projetos/{slug}/pedidos").json()
    assert bia.get(f"/projetos/{slug}/pedidos").status_code == 403
    assert bia.post(f"/projetos/{slug}/pedidos/{pedido['id']}/aceitar").status_code == 403
    assert bia.post(f"/projetos/{slug}/pedidos/{pedido['id']}/recusar").status_code == 403


def test_pedido_de_outro_projeto_nao_e_resolvido_por_id(mundo):
    ana, bia = mundo.pessoa("Ana"), mundo.pessoa("Bia")
    um = mundo.projeto(ana, "Um", visibility="private")
    dois = mundo.projeto(ana, "Dois", visibility="private")
    pedido = bia.post(f"/projetos/{um}/pedidos").json()
    assert ana.post(f"/projetos/{dois}/pedidos/{pedido['id']}/aceitar").status_code == 404
    assert bia.get(f"/projetos/{dois}/tasks").status_code == 404


def test_pedido_em_projeto_inexistente_404(mundo):
    assert mundo.pessoa("Ana").post("/projetos/nada/pedidos").status_code == 404


@pytest.mark.parametrize("rota", ["tasks", "membros", "relatorio", "mudancas", "features"])
def test_rotas_exigem_autenticacao(mundo, rota):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    assert mundo.cliente.get(f"/projetos/{slug}/{rota}").status_code == 401
