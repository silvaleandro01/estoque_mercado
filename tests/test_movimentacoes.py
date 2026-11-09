"""Histórico de movimentações de estoque (Fase 4).

Ver docstring de `utils.database.MovimentacaoEstoque` para a decisão de
arquitetura completa (convenção de sinal, quando `lote_id` é usado, quais
tipos já têm código que os gera nesta fase).

Esta primeira parte cobre a infraestrutura (registrar/listar), a geração de
ENTRADA_COMPRA (cadastro novo, incremento manual, confirmação de pendente) e
de VENDA (uma movimentação POR LOTE consumido via FEFO), além da invariante
central soma(MovimentacaoEstoque.quantidade de um produto) ==
Estoque.quantidade e da invariante por lote rastreado. AJUSTE_INVENTARIO é
coberto à parte (ver seção correspondente mais abaixo, adicionada junto com
o endpoint de ajuste de inventário).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from repository.estoque import criar_estoque, confirmar_pendente, listar_pendentes
from repository.vendas import criar_venda
from repository.movimentacoes import registrar_movimentacao, listar_movimentacoes
from schemas.schemas import EstoqueCreate, VendaInput, ItemVendaSchema, ConfirmarPendenteInput
from utils.database import Estoque, Lote, MovimentacaoEstoque
from conftest import make_setor, make_funcionario, make_produto, make_lote, make_compra, set_token


def _venda_input(codigo, quantidade):
    return VendaInput(itens=[ItemVendaSchema(codigodebarras=codigo, quantidade=quantidade)])


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _movimentacoes(session, estoque_id):
    return session.exec(
        select(MovimentacaoEstoque).where(MovimentacaoEstoque.estoque_id == estoque_id)
    ).all()


def _soma_movimentacoes(session, estoque_id):
    return sum((m.quantidade for m in _movimentacoes(session, estoque_id)), Decimal("0.000"))


def _soma_movimentacoes_do_lote(session, lote_id):
    movs = session.exec(select(MovimentacaoEstoque).where(MovimentacaoEstoque.lote_id == lote_id)).all()
    return sum((m.quantidade for m in movs), Decimal("0.000"))


# ── registrar_movimentacao / listar_movimentacoes (unidade) ─────────────────

def test_registrar_movimentacao_cria_linha_signed_sem_lote(engine, session):
    setor = make_setor(session, tipo="mov1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVU001", qtd=10)

    with Session(engine) as s:
        mov = registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("5"), func.id)
        s.commit()
        assert mov.id is not None

    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_COMPRA"
        assert movs[0].quantidade == Decimal("5.000")
        assert movs[0].funcionario_id == func.id
        assert movs[0].lote_id is None
        assert movs[0].motivo is None


def test_registrar_movimentacao_com_lote_e_motivo_negativa(engine, session):
    setor = make_setor(session, tipo="mov2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVU002", qtd=10)
    lote = make_lote(session, produto.id, codigo_lote="L1", qtd=10)

    with Session(engine) as s:
        registrar_movimentacao(
            s, produto.id, "AJUSTE_INVENTARIO", Decimal("-3"), func.id,
            lote_id=lote.id, motivo="Teste",
        )
        s.commit()

    with Session(engine) as s:
        mov = _movimentacoes(s, produto.id)[0]
        assert mov.lote_id == lote.id
        assert mov.motivo == "Teste"
        assert mov.quantidade == Decimal("-3.000")


def test_listar_movimentacoes_produto_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        listar_movimentacoes(9999)
    assert exc.value.status_code == 404


def test_listar_movimentacoes_ordena_mais_recente_primeiro(engine, session):
    setor = make_setor(session, tipo="mov3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVU003", qtd=10)
    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("1"), func.id)
        s.commit()
    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("2"), func.id)
        s.commit()

    movs = listar_movimentacoes(produto.id)
    assert len(movs) == 2
    assert movs[0].quantidade == Decimal("2.000")
    assert movs[1].quantidade == Decimal("1.000")


# ── ENTRADA_COMPRA via criar_estoque (cadastro novo + incremento) ───────────

def test_criar_estoque_cadastro_novo_gera_entrada_compra(engine, session):
    setor = make_setor(session, tipo="mov_cad1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Mov", quantidade=Decimal("20"),
                      preco=Decimal("10.00"), codigodebarras="MOVCAD001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_COMPRA"
        assert movs[0].quantidade == Decimal("20.000")
        assert movs[0].lote_id is None
        assert movs[0].funcionario_id == func.id


def test_criar_estoque_cadastro_com_quantidade_zero_nao_gera_movimentacao(engine, session):
    setor = make_setor(session, tipo="mov_cad0")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Zero", quantidade=Decimal("0"),
                      preco=Decimal("10.00"), codigodebarras="MOVCAD000", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _movimentacoes(s, produto.id) == []


def test_criar_estoque_incremento_gera_entrada_compra(engine, session):
    setor = make_setor(session, tipo="mov_incr1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVINCR001", qtd=10)
    criar_estoque(
        EstoqueCreate(nomedoproduto="Produto", quantidade=Decimal("5"),
                      preco=Decimal("10.00"), codigodebarras="MOVINCR001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_COMPRA"
        assert movs[0].quantidade == Decimal("5.000")
        assert movs[0].lote_id is None


# ── ENTRADA_COMPRA via confirmar_pendente (ligada ao lote criado) ───────────

def test_confirmar_pendente_produto_novo_gera_entrada_compra_com_lote(engine, session):
    setor = make_setor(session, tipo="mov_pend1")
    func = make_funcionario(session, setor_id=setor.id)
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "MOVPEND001", "nomedoproduto": "Produto Pendente", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 7, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto Pendente", codigodebarras="MOVPEND001",
                                preco_venda=10.0, categoria="Geral",
                                codigo_lote="LOTE-MOVPEND001", validade=date(2030, 1, 1)),
        func.id,
    )
    with Session(engine) as s:
        produto = s.exec(select(Estoque).where(Estoque.codigodebarras == "MOVPEND001")).first()
        lote = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_COMPRA"
        assert movs[0].quantidade == Decimal("7.000")
        assert movs[0].lote_id == lote.id


def test_confirmar_pendente_produto_existente_gera_entrada_compra_com_lote(engine, session):
    setor = make_setor(session, tipo="mov_pend2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVPEND002", qtd=10)
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "MOVPEND002", "nomedoproduto": "Produto", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 4, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto", codigodebarras="MOVPEND002",
                                preco_venda=10.0, categoria="Geral",
                                codigo_lote="LOTE-MOVPEND002", validade=date(2030, 1, 1)),
        func.id,
    )
    with Session(engine) as s:
        lote_datado = s.exec(
            select(Lote).where(Lote.estoque_id == produto.id, Lote.validade.is_not(None))
        ).first()
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_COMPRA"
        assert movs[0].quantidade == Decimal("4.000")
        assert movs[0].lote_id == lote_datado.id


# ── VENDA: uma movimentação POR LOTE consumido (não uma linha agregada) ────

def test_criar_venda_consumo_de_um_lote_gera_uma_movimentacao_venda(engine, session):
    setor = make_setor(session, tipo="mov_venda1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVVENDA001", qtd=10, preco=5.0)
    lote = make_lote(session, produto.id, codigo_lote="L1", qtd=10, validade=date.today() + timedelta(days=10))

    criar_venda(_venda_input("MOVVENDA001", 4), func.id)

    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "VENDA"
        assert movs[0].quantidade == Decimal("-4.000")
        assert movs[0].lote_id == lote.id
        assert movs[0].funcionario_id == func.id


def test_criar_venda_consumo_de_multiplos_lotes_gera_uma_movimentacao_por_lote(engine, session):
    """Venda que precisa consumir de 2 lotes via FEFO gera 2 movimentações
    VENDA distintas, uma por lote -- cada consumo de lote é um evento
    próprio, não uma única linha agregando a venda inteira."""
    setor = make_setor(session, tipo="mov_venda2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVVENDA002", qtd=7, preco=5.0)
    lote1 = make_lote(session, produto.id, codigo_lote="L1", qtd=3, validade=date.today() + timedelta(days=2))
    lote2 = make_lote(session, produto.id, codigo_lote="L2", qtd=4, validade=date.today() + timedelta(days=10))

    criar_venda(_venda_input("MOVVENDA002", 5), func.id)

    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 2
        assert all(m.tipo == "VENDA" for m in movs)
        por_lote = {m.lote_id: m.quantidade for m in movs}
        assert por_lote[lote1.id] == Decimal("-3.000")  # esgotado primeiro (vence antes)
        assert por_lote[lote2.id] == Decimal("-2.000")  # completa o restante


def test_criar_venda_produto_legado_sem_lote_materializa_e_gera_movimentacao(engine, session):
    """Produto sem nenhum lote cadastrado (legado) -- consumir_fefo
    materializa o "lote sem validade" cobrindo o saldo atual antes de
    consumir; a movimentação VENDA fica ligada a esse lote recém-materializado."""
    setor = make_setor(session, tipo="mov_venda3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="MOVVENDA003", qtd=8, preco=5.0)

    criar_venda(_venda_input("MOVVENDA003", 3), func.id)

    with Session(engine) as s:
        lote = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "VENDA"
        assert movs[0].quantidade == Decimal("-3.000")
        assert movs[0].lote_id == lote.id


# ── invariante: soma(MovimentacaoEstoque.quantidade) == Estoque.quantidade ──

def test_invariante_soma_movimentacoes_bate_com_estoque_entrada_e_venda(engine, session):
    """
    Mesma invariante central estabelecida para `Lote` na Fase 3, agora para
    o histórico de movimentações: a soma das quantidades (signed) de
    MovimentacaoEstoque de um produto, desde sempre, bate com
    Estoque.quantidade atual. Sequência cobrindo cadastro, incremento,
    confirmação de pendente (compra) e venda (consumo FEFO). O passo de
    ajuste de inventário é coberto por uma invariante própria (ver seção de
    AJUSTE_INVENTARIO mais abaixo).
    """
    setor = make_setor(session, tipo="mov_inv1")
    func = make_funcionario(session, setor_id=setor.id)

    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Invariante Mov", quantidade=Decimal("20"),
                      preco=Decimal("10.00"), codigodebarras="MOVINV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Invariante Mov", quantidade=Decimal("5"),
                      preco=Decimal("10.00"), codigodebarras="MOVINV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "MOVINV001", "nomedoproduto": "Produto Invariante Mov", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 7, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto Invariante Mov", codigodebarras="MOVINV001",
                                preco_venda=10.0, categoria="Geral",
                                codigo_lote="LOTE-MOVINV001", validade=date(2030, 1, 1)),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    criar_venda(_venda_input("MOVINV001", 12), func.id)
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade


def test_invariante_lote_rastreado_soma_movimentacoes_bate_com_saldo_do_lote(engine, session):
    """
    Para um LOTE RASTREADO (codigo_lote/validade reais, nascido já dentro
    desta fase via confirmação de compra pendente), a soma das
    movimentações ligadas a ele (lote_id) bate com quanto o lote já foi
    alimentado/consumido desde que foi criado -- o mesmo tipo de invariante
    da Fase 3 (soma(Lote.quantidade) == Estoque.quantidade), só que por
    lote individual em vez de por produto.

    NÃO vale para o "lote sem validade" (legado): esse lote não nasce de
    uma movimentação própria -- é um residual recalculado do zero por
    reconciliar_lote_sem_validade (ver repository/lotes.py), sem um
    histórico incremental de movimentações por trás. Produtos/lotes
    anteriores a esta fase (ou cujo saldo nunca passou por um ponto que
    gera movimentação ligada a lote) não têm histórico retroativo
    reconstruído -- documentado também na migration.sql.
    """
    setor = make_setor(session, tipo="mov_inv_lote")
    func = make_funcionario(session, setor_id=setor.id)
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "MOVINVLOTE001", "nomedoproduto": "Produto Lote", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 10, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto Lote", codigodebarras="MOVINVLOTE001",
                                preco_venda=10.0, categoria="Geral",
                                codigo_lote="LOTE-MOVINVLOTE001", validade=date(2030, 1, 1)),
        func.id,
    )
    with Session(engine) as s:
        produto = s.exec(select(Estoque).where(Estoque.codigodebarras == "MOVINVLOTE001")).first()
        lote = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        assert lote.quantidade == Decimal("10.000")
        assert _soma_movimentacoes_do_lote(s, lote.id) == lote.quantidade
        lote_id = lote.id

    criar_venda(_venda_input("MOVINVLOTE001", 4), func.id)

    with Session(engine) as s:
        lote_db = s.get(Lote, lote_id)
        assert lote_db.quantidade == Decimal("6.000")
        assert _soma_movimentacoes_do_lote(s, lote_id) == lote_db.quantidade


# ── permissão via rota HTTP (GET /estoque/{id}/movimentacoes) ───────────────

def test_rota_movimentacoes_nega_funcionario_fora_do_setor_estoque(client, session, engine):
    produto = make_produto(session, codigo="MOVROTA001", qtd=10)
    setor = make_setor(session, tipo="mov_rota_neg")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.get(f"/estoque/{produto.id}/movimentacoes", headers=_headers(token))
    assert r.status_code == 403


def test_rota_movimentacoes_permite_setor_estoque(client, session, engine):
    produto = make_produto(session, codigo="MOVROTA002", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("10"), func.id)
        s.commit()

    r = client.get(f"/estoque/{produto.id}/movimentacoes", headers=_headers(token))
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 1
    assert corpo[0]["tipo"] == "ENTRADA_COMPRA"
    assert corpo[0]["quantidade"] == 10.0


def test_rota_movimentacoes_produto_inexistente_404(client):
    r = client.get("/estoque/99999/movimentacoes")
    assert r.status_code == 404
