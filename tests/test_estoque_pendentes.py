import pytest
from fastapi import HTTPException

from repository.estoque import listar_pendentes, confirmar_pendente, mostrar_produtos
from schemas.schemas import ConfirmarPendenteInput
from conftest import make_setor, make_funcionario, make_produto, make_compra, set_token


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── listar_pendentes ─────────────────────────────────────────────────────────

def test_listar_pendentes_vazio_sem_compras(engine, session):
    assert listar_pendentes() == []


def test_listar_pendentes_mostra_itens_de_compra_autorizada(engine, session):
    setor = make_setor(session, tipo="compras_pend1")
    func = make_funcionario(session, setor_id=setor.id)
    compra = make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "PEND001", "nomedoproduto": "Produto Pendente", "categoria": "Geral",
         "preco_venda": 20.0, "quantidade": 8, "preco_custo": 9.0},
    ])
    pendentes = listar_pendentes()
    assert len(pendentes) == 1
    p = pendentes[0]
    assert p["compra_id"] == compra.id
    assert p["nomedoproduto"] == "Produto Pendente"
    assert p["codigodebarras"] == "PEND001"
    assert p["quantidade"] == 8
    assert p["preco_custo"] == 9.0
    assert p["preco_venda"] == 20.0


def test_listar_pendentes_ignora_itens_ja_lancados(engine, session):
    setor = make_setor(session, tipo="compras_pend2")
    func = make_funcionario(session, setor_id=setor.id)
    from datetime import datetime, timezone
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "PEND002", "nomedoproduto": "Ja Lancado", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 3, "preco_custo": 4.0,
         "lancado_em": datetime.now(timezone.utc)},
    ])
    assert listar_pendentes() == []


def test_listar_pendentes_ignora_compras_nao_autorizadas(engine, session):
    setor = make_setor(session, tipo="compras_pend3")
    func = make_funcionario(session, setor_id=setor.id)
    make_compra(session, func.id, status="aguardando_diretor", itens=[
        {"codigodebarras": "PEND003", "nomedoproduto": "Ainda nao autorizado", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 3, "preco_custo": 4.0},
    ])
    assert listar_pendentes() == []


# ── confirmar_pendente ───────────────────────────────────────────────────────

def test_confirmar_pendente_cria_produto_novo(engine, session):
    setor = make_setor(session, tipo="compras_pend4")
    solicitante = make_funcionario(session, setor_id=setor.id)
    compra = make_compra(session, solicitante.id, status="autorizada", itens=[
        {"codigodebarras": "CONF001", "nomedoproduto": "Nome Original", "categoria": "Geral",
         "preco_venda": 15.0, "quantidade": 10, "preco_custo": 6.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    setor_estoque = make_setor(session, tipo="estoque")
    func_estoque = make_funcionario(session, setor_id=setor_estoque.id)

    dados = ConfirmarPendenteInput(
        nomedoproduto="Nome Corrigido", codigodebarras="CODIGO-CORRIGIDO",
        preco_venda=18.0, categoria="Limpeza",
    )
    resultado = confirmar_pendente(item_id, dados, func_estoque.id)
    assert resultado["detail"] == "Produto lançado no estoque com sucesso"

    produtos = mostrar_produtos()
    produto = next(p for p in produtos if p.codigodebarras == "CODIGO-CORRIGIDO")
    assert produto.nomedoproduto == "Nome Corrigido"
    assert produto.quantidade == 10
    assert produto.preco == 18.0
    assert produto.preco_custo == 6.0
    assert produto.categoria == "Limpeza"

    assert listar_pendentes() == []


def test_confirmar_pendente_incrementa_produto_existente(engine, session):
    setor = make_setor(session, tipo="compras_pend5")
    solicitante = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="EXIST-PEND", qtd=5, preco=9.0, custo=3.0)
    make_compra(session, solicitante.id, status="autorizada", itens=[
        {"codigodebarras": "EXIST-PEND", "nomedoproduto": "Produto Existente", "categoria": "Geral",
         "preco_venda": 9.0, "quantidade": 12, "preco_custo": 4.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    setor_estoque = make_setor(session, tipo="estoque")
    func_estoque = make_funcionario(session, setor_id=setor_estoque.id)

    dados = ConfirmarPendenteInput(
        nomedoproduto="Produto Existente", codigodebarras="EXIST-PEND",
        preco_venda=9.0, categoria="Geral",
    )
    confirmar_pendente(item_id, dados, func_estoque.id)

    produtos = mostrar_produtos()
    produto = next(p for p in produtos if p.codigodebarras == "EXIST-PEND")
    assert produto.quantidade == 17
    assert produto.preco_custo == 4.0


def test_confirmar_pendente_inexistente_404(engine, session):
    dados = ConfirmarPendenteInput(
        nomedoproduto="X", codigodebarras="X", preco_venda=1.0, categoria="X",
    )
    with pytest.raises(HTTPException) as exc:
        confirmar_pendente(99999, dados, 1)
    assert exc.value.status_code == 404


def test_confirmar_pendente_duas_vezes_falha(engine, session):
    setor = make_setor(session, tipo="compras_pend6")
    solicitante = make_funcionario(session, setor_id=setor.id)
    make_compra(session, solicitante.id, status="autorizada", itens=[
        {"codigodebarras": "DUPLO001", "nomedoproduto": "Produto Duplo", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 5, "preco_custo": 3.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    setor_estoque = make_setor(session, tipo="estoque")
    func_estoque = make_funcionario(session, setor_id=setor_estoque.id)
    dados = ConfirmarPendenteInput(
        nomedoproduto="Produto Duplo", codigodebarras="DUPLO001",
        preco_venda=10.0, categoria="Geral",
    )
    confirmar_pendente(item_id, dados, func_estoque.id)

    with pytest.raises(HTTPException) as exc:
        confirmar_pendente(item_id, dados, func_estoque.id)
    assert exc.value.status_code == 400


# ── permissão via rotas HTTP ─────────────────────────────────────────────────

def test_rota_pendentes_nega_funcionario_fora_do_setor_estoque(client, session, engine):
    setor = make_setor(session, tipo="vendas_pend")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.get("/estoque/pendentes", headers=_headers(token))
    assert r.status_code == 403


def test_rota_confirmar_pendente_nega_funcionario_fora_do_setor_estoque(client, session, engine):
    setor = make_setor(session, tipo="compras_pend7")
    solicitante = make_funcionario(session, setor_id=setor.id)
    make_compra(session, solicitante.id, status="autorizada")
    item_id = listar_pendentes()[0]["id"]

    setor_vendas = make_setor(session, tipo="vendas_pend2")
    func_vendas = make_funcionario(session, setor_id=setor_vendas.id)
    token = set_token(session, func_vendas)

    r = client.post(f"/estoque/pendentes/{item_id}/confirmar", json={
        "nomedoproduto": "X", "codigodebarras": "X", "preco_venda": 1.0, "categoria": "X",
    }, headers=_headers(token))
    assert r.status_code == 403
