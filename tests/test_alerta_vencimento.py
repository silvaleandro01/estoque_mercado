"""Testes do alerta de vencimento de lotes (GET /estoque/alerta-vencimento)."""

from datetime import timedelta

from repository.lotes import listar_alerta_vencimento
from utils.timezone import hoje_brasil
from conftest import make_setor, make_funcionario, make_produto, make_lote, set_token


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_alerta_vencimento_lista_lote_vencendo_dentro_do_prazo(engine, session):
    hoje = hoje_brasil()
    produto = make_produto(session, codigo="ALERTA001", qtd=10)
    make_lote(session, produto.id, codigo_lote="L1", qtd=10, validade=hoje + timedelta(days=3))

    resultado = listar_alerta_vencimento(dias=7)

    assert resultado["dias"] == 7
    assert len(resultado["vencendo"]) == 1
    assert resultado["vencendo"][0]["codigodebarras"] == "ALERTA001"
    assert resultado["vencendo"][0]["dias_restantes"] == 3
    assert resultado["vencidos"] == []


def test_alerta_vencimento_lista_lotes_ja_vencidos(engine, session):
    hoje = hoje_brasil()
    produto = make_produto(session, codigo="ALERTA002", qtd=5)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=hoje - timedelta(days=2))

    resultado = listar_alerta_vencimento(dias=7)

    assert resultado["vencendo"] == []
    assert len(resultado["vencidos"]) == 1
    assert resultado["vencidos"][0]["codigodebarras"] == "ALERTA002"
    assert resultado["vencidos"][0]["dias_restantes"] == -2


def test_alerta_vencimento_fora_do_prazo_nao_aparece_em_nenhuma_lista(engine, session):
    hoje = hoje_brasil()
    produto = make_produto(session, codigo="ALERTA003", qtd=5)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=hoje + timedelta(days=30))

    resultado = listar_alerta_vencimento(dias=7)

    assert resultado["vencendo"] == []
    assert resultado["vencidos"] == []


def test_alerta_vencimento_ignora_lote_sem_validade_conhecida(engine, session):
    """Lote legado (validade=None) nunca aparece -- não há como saber se
    está vencido ou não (ver docstring de repository/lotes.py)."""
    produto = make_produto(session, codigo="ALERTA004", qtd=8)
    make_lote(session, produto.id, codigo_lote="LEGADO", qtd=8, validade=None)

    resultado = listar_alerta_vencimento(dias=7)

    assert resultado["vencendo"] == []
    assert resultado["vencidos"] == []


def test_alerta_vencimento_ignora_lote_com_quantidade_zerada(engine, session):
    """Lote já totalmente consumido (quantidade=0) não deveria gerar
    alerta, mesmo vencido -- não sobra produto físico para descartar."""
    hoje = hoje_brasil()
    produto = make_produto(session, codigo="ALERTA005", qtd=0)
    make_lote(session, produto.id, codigo_lote="L1", qtd=0, validade=hoje - timedelta(days=1))

    resultado = listar_alerta_vencimento(dias=7)

    assert resultado["vencendo"] == []
    assert resultado["vencidos"] == []


def test_alerta_vencimento_parametro_dias_e_configuravel(engine, session):
    hoje = hoje_brasil()
    produto = make_produto(session, codigo="ALERTA006", qtd=5)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=hoje + timedelta(days=10))

    assert listar_alerta_vencimento(dias=7)["vencendo"] == []
    resultado_15 = listar_alerta_vencimento(dias=15)
    assert len(resultado_15["vencendo"]) == 1
    assert resultado_15["dias"] == 15


def test_alerta_vencimento_ordenado_por_validade_mais_proxima_primeiro(engine, session):
    hoje = hoje_brasil()
    produto1 = make_produto(session, codigo="ALERTA007A", qtd=5)
    produto2 = make_produto(session, codigo="ALERTA007B", qtd=5)
    make_lote(session, produto1.id, codigo_lote="L1", qtd=5, validade=hoje + timedelta(days=6))
    make_lote(session, produto2.id, codigo_lote="L1", qtd=5, validade=hoje + timedelta(days=1))

    resultado = listar_alerta_vencimento(dias=7)

    assert [v["codigodebarras"] for v in resultado["vencendo"]] == ["ALERTA007B", "ALERTA007A"]


# ── permissão via rota HTTP ─────────────────────────────────────────────────

def test_rota_alerta_vencimento_nega_funcionario_fora_do_setor_estoque(client, session, engine):
    setor = make_setor(session, tipo="alerta_vend")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.get("/estoque/alerta-vencimento", headers=_headers(token))
    assert r.status_code == 403


def test_rota_alerta_vencimento_usa_parametro_dias_da_query(client, session, engine):
    hoje = hoje_brasil()
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    produto = make_produto(session, codigo="ALERTAROTA001", qtd=5)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=hoje + timedelta(days=20))

    r = client.get("/estoque/alerta-vencimento", headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["vencendo"] == []

    r = client.get("/estoque/alerta-vencimento?dias=30", headers=_headers(token))
    assert r.status_code == 200
    assert len(r.json()["vencendo"]) == 1
