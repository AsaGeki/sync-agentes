"""Tasks: criação e códigos, atualização, dependências, corpo versionado,
mensagens, diffs, listagem/busca e idempotência."""

import uuid

import pytest


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    return mundo, ana, bia, slug


def _t(slug, code=""):
    return f"/projetos/{slug}/tasks/{code}".rstrip("/")


# ---------- criação e codes ---------- #


def test_criar_task_defaults(cena):
    mundo, ana, _, slug = cena
    resp = ana.post(_t(slug), {"title": "Fazer login"})
    assert resp.status_code == 201
    t = resp.json()
    assert t["code"] == "T-001-fazer-login"
    assert t["status"] == "ideia"
    assert t["tags"] == [] and t["owner"] is None and t["feature"] is None
    assert t["versao_corpo"] == 0 and t["dependencies"] == []
    assert t["fazendo_agora"] is None
    assert t["cursor"] > 0


def test_numeracao_sequencial_e_nao_reaproveita_numero(cena):
    mundo, ana, _, slug = cena
    codes = [mundo.task(ana, slug, f"Item {i}") for i in range(3)]
    assert [c[:5] for c in codes] == ["T-001", "T-002", "T-003"]
    mundo.sql("DELETE FROM tasks WHERE code LIKE 'T-002%'")
    assert mundo.task(ana, slug, "Novo")[:5] == "T-004"


def test_slug_do_titulo_sem_acento_e_cortado_em_palavra_inteira(cena):
    mundo, ana, _, slug = cena
    assert mundo.task(ana, slug, "Ação de Conciliação").startswith("T-001-acao-de-conciliacao")
    longo = mundo.task(ana, slug, "palavra " * 20)
    corpo = longo.split("-", 2)[2]
    assert len(corpo) <= 40 and not corpo.endswith("-") and corpo.split("-")[-1] == "palavra"


def test_titulo_so_com_simbolos_vira_code_sem_slug(cena):
    mundo, ana, _, slug = cena
    assert mundo.task(ana, slug, "!!!") == "T-001"


def test_code_explicito_normaliza_e_conflita_se_repetido(cena):
    mundo, ana, _, slug = cena
    assert mundo.task(ana, slug, "Manual", code="T-7") == "T-007-manual"
    assert ana.post(_t(slug), {"title": "Outra", "code": "t-007"}).status_code == 409
    assert ana.post(_t(slug), {"title": "Outra", "code": "banana"}).status_code == 422
    # o automático continua acima do maior número usado
    assert mundo.task(ana, slug, "Auto")[:5] == "T-008"


def test_titulo_vazio_e_status_invalido_422(cena):
    _, ana, _, slug = cena
    assert ana.post(_t(slug), {"title": ""}).status_code == 422
    assert ana.post(_t(slug), {"title": "x", "status": "voando"}).status_code == 422
    assert ana.post(_t(slug), {}).status_code == 422


def test_criar_com_tags_dono_corpo_e_feature(cena):
    mundo, ana, bia, slug = cena
    assert ana.post(f"/projetos/{slug}/features", {"title": "Auth"}).status_code == 201
    resp = ana.post(
        _t(slug),
        {"title": "Com tudo", "tags": ["api", "ç"], "owner_id": bia.id, "corpo": "# oi", "feature": "F-1"},
    )
    assert resp.status_code == 201, resp.text
    t = resp.json()
    assert t["tags"] == ["api", "ç"] and t["owner"] is not None
    assert t["versao_corpo"] == 1 and t["feature"]["code"].startswith("F-001")


def test_criar_com_feature_ou_dependencia_inexistente_404(cena):
    _, ana, _, slug = cena
    assert ana.post(_t(slug), {"title": "x", "feature": "F-9"}).status_code == 404
    assert ana.post(_t(slug), {"title": "x", "dependencies": ["T-9"]}).status_code == 404


def test_dono_que_nao_e_membro_e_recusado(cena):
    mundo, ana, _, slug = cena
    intruso = mundo.pessoa("Intruso")
    assert ana.post(_t(slug), {"title": "x", "owner_id": intruso.id}).status_code == 422
    code = mundo.task(ana, slug)
    assert ana.patch(_t(slug, code), {"owner_id": intruso.id}).status_code == 422


def test_criar_com_dono_inexistente_nao_vira_500(cena):
    _, ana, _, slug = cena
    resp = ana.post(_t(slug), {"title": "x", "owner_id": 99999})
    assert resp.status_code in (404, 422), resp.text


def test_buscar_por_code_completo_numero_e_caixa(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug, "Achar")
    for forma in (code, "T-001", "T-1", "t-1", "T-0001"):
        assert ana.get(_t(slug, forma)).json()["code"] == code, forma
    assert ana.get(_t(slug, "T-2")).status_code == 404
    assert ana.get(_t(slug, "lixo")).status_code == 404


# ---------- atualização ---------- #


def test_update_sem_nada_422_e_valor_igual_nao_gera_evento(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    assert ana.patch(_t(slug, code), {}).status_code == 422
    resp = ana.patch(_t(slug, code), {"status": "ideia"})
    assert resp.status_code == 200 and resp.json()["cursor"] is None


def test_update_muda_campos_e_gera_um_evento_por_campo(cena):
    mundo, ana, bia, slug = cena
    code = mundo.task(ana, slug, "Velho")
    resp = ana.patch(_t(slug, code), {"title": "Novo", "status": "parcial", "tags": ["a"], "owner_id": bia.id})
    assert resp.status_code == 200, resp.text
    dados = resp.json()
    assert dados["title"] == "Novo" and dados["status"] == "parcial" and dados["tags"] == ["a"]
    assert dados["code"] == code  # título novo não troca o code
    campos = [r["campo"] for r in mundo.sql("SELECT campo FROM events WHERE kind='task.field_changed'")]
    assert sorted(campos) == ["owner_id", "status", "tags", "title"]


def test_update_status_invalido_422_e_task_inexistente_404(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    assert ana.patch(_t(slug, code), {"status": "xyz"}).status_code == 422
    assert ana.patch(_t(slug, "T-99"), {"status": "feito"}).status_code == 404


def test_update_dono_inexistente_nao_vira_500(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    resp = ana.patch(_t(slug, code), {"owner_id": 99999})
    assert resp.status_code in (404, 422), resp.text


def test_fazendo_agora_mostra_quem_e_some_ao_sair(cena):
    mundo, ana, bia, slug = cena
    code = mundo.task(ana, slug)
    dados = bia.patch(_t(slug, code), {"status": "em_andamento"}).json()
    assert dados["fazendo_agora"]["person"].startswith("bia")
    assert dados["fazendo_agora"]["agent"] == "claude"
    assert ana.patch(_t(slug, code), {"status": "parcial"}).json()["fazendo_agora"] is None


def test_task_criada_ja_em_andamento_tem_fazendo_agora(cena):
    mundo, ana, _, slug = cena
    resp = ana.post(_t(slug), {"title": "Já", "status": "em_andamento"})
    assert resp.json()["fazendo_agora"]["person"].startswith("ana")


# ---------- dependências ---------- #


def test_dependencia_pendente_trava_feito(cena):
    mundo, ana, _, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    resp = ana.patch(_t(slug, topo), {"status": "feito"})
    assert resp.status_code == 409 and base[:5] in resp.json()["detail"]
    assert ana.patch(_t(slug, base), {"status": "feito"}).status_code == 200
    assert ana.patch(_t(slug, topo), {"status": "feito"}).status_code == 200


def test_criar_ja_feito_com_dependencia_pendente_e_barrado(cena):
    mundo, ana, _, slug = cena
    base = mundo.task(ana, slug, "Base")
    resp = ana.post(_t(slug), {"title": "Topo", "status": "feito", "dependencies": [base]})
    assert resp.status_code == 409, resp.text


def test_dependencia_em_si_mesma_e_ciclo(cena):
    mundo, ana, _, slug = cena
    a = mundo.task(ana, slug, "A")
    b = mundo.task(ana, slug, "B", dependencies=[a])
    c = mundo.task(ana, slug, "C", dependencies=[b])
    assert ana.patch(_t(slug, a), {"dependencies": [a]}).status_code == 422
    assert ana.patch(_t(slug, a), {"dependencies": [c]}).status_code == 409
    assert ana.patch(_t(slug, a), {"dependencies": [b]}).status_code == 409


def test_lista_de_dependencias_substitui_e_vazia_remove(cena):
    mundo, ana, _, slug = cena
    a, b, c = (mundo.task(ana, slug, n) for n in "ABC")
    mundo.task(ana, slug, "D")
    d = ana.get(_t(slug)).json()[3]["code"]
    ana.patch(_t(slug, d), {"dependencies": [a, b]})
    assert ana.get(_t(slug, d)).json()["dependencies"] == [a, b]
    ana.patch(_t(slug, d), {"dependencies": [c]})
    assert ana.get(_t(slug, d)).json()["dependencies"] == [c]
    resp = ana.patch(_t(slug, d), {"dependencies": []})
    assert ana.get(_t(slug, d)).json()["dependencies"] == []
    assert resp.status_code == 200


def test_dependencias_pendentes_acompanham_o_status_da_dependencia(cena):
    mundo, ana, _, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    assert ana.get(_t(slug, topo)).json()["dependencias_pendentes"] == [base]
    ana.patch(_t(slug, base), {"status": "feito"})
    assert ana.get(_t(slug, topo)).json()["dependencias_pendentes"] == []


def test_fechar_no_mesmo_patch_que_troca_a_dependencia_vale_contra_a_nova(cena):
    mundo, ana, _, slug = cena
    velha = mundo.task(ana, slug, "Velha")
    topo = mundo.task(ana, slug, "Topo", dependencies=[velha])
    resp = ana.patch(_t(slug, topo), {"dependencies": [], "status": "feito"})
    assert resp.status_code == 200 and resp.json()["status"] == "feito"


def test_reabrir_dependencia_reabre_dependentes_em_cascata(cena):
    mundo, ana, _, slug = cena
    a = mundo.task(ana, slug, "A")
    b = mundo.task(ana, slug, "B", dependencies=[a])
    c = mundo.task(ana, slug, "C", dependencies=[b])
    for code in (a, b, c):
        assert ana.patch(_t(slug, code), {"status": "feito"}).status_code == 200
    ana.patch(_t(slug, a), {"status": "parcial"})
    assert ana.get(_t(slug, b)).json()["status"] == "parcial"
    assert ana.get(_t(slug, c)).json()["status"] == "parcial"


def test_reabrir_nao_mexe_em_dependente_que_nao_estava_feito(cena):
    mundo, ana, _, slug = cena
    a = mundo.task(ana, slug, "A")
    b = mundo.task(ana, slug, "B", dependencies=[a], status="bloqueado")
    ana.patch(_t(slug, a), {"status": "feito"})
    ana.patch(_t(slug, a), {"status": "ideia"})
    assert ana.get(_t(slug, b)).json()["status"] == "bloqueado"


def test_fechar_task_sem_dependencias_nunca_trava(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    assert ana.patch(_t(slug, code), {"status": "feito"}).status_code == 200


def test_falha_de_dependencia_nao_deixa_escrita_pela_metade(cena):
    mundo, ana, _, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    antes = mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"]
    resp = ana.patch(_t(slug, topo), {"title": "Mudou", "status": "feito"})
    assert resp.status_code == 409
    assert ana.get(_t(slug, topo)).json()["title"] == "Topo"
    assert mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"] == antes


# ---------- corpo versionado ---------- #


def test_corpo_versoes_diff_e_conflito(cena):
    mundo, ana, bia, slug = cena
    code = mundo.task(ana, slug)
    corpo = f"{_t(slug, code)}/corpo"
    r1 = ana.put(corpo, {"texto": "linha 1\n"}).json()
    assert r1["versao"] == 1 and "+linha 1" in r1["diff"]
    r2 = bia.put(corpo, {"texto": "linha 1\nlinha 2\n", "versao_base": 1}).json()
    assert r2["versao"] == 2 and "+linha 2" in r2["diff"]
    conflito = ana.put(corpo, {"texto": "sobrescrevo", "versao_base": 1})
    assert conflito.status_code == 409 and "v2" in conflito.json()["detail"]
    assert ana.get(_t(slug, code)).json()["corpo"] == "linha 1\nlinha 2\n"
    sem_base = ana.put(corpo, {"texto": "sem base"})
    assert sem_base.status_code == 200 and sem_base.json()["versao"] == 3


def test_corpo_com_versao_base_zero_so_vale_na_primeira_gravacao(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    corpo = f"{_t(slug, code)}/corpo"
    assert ana.put(corpo, {"texto": "a", "versao_base": 0}).status_code == 200
    assert ana.put(corpo, {"texto": "b", "versao_base": 0}).status_code == 409


def test_corpo_vazio_e_aceito_e_versiona(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    corpo = f"{_t(slug, code)}/corpo"
    ana.put(corpo, {"texto": "algo"})
    resp = ana.put(corpo, {"texto": ""})
    assert resp.status_code == 200 and resp.json()["versao"] == 2
    assert ana.get(_t(slug, code)).json()["corpo"] == ""


def test_diff_do_corpo_desde_versao(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    corpo = f"{_t(slug, code)}/corpo"
    ana.put(corpo, {"texto": "a\n"})
    ana.put(corpo, {"texto": "a\nb\n"})
    ana.put(corpo, {"texto": "a\nb\nc\n"})
    d0 = ana.get(f"{corpo}/diff", params={"desde": 0}).json()
    assert d0["versao_para"] == 3 and "+a" in d0["diff"] and "+c" in d0["diff"]
    d2 = ana.get(f"{corpo}/diff", params={"desde": 2}).json()
    assert "+c" in d2["diff"] and "+a" not in d2["diff"]
    assert ana.get(f"{corpo}/diff", params={"desde": -1}).status_code == 422


def test_diff_do_corpo_de_task_sem_corpo(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    d = ana.get(f"{_t(slug, code)}/corpo/diff").json()
    assert d["diff"] == "" and d["versao_para"] == 0


def test_corpo_nao_vaza_na_lista_mas_vem_no_read(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug, corpo="segredo do corpo")
    assert "corpo" not in ana.get(_t(slug)).json()[0]
    assert ana.get(_t(slug, code)).json()["corpo"] == "segredo do corpo"
    assert "corpo" not in ana.get(_t(slug, code), params={"com_corpo": False}).json()


# ---------- mensagens ---------- #


def test_mensagem_tipos_e_validacao(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    for tipo in ("mudanca", "pergunta", "resposta", "decisao", "bloqueio"):
        assert ana.post(f"{_t(slug, code)}/mensagens", {"type": tipo, "texto": "x"}).status_code == 201
    assert ana.post(f"{_t(slug, code)}/mensagens", {"type": "fofoca", "texto": "x"}).status_code == 422
    assert ana.post(f"{_t(slug, code)}/mensagens", {"type": "mudanca", "texto": ""}).status_code == 422
    assert ana.post(f"{_t(slug, code)}/mensagens", {"type": "mudanca"}).status_code == 422


def test_mensagem_em_task_inexistente_404(cena):
    _, ana, _, slug = cena
    assert ana.post(f"{_t(slug, 'T-9')}/mensagens", {"type": "mudanca", "texto": "x"}).status_code == 404


def test_mensagem_assina_pessoa_e_ferramenta(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    ev = mundo.mensagem(ana, slug, code, "decisao", "fechado")
    assert ev["actor"]["agent"] == "claude" and ev["actor"]["person"].startswith("ana")
    assert ev["payload"] == {"type": "decisao", "texto": "fechado"}


def test_agent_desconhecido_vira_outro_e_codex_e_reconhecido(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    for header, esperado in (("Codex CLI", "codex"), ("Cursor", "outro"), ("", "outro")):
        resp = ana.post(
            f"{_t(slug, code)}/mensagens", {"type": "mudanca", "texto": "x"}, headers={"X-Agent": header}
        )
        assert resp.json()["actor"]["agent"] == esperado


# ---------- perguntas abertas ---------- #


def _abertas(ana, slug):
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json"}).json()
    return [(p["code"], p["texto"]) for p in rel["perguntas_abertas"]]


def test_resposta_fecha_a_pergunta_mais_antiga(cena):
    mundo, ana, bia, slug = cena
    code = mundo.task(ana, slug)
    mundo.mensagem(ana, slug, code, "pergunta", "p1")
    mundo.mensagem(ana, slug, code, "pergunta", "p2")
    assert [t for _, t in _abertas(ana, slug)] == ["p1", "p2"]
    mundo.mensagem(bia, slug, code, "resposta", "r1")
    assert [t for _, t in _abertas(ana, slug)] == ["p2"]
    mundo.mensagem(bia, slug, code, "resposta", "r2")
    assert _abertas(ana, slug) == []


def test_resposta_sem_pergunta_aberta_e_ignorada(cena):
    mundo, ana, bia, slug = cena
    code = mundo.task(ana, slug)
    mundo.mensagem(bia, slug, code, "resposta", "solta")
    mundo.mensagem(ana, slug, code, "pergunta", "depois")
    assert [t for _, t in _abertas(ana, slug)] == ["depois"]


def test_perguntas_abertas_por_task_independentes(cena):
    mundo, ana, bia, slug = cena
    a, b = mundo.task(ana, slug, "A"), mundo.task(ana, slug, "B")
    mundo.mensagem(ana, slug, a, "pergunta", "pa")
    mundo.mensagem(ana, slug, b, "pergunta", "pb")
    mundo.mensagem(bia, slug, a, "resposta", "ra")
    assert [t for _, t in _abertas(ana, slug)] == ["pb"]


# ---------- diffs de código ---------- #


def _diff(ana, slug, code, commit="b" * 40, **corpo):
    payload = {"base_sha": "a" * 40, "arquivos": ["x.py"], **corpo}
    return ana.post(f"{_t(slug, code)}/diffs", payload, headers={"X-Git-Commit": commit} if commit else {})


def test_diff_exige_commit_base_diferente_e_sha_valido(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    assert _diff(ana, slug, code, commit=None).status_code == 400
    assert _diff(ana, slug, code, commit="a" * 40).status_code == 422
    assert _diff(ana, slug, code, base_sha="ZZZZZZZ").status_code == 422
    assert _diff(ana, slug, code, base_sha="abc").status_code == 422
    assert _diff(ana, slug, code).status_code == 201


def test_diff_trunca_patch_gigante_e_marca(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    resp = _diff(ana, slug, code, patch="x" * 150_000)
    assert resp.status_code == 201 and resp.json()["truncado"] is True
    ev = ana.get(_t(slug, code)).json()["eventos"][-1]
    assert ev["payload"]["patch"].endswith("... patch truncado ...\n")
    assert len(ev["payload"]["patch"]) < 101_000


def test_diff_listagem_sem_patch_e_leitura_com_patch(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    _diff(ana, slug, code, patch="--- a\n+++ b\n")
    lista = ana.get(f"{_t(slug, code)}/diffs").json()
    assert len(lista) == 1 and "patch" not in lista[0]["payload"]
    assert lista[0]["payload"]["head_sha"] == "b" * 40
    evs = [e for e in ana.get(_t(slug, code)).json()["eventos"] if e["kind"] == "diff.published"]
    assert evs[0]["payload"]["patch"] == "--- a\n+++ b\n"


def test_pedir_revisao_cria_pergunta_aberta(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug)
    resp = _diff(ana, slug, code, pedir_revisao=True, resumo="mexi no login")
    assert resp.status_code == 201
    (_, texto), = _abertas(ana, slug)
    assert "mexi no login" in texto
    sem = mundo.task(ana, slug, "Outra")
    _diff(ana, slug, sem)
    assert len(_abertas(ana, slug)) == 1


# ---------- listagem e busca ---------- #


def test_filtros_de_status_tag_e_feature(cena):
    mundo, ana, _, slug = cena
    ana.post(f"/projetos/{slug}/features", {"title": "F"})
    a = mundo.task(ana, slug, "A", tags=["api"], status="feito")
    b = mundo.task(ana, slug, "B", tags=["apis"], feature="F-1")
    c = mundo.task(ana, slug, "C", tags=["api", "ui"], feature="F-1")
    codes = lambda params: [t["code"] for t in ana.get(_t(slug), params=params).json()]  # noqa: E731
    assert codes({"status": "feito"}) == [a]
    assert codes({"tag": "api"}) == [a, c]  # tag é exata, não substring
    assert codes({"feature": "F-1"}) == [b, c]
    assert codes({"sem_feature": True}) == [a]
    assert ana.get(_t(slug), params={"feature": "F-1", "sem_feature": True}).status_code == 422
    assert ana.get(_t(slug), params={"feature": "F-9"}).status_code == 404
    assert ana.get(_t(slug), params={"status": "xyz"}).status_code == 422
    assert codes({"status": "feito", "tag": "ui"}) == []


def test_busca_por_code_titulo_e_corpo_sem_caixa(cena):
    mundo, ana, _, slug = cena
    a = mundo.task(ana, slug, "Relatório mensal")
    b = mundo.task(ana, slug, "Outra", corpo="detalhe sobre CONCILIAÇÃO")
    codes = lambda q: [t["code"] for t in ana.get(_t(slug), params={"q": q}).json()]  # noqa: E731
    assert codes("mensal") == [a]
    assert codes("conciliação") == [b]
    assert codes("T-002") == [b]
    assert codes("nada") == []


def test_busca_so_olha_o_corpo_atual_nao_versoes_antigas(cena):
    mundo, ana, _, slug = cena
    code = mundo.task(ana, slug, corpo="texto antigo zebra")
    ana.put(f"{_t(slug, code)}/corpo", {"texto": "texto novo"})
    assert ana.get(_t(slug), params={"q": "zebra"}).json() == []
    assert len(ana.get(_t(slug), params={"q": "novo"}).json()) == 1


def test_busca_com_curinga_like_e_literal(cena):
    mundo, ana, _, slug = cena
    mundo.task(ana, slug, "Taxa de 100% sucesso")
    mundo.task(ana, slug, "Outra coisa")
    mundo.task(ana, slug, "snake_case aqui")
    codes = lambda q: [t["title"] for t in ana.get(_t(slug), params={"q": q}).json()]  # noqa: E731
    assert codes("%") == ["Taxa de 100% sucesso"]
    assert codes("_") == ["snake_case aqui"]


def test_lista_vem_ordenada_por_code_numerico_ate_999(cena):
    mundo, ana, _, slug = cena
    for i in range(12):
        mundo.task(ana, slug, f"t{i}")
    codes = [t["code"][:5] for t in ana.get(_t(slug)).json()]
    assert codes == sorted(codes)


# ---------- idempotência ---------- #


def test_mesmo_operation_id_nao_duplica_a_escrita(cena):
    mundo, ana, _, slug = cena
    op = str(uuid.uuid4())
    r1 = ana.post(_t(slug), {"title": "Uma vez"}, headers={"X-Operation-Id": op})
    r2 = ana.post(_t(slug), {"title": "Uma vez"}, headers={"X-Operation-Id": op})
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert len(ana.get(_t(slug)).json()) == 1


def test_erro_nao_fica_gravado_e_retentativa_executa(cena):
    mundo, ana, _, slug = cena
    op = str(uuid.uuid4())
    assert ana.patch(_t(slug, "T-1"), {"status": "feito"}, headers={"X-Operation-Id": op}).status_code == 404
    code = mundo.task(ana, slug)
    assert ana.patch(_t(slug, code), {"status": "feito"}, headers={"X-Operation-Id": op}).status_code == 200


def test_operation_id_de_uma_pessoa_nao_responde_pela_outra(cena):
    mundo, ana, bia, slug = cena
    op = str(uuid.uuid4())
    ana.post(_t(slug), {"title": "da Ana"}, headers={"X-Operation-Id": op})
    resp = bia.post(_t(slug), {"title": "da Bia"}, headers={"X-Operation-Id": op})
    titulos = [t["title"] for t in ana.get(_t(slug)).json()]
    assert "da Bia" in titulos, (resp.status_code, resp.text, titulos)


def test_get_com_operation_id_nao_e_cacheado(cena):
    mundo, ana, _, slug = cena
    op = str(uuid.uuid4())
    assert ana.get(_t(slug), headers={"X-Operation-Id": op}).json() == []
    mundo.task(ana, slug)
    assert len(ana.get(_t(slug), headers={"X-Operation-Id": op}).json()) == 1
