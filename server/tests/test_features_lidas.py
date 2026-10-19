"""Marca de leitura dos eventos de feature: o aviso do `/nao-lidos`, quem marca
(`list_features`), entrada tardia e os contadores da web."""

import pytest

from src.modules.features import repositorio as features_repositorio
from src.modules.features import service as features_service
from src.shared import db

from .conftest import ADMIN
from .test_web import _logar


@pytest.fixture
def cena(mundo):
    ana = mundo.pessoa("Ana")
    bia = mundo.pessoa("Bia")
    slug = mundo.projeto(ana)
    mundo.entrar(bia, slug)
    return mundo, ana, bia, slug


def _feat(slug):
    return f"/projetos/{slug}/features"


def _sem_features(aviso):
    return "features" not in aviso


def test_feature_criada_por_outra_pessoa_aparece_no_aviso(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "Login social"})
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 0 and aviso["tasks"] == []
    assert aviso["features"]["nao_lidos"] == 1
    assert "feature criada: Login social" in aviso["features"]["ultimo"]


def test_o_proprio_autor_nao_recebe_aviso_da_feature(cena):
    mundo, ana, _, slug = cena
    ana.post(_feat(slug), {"title": "Minha"})
    ana.patch(f"{_feat(slug)}/F-1", {"title": "Minha 2"})
    assert _sem_features(mundo.nao_lidos(ana, slug))


def test_cada_evento_de_feature_conta_e_ultimo_e_o_mais_recente(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "Velha"})
    ana.patch(f"{_feat(slug)}/F-1", {"title": "Nova", "description": "texto"})
    aviso = mundo.nao_lidos(bia, slug)["features"]
    assert aviso["nao_lidos"] == 3  # criada + título + descrição
    assert "description" in aviso["ultimo"]


def test_list_features_marca_lido(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    assert bia.get(_feat(slug)).status_code == 200
    assert _sem_features(mundo.nao_lidos(bia, slug))
    ana.patch(f"{_feat(slug)}/F-1", {"description": "mudou"})
    assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1
    bia.get(_feat(slug))
    assert _sem_features(mundo.nao_lidos(bia, slug))


def test_read_feature_nao_marca_lido(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    assert bia.get(f"{_feat(slug)}/F-1").status_code == 200
    assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1


def test_chamar_nao_lidos_nao_marca_nada(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    for _ in range(3):
        assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1


def test_marca_e_por_pessoa(cena):
    mundo, ana, bia, slug = cena
    leo = mundo.pessoa("Leo")
    mundo.entrar(leo, slug)
    ana.post(_feat(slug), {"title": "A"})
    bia.get(_feat(slug))
    assert _sem_features(mundo.nao_lidos(bia, slug))
    assert mundo.nao_lidos(leo, slug)["features"]["nao_lidos"] == 1


def test_apagar_feature_conta_e_list_features_limpa(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "Some"})
    bia.get(_feat(slug))
    ana.delete(f"{_feat(slug)}/F-1")
    aviso = mundo.nao_lidos(bia, slug)["features"]
    assert aviso["nao_lidos"] == 1 and "feature apagada" in aviso["ultimo"]
    bia.get(_feat(slug))
    assert _sem_features(mundo.nao_lidos(bia, slug))


def test_evento_de_feature_nao_vaza_pro_contador_de_tasks(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    code = mundo.task(ana, slug)
    aviso = mundo.nao_lidos(bia, slug)
    assert aviso["total"] == 1 and aviso["tasks"][0]["code"] == code
    assert aviso["tasks"][0]["nao_lidos"] == 1  # só o task.created, não o da feature


def test_features_de_outro_projeto_nao_contam(cena):
    mundo, ana, bia, slug = cena
    outro = mundo.projeto(ana, "Outro")
    mundo.entrar(bia, outro)
    ana.post(_feat(outro), {"title": "So la"})
    assert _sem_features(mundo.nao_lidos(bia, slug))
    assert mundo.nao_lidos(bia, outro)["features"]["nao_lidos"] == 1
    bia.get(_feat(slug))
    assert mundo.nao_lidos(bia, outro)["features"]["nao_lidos"] == 1


def test_evento_que_chega_durante_a_listagem_continua_nao_lido(cena, monkeypatch):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    original = features_service.serializar

    def serializar_e_depois_chega_um(conn, feature):
        dados = original(conn, feature)
        mundo.sql(
            "INSERT INTO events (project_id, feature_id, author_id, agent, kind, texto, campo, valor_de,"
            " valor_para, created_at) VALUES (?, ?, ?, 'claude', 'feature.field_changed', ?, 'title', 'A',"
            " 'B', '2999-01-01T00:00:00+00:00')",
            (feature["project_id"], feature["id"], ana.id, feature["code"]),
        )
        return dados

    with monkeypatch.context() as m:
        m.setattr(features_service, "serializar", serializar_e_depois_chega_um)
        bia.get(_feat(slug))
    assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1


def test_marca_so_anda_pra_frente(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    bia.get(_feat(slug))
    antes = mundo.sql("SELECT last_read_seq FROM feature_reads")[0]["last_read_seq"]
    (projeto_id,) = [r["id"] for r in mundo.sql("SELECT id FROM projects")]
    conn = db.conectar()
    try:
        with conn:
            features_repositorio.marcar_lidos(conn, projeto_id, bia.id, 1)
    finally:
        conn.close()
    assert mundo.sql("SELECT last_read_seq FROM feature_reads")[0]["last_read_seq"] == antes


def test_listar_sem_nenhum_evento_de_feature_nao_cria_marca(cena):
    mundo, _, bia, slug = cena
    bia.get(_feat(slug))
    assert mundo.sql("SELECT COUNT(*) AS n FROM feature_reads")[0]["n"] == 0


def test_quem_entra_depois_nao_tem_o_historico_de_features_como_nao_lido(mundo):
    ana = mundo.pessoa("Ana")
    slug = mundo.projeto(ana)
    ana.post(_feat(slug), {"title": "Antiga"})
    mundo.datar_eventos("2026-01-01T10:00:00+00:00")
    bia = mundo.pessoa("Bia")
    mundo.entrar(bia, slug, em="2026-02-01T10:00:00+00:00")
    assert _sem_features(mundo.nao_lidos(bia, slug))
    ana.patch(f"{_feat(slug)}/F-1", {"description": "depois"})
    mundo.sql("UPDATE events SET created_at = '2026-03-01T10:00:00+00:00' WHERE campo = 'description'")
    assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1


def test_nao_membro_nao_marca_nem_ve(cena):
    mundo, ana, _, slug = cena
    intruso = mundo.pessoa("Intruso")
    ana.post(_feat(slug), {"title": "A"})
    assert intruso.get(_feat(slug)).status_code == 404
    assert mundo.sql("SELECT COUNT(*) AS n FROM feature_reads")[0]["n"] == 0


def test_apagar_projeto_e_pessoa_limpam_a_marca(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    bia.get(_feat(slug))
    assert mundo.sql("SELECT COUNT(*) AS n FROM feature_reads")[0]["n"] == 1
    assert mundo.cliente.delete(f"/projetos/{slug}", headers=mundo.admin).status_code == 204
    assert mundo.sql("SELECT COUNT(*) AS n FROM feature_reads")[0]["n"] == 0


def test_banco_antigo_sem_a_tabela_ganha_a_tabela_no_start(mundo):
    mundo.sql("DROP TABLE feature_reads")
    db.iniciar_banco()
    assert mundo.sql("SELECT COUNT(*) AS n FROM feature_reads")[0]["n"] == 0


# ---------- web ---------- #


def test_web_conta_evento_de_feature_nos_contadores(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    web = _logar(bia.token)
    html = web.get(f"/web/p/{slug}/features").text
    assert 'id="contador-features" hidden' not in html and 'id="contador-features"' in html
    assert "tem-notificacoes" in html
    assert 'class="sidebar-topbar-notification-count" aria-hidden="true">1<' in html
    assert f'id="contador-{slug}"' in html and f'id="contador-{slug}" hidden' not in html


def test_web_nao_marca_lido_e_a_ia_limpa(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    web = _logar(bia.token)
    web.get(f"/web/p/{slug}/features")
    web.get(f"/web/p/{slug}/f/F-1")
    assert mundo.nao_lidos(bia, slug)["features"]["nao_lidos"] == 1
    bia.get(_feat(slug))
    html = web.get(f"/web/p/{slug}/features").text
    assert "tem-notificacoes" not in html and 'id="contador-features" hidden' in html


def test_web_card_e_painel_somam_eventos_de_feature(cena):
    mundo, ana, bia, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    web = _logar(bia.token)
    assert "tile-nao-lidos" in web.get(f"/web/p/{slug}").text
    inicio = web.get("/web").text
    assert "Não lidos (IA)" in inicio
    assert "<dd>1</dd>" in inicio


def test_web_admin_nao_mostra_contador_de_feature(cena):
    mundo, ana, _, slug = cena
    ana.post(_feat(slug), {"title": "A"})
    adm = _logar(ADMIN, admin=True)
    html = adm.get(f"/web/admin/p/{slug}/features").text
    assert "contador-features" not in html

