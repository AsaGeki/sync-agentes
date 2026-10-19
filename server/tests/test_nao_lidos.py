"""Mecanismo de lido/não lido: marca d'água por (task, pessoa), aviso do bridge
(`/nao-lidos`), filtro `nao_lidas` e a regra de entrada tardia."""

from src.modules.tasks import repositorio as tasks_repositorio
from src.shared import db

from .conftest import PASSADO


def _montar(mundo, quantas_tasks=0):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    codes = [mundo.task(ana, slug, f"Tarefa {i}") for i in range(quantas_tasks)]
    return ana, bia, slug, codes


# ---------- o básico ---------- #


def test_eco_proprio_nao_conta_como_nao_lido(mundo):
    ana, _, slug, _ = _montar(mundo, 1)
    assert mundo.nao_lidos(ana, slug) == {"total": 0, "tasks": []}


def test_evento_de_outra_pessoa_aparece_e_formato_do_aviso(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 1
    (item,) = aviso["tasks"]
    assert item["code"] == code
    assert item["nao_lidos"] == 1
    assert item["status"] == "ideia"
    assert "task criada" in item["ultimo"]
    assert "pergunta" not in item


def test_nao_lidos_conta_cada_evento_e_ultimo_e_o_mais_recente(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(ana, slug, code, "mudanca", "primeira")
    mundo.mensagem(ana, slug, code, "decisao", "segunda")
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert item["nao_lidos"] == 3
    assert "decisao: segunda" in item["ultimo"]


def test_chamar_nao_lidos_nao_marca_nada(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    for _ in range(3):
        assert mundo.nao_lidos(bia, slug)["total"] == 1


def test_read_task_marca_lido_e_so_volta_com_evento_novo(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    leitura = bia.get(f"/projetos/{slug}/tasks/{code}").json()
    assert leitura["nao_lidos"] == 1  # a resposta mostra o que havia antes de abrir
    assert mundo.nao_lidos(bia, slug) == {"total": 0, "tasks": []}
    mundo.mensagem(ana, slug, code)
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert item["nao_lidos"] == 1


def test_read_task_sem_corpo_tambem_marca_lido(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    bia.get(f"/projetos/{slug}/tasks/{code}", params={"com_corpo": False})
    assert mundo.nao_lidos(bia, slug)["total"] == 0


def test_leitura_e_por_pessoa(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    leo = mundo.pessoa("Leo")
    mundo.entrar(leo, slug)
    bia.get(f"/projetos/{slug}/tasks/{code}")
    assert mundo.nao_lidos(bia, slug)["total"] == 0
    assert mundo.nao_lidos(leo, slug)["total"] == 1


def test_escrever_na_task_nao_marca_lido_do_que_o_outro_escreveu(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(bia, slug, code, "resposta", "vi de cabeça")
    assert mundo.nao_lidos(bia, slug)["total"] == 1


def test_evento_do_proprio_autor_nunca_entra_mesmo_com_outros_no_meio(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    bia.get(f"/projetos/{slug}/tasks/{code}")
    mundo.mensagem(bia, slug, code)
    mundo.mensagem(ana, slug, code)
    mundo.mensagem(bia, slug, code)
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert item["nao_lidos"] == 1


def test_marca_so_anda_pra_frente(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(ana, slug, code)
    bia.get(f"/projetos/{slug}/tasks/{code}")
    (task_id,) = [r["id"] for r in mundo.sql("SELECT id FROM tasks")]
    antes = mundo.sql("SELECT last_read_seq FROM task_reads")[0]["last_read_seq"]
    conn = db.conectar()
    try:
        with conn:
            tasks_repositorio.marcar_lida(conn, task_id, bia.id, 1)
    finally:
        conn.close()
    assert mundo.sql("SELECT last_read_seq FROM task_reads")[0]["last_read_seq"] == antes


def test_projetos_independentes_nao_se_misturam(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    outro = mundo.projeto(ana, "Outro")
    mundo.entrar(bia, outro)
    mundo.task(ana, outro, "Do outro")
    assert mundo.nao_lidos(bia, slug)["total"] == 1
    assert mundo.nao_lidos(bia, outro)["total"] == 1
    bia.get(f"/projetos/{slug}/tasks/{code}")
    assert mundo.nao_lidos(bia, slug)["total"] == 0
    assert mundo.nao_lidos(bia, outro)["total"] == 1


def test_eventos_de_feature_nao_entram_na_lista_de_tasks(mundo):
    ana, bia, slug, _ = _montar(mundo, 0)
    assert ana.post(f"/projetos/{slug}/features", {"title": "Feat"}).status_code == 201
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 0 and aviso["tasks"] == []
    assert aviso["features"]["nao_lidos"] == 1  # aparecem à parte (ver test_features_lidas)


# ---------- corrida na marca de lido ---------- #


def test_evento_que_chega_durante_a_leitura_continua_nao_lido(mundo, monkeypatch):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    from src.modules.tasks import service

    original = service.eventos_service.eventos_da_task

    def eventos_e_depois_chega_um(conn, task_id):
        carregados = original(conn, task_id)
        mundo.sql(
            "INSERT INTO events (project_id, task_id, author_id, agent, kind, type, texto, created_at)"
            " SELECT project_id, id, ?, 'claude', 'message.created', 'mudanca', 'chegou no meio', ?"
            " FROM tasks WHERE id = ?",
            (ana.id, PASSADO.replace("2000", "2999"), task_id),
        )
        return carregados

    with monkeypatch.context() as m:
        m.setattr(service.eventos_service, "eventos_da_task", eventos_e_depois_chega_um)
        bia.get(f"/projetos/{slug}/tasks/{code}")
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert item["nao_lidos"] == 1
    assert "chegou no meio" in item["ultimo"]


def test_task_sem_eventos_carregados_nao_quebra_a_marca(mundo, monkeypatch):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    from src.modules.tasks import service

    with monkeypatch.context() as m:
        m.setattr(service.eventos_service, "eventos_da_task", lambda conn, task_id: [])
        assert bia.get(f"/projetos/{slug}/tasks/{code}").status_code == 200
    assert mundo.sql("SELECT COUNT(*) AS n FROM task_reads")[0]["n"] == 0
    assert mundo.nao_lidos(bia, slug)["total"] == 1


# ---------- entrada tardia ---------- #


def test_quem_entra_depois_nao_tem_o_historico_como_nao_lido(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    codes = [mundo.task(ana, slug, f"T {i}") for i in range(3)]
    mundo.mensagem(ana, slug, codes[0], "pergunta", "antiga?")
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")

    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, em="2026-01-02T10:00:00+00:00")

    assert mundo.nao_lidos(bia, slug) == {"total": 0, "tasks": []}
    lista = bia.get(f"/projetos/{slug}/tasks", params={"nao_lidas": True}).json()
    assert lista == []
    todas = bia.get(f"/projetos/{slug}/tasks").json()
    assert [t["nao_lidos"] for t in todas] == [0, 0, 0]


def test_evento_depois_da_entrada_conta(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    code = mundo.task(ana, slug)
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, em="2026-01-02T10:00:00+00:00")
    mundo.mensagem(ana, slug, code)
    mundo.sql(
        "UPDATE events SET created_at = '2026-01-03T10:00:00+00:00' WHERE kind = 'message.created'"
    )
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert item["nao_lidos"] == 1


def test_corte_de_entrada_respeita_fuso(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    code = mundo.task(ana, slug)
    mundo.datar_eventos("2026-01-01T12:30:00+00:00")  # antes da entrada (13:00Z)
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, em="2026-01-01T10:00:00-03:00")  # = 13:00Z
    assert mundo.nao_lidos(bia, slug)["total"] == 0
    mundo.mensagem(ana, slug, code)
    mundo.sql(
        "UPDATE events SET created_at = '2026-01-01T13:30:00+00:00' WHERE kind = 'message.created'"
    )
    assert mundo.nao_lidos(bia, slug)["tasks"][0]["nao_lidos"] == 1


def test_entrada_em_projeto_privado_por_convite_tambem_corta(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana, visibility="private")
    mundo.task(ana, slug)
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, dono=ana, em="2026-02-01T10:00:00+00:00")
    assert mundo.nao_lidos(bia, slug)["total"] == 0


def test_entrada_real_sem_recuar_o_relogio_corta_o_historico(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    mundo.task(ana, slug)
    mundo.datar_eventos("2000-01-01T00:00:00+00:00")
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, em=None)  # created_at = agora, de verdade
    assert mundo.nao_lidos(bia, slug)["total"] == 0


def test_vincular_de_novo_nao_reseta_a_data_de_entrada(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    mundo.task(ana, slug)
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug)  # entrada em 2000
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")
    bia.post(f"/projetos/{slug}/repos", {"root_sha": mundo.shas[slug], "name": "repo"})
    assert mundo.nao_lidos(bia, slug)["total"] == 1


def test_resolve_repo_em_projeto_team_entra_como_membro_novo_sem_historico(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    mundo.task(ana, slug)
    mundo.datar_eventos("2000-01-01T00:00:00+00:00")
    bia = mundo.pessoa("Bia")
    resp = bia.post("/repos/resolve", {"root_sha": mundo.shas[slug], "name": "repo"})
    assert resp.status_code == 200 and resp.json()[0]["role"] == "member"
    assert mundo.nao_lidos(bia, slug)["total"] == 0


def test_aprovar_pedido_de_acesso_entra_sem_historico(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana, visibility="private")
    mundo.task(ana, slug)
    mundo.datar_eventos("2000-01-01T00:00:00+00:00")
    bia = mundo.pessoa("Bia")
    pedido = bia.post(f"/projetos/{slug}/pedidos").json()
    assert ana.post(f"/projetos/{slug}/pedidos/{pedido['id']}/aceitar").status_code == 200
    assert mundo.nao_lidos(bia, slug)["total"] == 0


# ---------- corte de 20 e total ---------- #


def test_corte_em_20_informa_o_total(mundo):
    ana, bia, slug, codes = _montar(mundo, 25)
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 25
    assert len(aviso["tasks"]) == 20
    todas = bia.get(f"/projetos/{slug}/tasks", params={"nao_lidas": True}).json()
    assert len(todas) == 25


def test_exatamente_20_nao_tem_omitidos(mundo):
    ana, bia, slug, _ = _montar(mundo, 20)
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 20 and len(aviso["tasks"]) == 20


def test_ordem_do_aviso_e_da_mais_recente_pra_mais_antiga(mundo):
    ana, bia, slug, codes = _montar(mundo, 3)
    mundo.mensagem(ana, slug, codes[0])  # a T-001 ganha o evento mais novo
    ordem = [t["code"] for t in mundo.nao_lidos(bia, slug)["tasks"]]
    assert ordem == [codes[0], codes[2], codes[1]]


def test_corte_mantem_as_mais_recentes(mundo):
    ana, bia, slug, codes = _montar(mundo, 22)
    presentes = {t["code"] for t in mundo.nao_lidos(bia, slug)["tasks"]}
    assert codes[0] not in presentes and codes[1] not in presentes
    assert codes[-1] in presentes


# ---------- pergunta em destaque ---------- #


def test_task_com_pergunta_nao_lida_vem_primeiro(mundo):
    ana, bia, slug, codes = _montar(mundo, 3)
    mundo.mensagem(ana, slug, codes[0], "pergunta", "posso apagar?")
    mundo.mensagem(ana, slug, codes[1], "mudanca", "mexi")
    mundo.mensagem(ana, slug, codes[2], "mudanca", "mexi também")
    ordem = [t["code"] for t in mundo.nao_lidos(bia, slug)["tasks"]]
    assert ordem[0] == codes[0]
    assert ordem[1:] == [codes[2], codes[1]]


def test_pergunta_fura_o_corte_de_20(mundo):
    ana, bia, slug, codes = _montar(mundo, 22)
    mundo.mensagem(ana, slug, codes[0], "pergunta", "urgente")
    # codes[0] seria a mais antiga; com pergunta tem que estar dentro dos 20
    assert mundo.nao_lidos(bia, slug)["tasks"][0]["code"] == codes[0]


def test_pergunta_que_nao_e_o_ultimo_evento_vem_em_campo_proprio(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(ana, slug, code, "pergunta", "a cor é azul?")
    mundo.mensagem(ana, slug, code, "mudanca", "troquei o header")
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "mudanca: troquei o header" in item["ultimo"]
    assert "pergunta: a cor é azul?" in item["pergunta"]


def test_pergunta_como_ultimo_evento_nao_duplica(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(ana, slug, code, "mudanca", "antes")
    mundo.mensagem(ana, slug, code, "pergunta", "e agora?")
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "pergunta: e agora?" in item["ultimo"]
    assert "pergunta" not in item


def test_varias_perguntas_destaca_a_mais_recente(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    mundo.mensagem(ana, slug, code, "pergunta", "primeira?")
    mundo.mensagem(ana, slug, code, "pergunta", "segunda?")
    mundo.mensagem(ana, slug, code, "decisao", "decidi")
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "segunda?" in item["pergunta"]


def test_pergunta_do_proprio_autor_nao_destaca(mundo):
    ana, bia, slug, codes = _montar(mundo, 2)
    mundo.mensagem(bia, slug, codes[0], "pergunta", "minha pergunta")
    mundo.mensagem(ana, slug, codes[1], "mudanca", "mexi")
    ordem = [t["code"] for t in mundo.nao_lidos(bia, slug)["tasks"]]
    assert ordem == [codes[1], codes[0]] or ordem == [codes[1]]
    assert all("pergunta" not in t for t in mundo.nao_lidos(bia, slug)["tasks"])


def test_pergunta_lida_deixa_de_destacar(mundo):
    ana, bia, slug, codes = _montar(mundo, 2)
    mundo.mensagem(ana, slug, codes[0], "pergunta", "lida logo")
    mundo.mensagem(ana, slug, codes[1], "mudanca", "mexi")
    bia.get(f"/projetos/{slug}/tasks/{codes[0]}")
    ordem = [t["code"] for t in mundo.nao_lidos(bia, slug)["tasks"]]
    assert ordem == [codes[1]]


def test_pedir_revisao_de_diff_conta_como_pergunta_nao_lida(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    resp = ana.post(
        f"/projetos/{slug}/tasks/{code}/diffs",
        {"base_sha": "a" * 40, "arquivos": ["a.py"], "pedir_revisao": True},
        headers={"X-Git-Commit": "b" * 40},
    )
    assert resp.status_code == 201, resp.text
    (item,) = mundo.nao_lidos(bia, slug)["tasks"]
    assert "pergunta: Revisão pedida" in item["ultimo"]
    assert item["nao_lidos"] == 3


# ---------- acesso ---------- #


def test_nao_lidos_exige_token(mundo):
    ana, bia, slug, _ = _montar(mundo, 0)
    assert mundo.cliente.get(f"/projetos/{slug}/nao-lidos").status_code == 401
    assert mundo.cliente.get(f"/projetos/{slug}/nao-lidos", headers={"Authorization": "Bearer x"}).status_code == 401


def test_nao_membro_recebe_404_e_nao_descobre_o_projeto(mundo):
    ana, bia, slug, _ = _montar(mundo, 1)
    intruso = mundo.pessoa("Intruso")
    assert intruso.get(f"/projetos/{slug}/nao-lidos").status_code == 404
    assert intruso.get(f"/projetos/{slug}/tasks", params={"nao_lidas": True}).status_code == 404


def test_projeto_inexistente_404(mundo):
    ana = mundo.pessoa("Ana")
    assert ana.get("/projetos/nao-existe/nao-lidos").status_code == 404


def test_task_removida_do_banco_nao_deixa_lixo(mundo):
    ana, bia, slug, (code,) = _montar(mundo, 1)
    bia.get(f"/projetos/{slug}/tasks/{code}")
    conn = db.conectar()
    try:
        with conn:
            conn.execute("DELETE FROM tasks")
    finally:
        conn.close()
    assert mundo.sql("SELECT COUNT(*) AS n FROM task_reads")[0]["n"] == 0
    assert mundo.nao_lidos(bia, slug) == {"total": 0, "tasks": []}
