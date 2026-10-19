"""Status `cancelada`: não trava dependentes, sai do progresso, migração do banco
antigo e telas."""

import sqlite3

import pytest

from src.shared import db

from .test_web import _logar


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    return mundo, ana, slug


def _t(slug, code=""):
    return f"/projetos/{slug}/tasks/{code}".rstrip("/")


def _status(ana, slug, code):
    return ana.get(_t(slug, code)).json()["status"]


# ---------- status ---------- #


def test_criar_e_mudar_para_cancelada(cena):
    mundo, ana, slug = cena
    direto = ana.post(_t(slug), {"title": "Nasce cancelada", "status": "cancelada"})
    assert direto.status_code == 201 and direto.json()["status"] == "cancelada"
    code = mundo.task(ana, slug, "Vira cancelada")
    assert ana.patch(_t(slug, code), {"status": "cancelada"}).json()["status"] == "cancelada"
    assert ana.patch(_t(slug, code), {"status": "cancelada2"}).status_code == 422


def test_filtro_por_status_cancelada(cena):
    mundo, ana, slug = cena
    a = mundo.task(ana, slug, "A", status="cancelada")
    mundo.task(ana, slug, "B")
    assert [t["code"] for t in ana.get(_t(slug), params={"status": "cancelada"}).json()] == [a]


def test_cancelar_task_em_andamento_tira_o_fazendo_agora(cena):
    mundo, ana, slug = cena
    code = mundo.task(ana, slug, status="em_andamento")
    assert ana.get(_t(slug, code)).json()["fazendo_agora"] is not None
    assert ana.patch(_t(slug, code), {"status": "cancelada"}).json()["fazendo_agora"] is None


# ---------- dependências ---------- #


def test_dependencia_cancelada_nao_trava_o_feito(cena):
    mundo, ana, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    assert ana.patch(_t(slug, topo), {"status": "feito"}).status_code == 409
    ana.patch(_t(slug, base), {"status": "cancelada"})
    assert ana.get(_t(slug, topo)).json()["dependencias_pendentes"] == []
    assert ana.patch(_t(slug, topo), {"status": "feito"}).status_code == 200


def test_criar_feito_com_dependencia_cancelada_passa(cena):
    mundo, ana, slug = cena
    base = mundo.task(ana, slug, "Base", status="cancelada")
    assert ana.post(_t(slug), {"title": "Topo", "status": "feito", "dependencies": [base]}).status_code == 201


def test_mensagem_de_erro_cita_feito_e_cancelada(cena):
    mundo, ana, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    assert "cancelada" in ana.patch(_t(slug, topo), {"status": "feito"}).json()["detail"]


def test_cancelar_nao_reabre_dependente_ja_feito(cena):
    mundo, ana, slug = cena
    base = mundo.task(ana, slug, "Base")
    topo = mundo.task(ana, slug, "Topo", dependencies=[base])
    ana.patch(_t(slug, base), {"status": "feito"})
    ana.patch(_t(slug, topo), {"status": "feito"})
    ana.patch(_t(slug, base), {"status": "cancelada"})
    assert _status(ana, slug, topo) == "feito"


def test_reabrir_cancelada_reabre_dependentes_feitos_em_cascata(cena):
    mundo, ana, slug = cena
    a = mundo.task(ana, slug, "A")
    b = mundo.task(ana, slug, "B", dependencies=[a])
    c = mundo.task(ana, slug, "C", dependencies=[b])
    ana.patch(_t(slug, a), {"status": "cancelada"})
    for code in (b, c):
        assert ana.patch(_t(slug, code), {"status": "feito"}).status_code == 200
    ana.patch(_t(slug, a), {"status": "ideia"})
    assert _status(ana, slug, b) == "parcial" and _status(ana, slug, c) == "parcial"


def test_cancelada_para_feito_nao_mexe_nos_dependentes(cena):
    mundo, ana, slug = cena
    a = mundo.task(ana, slug, "A", status="cancelada")
    b = mundo.task(ana, slug, "B", dependencies=[a], status="feito")
    ana.patch(_t(slug, a), {"status": "feito"})
    assert _status(ana, slug, b) == "feito"


def test_feito_para_cancelada_e_o_inverso_nao_reabrem_ninguem_a_toa(cena):
    mundo, ana, slug = cena
    a = mundo.task(ana, slug, "A")
    b = mundo.task(ana, slug, "B", dependencies=[a])
    ana.patch(_t(slug, a), {"status": "feito"})
    ana.patch(_t(slug, b), {"status": "feito"})
    ana.patch(_t(slug, a), {"status": "cancelada"})
    ana.patch(_t(slug, a), {"status": "feito"})
    assert _status(ana, slug, b) == "feito"


# ---------- features ---------- #


def _feature_com(mundo, ana, slug, statuses):
    ana.post(f"/projetos/{slug}/features", {"title": "F"})
    for i, st in enumerate(statuses):
        mundo.task(ana, slug, f"t{i}", status=st, feature="F-1")
    return ana.get(f"/projetos/{slug}/features/F-1").json()


def test_progresso_da_feature_nao_conta_cancelada_no_total(cena):
    mundo, ana, slug = cena
    f = _feature_com(mundo, ana, slug, ["feito", "cancelada", "ideia"])
    assert f["progresso"] == {"feito": 1, "total": 2}
    assert f["contagem_status"] == {"feito": 1, "cancelada": 1, "ideia": 1}


@pytest.mark.parametrize(
    ("statuses", "esperado"),
    [
        (["feito", "cancelada"], "feito"),
        (["cancelada", "ideia"], "ideia"),
        (["cancelada", "bloqueado"], "bloqueado"),
        (["cancelada", "em_andamento"], "em_andamento"),
        (["cancelada", "feito", "ideia"], "parcial"),
        (["cancelada", "cancelada"], "ideia"),
    ],
)
def test_status_derivado_ignora_canceladas(cena, statuses, esperado):
    mundo, ana, slug = cena
    assert _feature_com(mundo, ana, slug, statuses)["status"] == esperado


def test_feature_so_com_canceladas_tem_progresso_zero_de_zero(cena):
    mundo, ana, slug = cena
    f = _feature_com(mundo, ana, slug, ["cancelada"])
    assert f["progresso"] == {"feito": 0, "total": 0}


# ---------- relatório ---------- #


def test_relatorio_mostra_cancelada(cena):
    mundo, ana, slug = cena
    code = mundo.task(ana, slug, "Cancelada", status="cancelada")
    rel = ana.get(f"/projetos/{slug}/relatorio", params={"formato": "json"}).json()
    assert rel["contagem_status"] == {"cancelada": 1}
    ana.put(f"{_t(slug, code)}/corpo", {"texto": "x\n"})
    md = ana.get(f"/projetos/{slug}/relatorio").text
    assert "1 cancelada" in md and "[cancelada]" in md


# ---------- tela ---------- #


def test_web_progresso_sem_canceladas_e_coluna_no_quadro(cena):
    mundo, ana, slug = cena
    mundo.task(ana, slug, "Feita", status="feito")
    mundo.task(ana, slug, "Aberta")
    mundo.task(ana, slug, "Cancelada", status="cancelada")
    web = _logar(ana.token)
    painel = web.get(f"/web/p/{slug}").text
    assert "1<small> / 2</small>" in painel
    assert "3 tasks no projeto, 1 cancelada(s) fora do progresso" in painel
    assert "st-cancelada" in painel
    inicio = web.get("/web").text
    assert "1/2 tasks feitas" in inicio
    quadro = web.get(f"/web/p/{slug}/tasks?visao=quadro").text
    assert quadro.count("coluna-quadro") >= 7 and "cancelada" in quadro
    assert web.get(f"/web/p/{slug}/tasks", params={"status": "cancelada"}).status_code == 200
    assert web.get(f"/web/p/{slug}/tasks", params={"agrupar": "status"}).status_code == 200


def test_web_pagina_da_feature_separa_as_canceladas(cena):
    mundo, ana, slug = cena
    ana.post(f"/projetos/{slug}/features", {"title": "F"})
    mundo.task(ana, slug, "Aberta", feature="F-1")
    mundo.task(ana, slug, "Cancelada", feature="F-1", status="cancelada")
    html = _logar(ana.token).get(f"/web/p/{slug}/f/F-1").text
    assert "Canceladas" in html
    assert 'Tasks abertas <span class="mudo">1</span>' in html


def test_web_feature_sem_canceladas_nao_mostra_o_bloco(cena):
    mundo, ana, slug = cena
    ana.post(f"/projetos/{slug}/features", {"title": "F"})
    mundo.task(ana, slug, "Aberta", feature="F-1")
    assert "Canceladas" not in _logar(ana.token).get(f"/web/p/{slug}/f/F-1").text


def test_web_task_oferece_cancelada_e_aceita_pela_tela(cena):
    mundo, ana, slug = cena
    code = mundo.task(ana, slug)
    web = _logar(ana.token)
    assert 'value="cancelada"' in web.get(f"/web/p/{slug}/t/{code}").text
    r = web.post(
        f"/web/p/{slug}/t/{code}/campos",
        data={"status": "cancelada", "owner_id": "", "feature": "", "tags": ""},
    )
    assert r.status_code == 200 and _status(ana, slug, code) == "cancelada"


def test_web_lista_com_task_cancelada_e_barra_de_progresso_zerada(cena):
    mundo, ana, slug = cena
    mundo.task(ana, slug, "Cancelada", status="cancelada")
    html = _logar(ana.token).get(f"/web/p/{slug}/tasks").text
    assert "st-cancelada" in html and "0%" in html


# ---------- migração do banco antigo ---------- #

CHECK_ANTIGO = "'ideia','em_andamento','parcial','feito','bloqueado','aguardando_decisao'"


def _rebaixar_tasks_para_check_antigo(mundo):
    """Deixa `tasks` como era antes da cancelada: mesmo conteúdo, CHECK antigo."""
    conn = sqlite3.connect(db.DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        sequencia = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'tasks'").fetchone()
        with conn:
            conn.execute(
                f"""CREATE TABLE tasks_velho (
                      id         INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                      code       TEXT NOT NULL,
                      title      TEXT NOT NULL,
                      status     TEXT NOT NULL CHECK (status IN ({CHECK_ANTIGO})),
                      tags       TEXT NOT NULL DEFAULT '[]',
                      owner_id   INTEGER REFERENCES people(id),
                      feature_id INTEGER REFERENCES features(id) ON DELETE SET NULL,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      UNIQUE (project_id, code)
                    )"""
            )
            conn.execute("INSERT INTO tasks_velho SELECT * FROM tasks")
            conn.execute("DROP TABLE tasks")
            conn.execute("ALTER TABLE tasks_velho RENAME TO tasks")
            if sequencia is not None:
                conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'tasks'", (sequencia[0],))
    finally:
        conn.close()


def test_migracao_recria_tasks_com_o_novo_check_sem_perder_nada(cena):
    mundo, ana, slug = cena
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug)
    ana.post(f"/projetos/{slug}/features", {"title": "F"})
    a = mundo.task(ana, slug, "A", feature="F-1", tags=["x"], owner_id=bia.id)
    b = mundo.task(ana, slug, "B", dependencies=[a], corpo="corpo b")
    mundo.mensagem(bia, slug, b, "pergunta", "ainda vale?")
    bia.get(_t(slug, b))
    antes_tasks = [dict(r) for r in mundo.sql("SELECT * FROM tasks ORDER BY id")]
    antes_eventos = mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"]
    antes_leituras = mundo.sql("SELECT COUNT(*) AS n FROM task_reads")[0]["n"]

    _rebaixar_tasks_para_check_antigo(mundo)
    with pytest.raises(sqlite3.IntegrityError):
        mundo.sql(
            "INSERT INTO tasks (project_id, code, title, status, created_at, updated_at)"
            " VALUES (1, 'T-099', 'x', 'cancelada', 'a', 'a')"
        )

    db.iniciar_banco()

    assert [dict(r) for r in mundo.sql("SELECT * FROM tasks ORDER BY id")] == antes_tasks
    assert mundo.sql("SELECT COUNT(*) AS n FROM events")[0]["n"] == antes_eventos
    assert mundo.sql("SELECT COUNT(*) AS n FROM task_reads")[0]["n"] == antes_leituras
    assert mundo.sql("SELECT COUNT(*) AS n FROM task_dependencies")[0]["n"] == 1
    assert ana.get(_t(slug, a)).json()["dependencies"] == []
    assert ana.get(_t(slug, b)).json()["dependencies"] == [a]
    assert ana.patch(_t(slug, a), {"status": "cancelada"}).status_code == 200


def test_migracao_e_idempotente_e_nao_reaproveita_id_apagado(cena):
    mundo, ana, slug = cena
    mundo.task(ana, slug, "A")
    mundo.task(ana, slug, "B")
    mundo.sql("DELETE FROM tasks WHERE code LIKE 'T-002%'")
    _rebaixar_tasks_para_check_antigo(mundo)
    db.iniciar_banco()
    sql1 = mundo.sql("SELECT sql FROM sqlite_master WHERE name = 'tasks'")[0]["sql"]
    db.iniciar_banco()
    assert mundo.sql("SELECT sql FROM sqlite_master WHERE name = 'tasks'")[0]["sql"] == sql1
    assert "'cancelada'" in sql1
    mundo.task(ana, slug, "C")
    assert mundo.sql("SELECT MAX(id) AS m FROM tasks")[0]["m"] == 3  # o id apagado não volta


def test_migracao_recria_os_indices_de_tasks(cena):
    mundo, ana, slug = cena
    mundo.task(ana, slug, "A")
    _rebaixar_tasks_para_check_antigo(mundo)
    db.iniciar_banco()
    consulta = "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'tasks'"
    indices = {r["name"] for r in mundo.sql(consulta)}
    assert {"idx_tasks_numero", "idx_tasks_feature"} <= indices
    assert mundo.task(ana, slug, "B")  # a numeração única continua valendo


# ---------- cliente ---------- #


def test_enum_do_cliente_tem_cancelada():
    from sync_agents_mcp.enums import EStatusTask

    assert EStatusTask.cancelada.value == "cancelada"
    assert "cancelada" in [s.value for s in EStatusTask]
