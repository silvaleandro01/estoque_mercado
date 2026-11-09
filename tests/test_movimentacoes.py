"""Histórico de movimentações de estoque (Fase 4).

Ver docstring de `utils.database.MovimentacaoEstoque` para a decisão de
arquitetura completa (convenção de sinal, quando `lote_id` é usado, quais
tipos já têm código que os gera nesta fase).

Esta primeira parte cobre a infraestrutura (registrar/listar), a geração de
ENTRADA_MANUAL (cadastro novo e incremento manual via criar_estoque) e
ENTRADA_COMPRA (confirmação de pendente -- entrada rastreada via
compra/fornecedor de verdade), e de VENDA (uma movimentação POR LOTE
consumido via FEFO), além da invariante
central soma(MovimentacaoEstoque.quantidade de um produto) ==
Estoque.quantidade e da invariante por lote rastreado. AJUSTE_INVENTARIO é
coberto à parte (ver seção correspondente mais abaixo, adicionada junto com
o endpoint de ajuste de inventário).
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select, SQLModel

from repository.estoque import criar_estoque, confirmar_pendente, listar_pendentes, deletar_estoque
from repository.funcionarios import deletar_funcionario
from repository.vendas import criar_venda
from repository.movimentacoes import registrar_movimentacao, listar_movimentacoes
from schemas.schemas import EstoqueCreate, VendaInput, ItemVendaSchema, ConfirmarPendenteInput
from utils.database import Estoque, Funcionario, HistoricoSenha, Lote, MovimentacaoEstoque
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


# ── ENTRADA_MANUAL via criar_estoque (cadastro novo + incremento) ──────────
# IMPORTANTE 5 (revisão da Fase 4): criar_estoque (cadastro e incremento, os
# dois caminhos de POST /estoque/inserir) passa a gerar ENTRADA_MANUAL, não
# mais ENTRADA_COMPRA -- esse tipo fica reservado só para confirmar_pendente
# (entrada rastreada via compra/fornecedor de verdade).

def test_criar_estoque_cadastro_novo_gera_entrada_manual(engine, session):
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
        assert movs[0].tipo == "ENTRADA_MANUAL"
        assert movs[0].quantidade == Decimal("20.000")
        # CRÍTICO 2 (revisão da Fase 4): lote_id agora aponta pro lote "sem
        # validade" (reconciliado pelo próprio cadastro), não mais None --
        # fecha a contradição do docstring de MovimentacaoEstoque.
        assert movs[0].lote_id is not None
        lote_residual = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        assert movs[0].lote_id == lote_residual.id
        assert lote_residual.quantidade == Decimal("20.000")
        assert movs[0].funcionario_id == func.id


def test_criar_estoque_cadastro_com_quantidade_zero_gera_movimentacao_zerada(engine, session):
    """IMPORTANTE 6 (revisão da Fase 4): diferente de incremento/ajuste em
    produto JÁ existente (onde delta == 0 continua pulando o registro), o
    CADASTRO de um produto novo sempre gera uma movimentação -- mesmo com
    saldo inicial 0 -- deixando um rastro auditável de "quando o produto
    nasceu" dentro do domínio de movimentações de estoque."""
    setor = make_setor(session, tipo="mov_cad0")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Zero", quantidade=Decimal("0"),
                      preco=Decimal("10.00"), codigodebarras="MOVCAD000", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 1
        assert movs[0].tipo == "ENTRADA_MANUAL"
        assert movs[0].quantidade == Decimal("0.000")
        # Saldo 0: reconciliar_lote_sem_validade não cria lote nenhum
        # (residual fica 0), então esta movimentação de criação fica sem
        # lote_id mesmo.
        assert movs[0].lote_id is None


def test_criar_estoque_incremento_gera_entrada_manual(engine, session):
    """Base criada via criar_estoque (cadastro), não make_produto direto --
    um produto 100% nascido dentro da Fase 4 não tem saldo legado
    pré-existente não rastreado, então o delta do incremento no lote "sem
    validade" bate exatamente com o incremento nominal (sem nenhuma
    surpresa de materialização de saldo antigo -- ver nuance no docstring
    de reconciliar_lote_sem_validade)."""
    setor = make_setor(session, tipo="mov_incr1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto", quantidade=Decimal("10"),
                      preco=Decimal("10.00"), codigodebarras="MOVINCR001", categoria="Geral"),
        func.id,
    )
    criar_estoque(
        EstoqueCreate(nomedoproduto="Produto", quantidade=Decimal("5"),
                      preco=Decimal("10.00"), codigodebarras="MOVINCR001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        # 2 movimentações: a do cadastro (quantidade=10) + a do incremento
        # (quantidade=5) -- ambas ligadas ao mesmo lote "sem validade".
        assert len(movs) == 2
        incremento = max(movs, key=lambda m: m.id)
        assert incremento.tipo == "ENTRADA_MANUAL"
        assert incremento.quantidade == Decimal("5.000")
        assert incremento.lote_id is not None
        lote_residual = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        assert incremento.lote_id == lote_residual.id
        assert lote_residual.quantidade == Decimal("15.000")


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
    """Produto criado via make_produto (legado: saldo=10 pré-existente, sem
    NENHUM lote/movimentação antes) -- confirmar um pendente com lote
    rastreado de verdade gera DUAS movimentações (CRÍTICO 2 da revisão da
    Fase 4): a do lote recém-criado (quantidade=4, o que esta confirmação
    de fato trouxe) e uma SEGUNDA, ligada ao lote "sem validade", cobrindo o
    saldo de 10 que nunca tinha sido rastreado em nenhum lote (cenário C do
    docstring de reconciliar_lote_sem_validade -- "descoberto" só agora
    porque a lista de lotes deixou de estar vazia). As duas juntas fecham a
    invariante: soma(movimentações do produto) == Estoque.quantidade final
    (14), não só os 4 desta confirmação."""
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
        lote_residual = s.exec(
            select(Lote).where(Lote.estoque_id == produto.id, Lote.validade.is_(None))
        ).first()
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 2

        mov_rastreada = next(m for m in movs if m.lote_id == lote_datado.id)
        assert mov_rastreada.tipo == "ENTRADA_COMPRA"
        assert mov_rastreada.quantidade == Decimal("4.000")

        mov_residual = next(m for m in movs if m.lote_id == lote_residual.id)
        assert mov_residual.tipo == "ENTRADA_COMPRA"
        assert mov_residual.quantidade == Decimal("10.000")

        assert s.get(Estoque, produto.id).quantidade == Decimal("14.000")
        assert _soma_movimentacoes(s, produto.id) == Decimal("14.000")


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

    CORRIGIDO (CRÍTICO 2 da revisão da Fase 4): até então, esta invariante
    NÃO valia para o "lote sem validade" (legado) -- a movimentação que o
    alimentava era sempre gravada com lote_id=None. Ver
    test_invariante_lote_sem_validade_soma_movimentacoes_bate_com_saldo_do_lote
    logo abaixo para a mesma invariante, agora valendo também pra ele (com
    uma ressalva: só para um produto que nasce inteiramente dentro da Fase 4
    -- um produto genuinamente legado, com saldo pré-existente nunca antes
    rastreado em nenhum lote/movimentação, ainda não tem esse histórico
    reconstruído retroativamente, só absorvido de uma vez na primeira
    reconciliação -- ver docstring de reconciliar_lote_sem_validade).
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


def test_invariante_lote_sem_validade_soma_movimentacoes_bate_com_saldo_do_lote(engine, session):
    """
    CRÍTICO 2 (revisão da Fase 4): a mesma invariante "por lote" acima
    (soma(MovimentacaoEstoque.quantidade de um lote_id) == Lote.quantidade
    desse lote), que já valia só para lotes DATADOS, agora vale TAMBÉM para
    o "lote sem validade" -- desde que o produto nasça inteiramente dentro
    da Fase 4 (sem saldo legado pré-existente não rastreado, ver nuance no
    docstring de reconciliar_lote_sem_validade).

    Sequência: cadastro (gera o lote "sem validade" + sua primeira
    movimentação) -> incremento manual (mexe no mesmo lote) -> ajuste de
    inventário que REDUZ o saldo (mexe no mesmo lote de novo) -- a soma das
    três movimentações ligadas a esse lote_id bate com Lote.quantidade dele
    depois de cada passo.
    """
    setor = make_setor(session, tipo="mov_inv_lote_sv")
    func = make_funcionario(session, setor_id=setor.id)

    # 1) Cadastro com saldo inicial -> primeira movimentação do lote "sem
    # validade" (criado agora).
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Lote SV", quantidade=Decimal("20"),
                      preco=Decimal("10.00"), codigodebarras="MOVINVLOTESV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        lote_sv = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        assert lote_sv.quantidade == Decimal("20.000")
        assert _soma_movimentacoes_do_lote(s, lote_sv.id) == lote_sv.quantidade
        lote_id = lote_sv.id

    # 2) Incremento manual -> segunda movimentação, mesmo lote.
    criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Lote SV", quantidade=Decimal("5"),
                      preco=Decimal("10.00"), codigodebarras="MOVINVLOTESV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        lote_db = s.get(Lote, lote_id)
        assert lote_db.quantidade == Decimal("25.000")
        assert _soma_movimentacoes_do_lote(s, lote_id) == lote_db.quantidade

    # 3) Ajuste de inventário que reduz o saldo -> terceira movimentação,
    # mesmo lote (ajustar_inventario nunca toca lote datado -- não há
    # nenhum neste produto -- então o delta cai inteiro no residual).
    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("18"), motivo="Perda não contabilizada"), func.id,
    )
    with Session(engine) as s:
        lote_db = s.get(Lote, lote_id)
        assert lote_db.quantidade == Decimal("18.000")
        assert _soma_movimentacoes_do_lote(s, lote_id) == lote_db.quantidade
        # Fecha também a invariante por PRODUTO (sempre válida, ver seção
        # acima) -- as três movimentações, todas ligadas ao mesmo lote,
        # também batem com Estoque.quantidade.
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade == Decimal("18.000")


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
    assert corpo[0]["unidade_medida"] == "UN"


# ── IMPORTANTE 3 (revisão do painel -- Fase 4) -- snapshot de unidade_medida ─

def test_registrar_movimentacao_grava_snapshot_da_unidade_medida_do_produto(engine, session):
    setor = make_setor(session, tipo="unidade1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="UNIDADE001", qtd=10, unidade="KG")

    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("10"), func.id)
        s.commit()

    with Session(engine) as s:
        mov = _movimentacoes(s, produto.id)[0]
        assert mov.unidade_medida == "KG"


def test_mudar_unidade_medida_do_produto_nao_altera_snapshot_de_movimentacao_antiga(client, session, engine):
    """O bug que o painel apontou: o frontend formatava TODO o histórico com
    a unidade ATUAL do produto -- se o produto mudasse de KG pra UN depois,
    reabrir o histórico distorcia (arredondava) movimentações antigas que
    eram fracionárias. A correção é o snapshot em si: uma movimentação
    registrada quando o produto era KG continua com unidade_medida=KG na
    resposta da API mesmo depois do produto virar UN."""
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="UNIDADE002", qtd=10, unidade="KG")
    token = set_token(session, func)

    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("1.350"), func.id)
        s.commit()

    # Produto muda de KG pra UN (ex.: correção de cadastro).
    with Session(engine) as s:
        produto_db = s.get(Estoque, produto.id)
        produto_db.unidade_medida = "UN"
        s.add(produto_db)
        s.commit()

    r = client.get(f"/estoque/{produto.id}/movimentacoes", headers=_headers(token))
    assert r.status_code == 200
    corpo = r.json()
    assert len(corpo) == 1
    # Snapshot preservado: continua KG, não UN (o valor atual do produto).
    assert corpo[0]["unidade_medida"] == "KG"
    assert corpo[0]["quantidade"] == 1.35


def test_rota_movimentacoes_produto_inexistente_404(client):
    r = client.get("/estoque/99999/movimentacoes")
    assert r.status_code == 404


# ── IMPORTANTE 4 (revisão do painel -- Fase 4) -- paginação ─────────────────
# Sem limite, o endpoint devolvia o histórico INTEIRO de uma vez -- num
# produto com uso pesado de longo prazo isso cresce sem parar (~600ms com 20
# mil linhas, medido pelo painel). limit/offset com default razoável (50) e
# teto máximo (200).

def _criar_movimentacoes(session, engine, produto_id, func_id, quantidade):
    with Session(engine) as s:
        for _ in range(quantidade):
            registrar_movimentacao(s, produto_id, "AJUSTE_INVENTARIO", Decimal("1"), func_id)
        s.commit()


def test_listar_movimentacoes_aplica_limit_padrao(engine, session):
    setor = make_setor(session, tipo="pag1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="PAG001", qtd=10)
    _criar_movimentacoes(session, engine, produto.id, func.id, 60)

    movs = listar_movimentacoes(produto.id)
    assert len(movs) == 50  # LIMIT_PADRAO


def test_listar_movimentacoes_respeita_limit_e_offset_informados(engine, session):
    setor = make_setor(session, tipo="pag2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="PAG002", qtd=10)
    _criar_movimentacoes(session, engine, produto.id, func.id, 10)

    primeira_pagina = listar_movimentacoes(produto.id, limit=4, offset=0)
    segunda_pagina = listar_movimentacoes(produto.id, limit=4, offset=4)
    assert len(primeira_pagina) == 4
    assert len(segunda_pagina) == 4
    # Mais recente primeiro, sem sobreposição entre páginas.
    ids_primeira = {m.id for m in primeira_pagina}
    ids_segunda = {m.id for m in segunda_pagina}
    assert ids_primeira.isdisjoint(ids_segunda)


def test_listar_movimentacoes_limit_acima_do_teto_e_limitado(engine, session):
    """Mesmo que alguém peça um limit absurdamente alto diretamente na
    função (chamada fora da rota, que já valida le= na camada Pydantic/
    FastAPI), o repository aplica o teto máximo por conta própria."""
    setor = make_setor(session, tipo="pag3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="PAG003", qtd=10)
    _criar_movimentacoes(session, engine, produto.id, func.id, 250)

    movs = listar_movimentacoes(produto.id, limit=10_000)
    assert len(movs) == 200  # LIMIT_MAXIMO


def test_rota_movimentacoes_limit_acima_do_teto_rejeitado_com_422(client, session, engine):
    produto = make_produto(session, codigo="PAG004", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.get(f"/estoque/{produto.id}/movimentacoes?limit=201", headers=_headers(token))
    assert r.status_code == 422


def test_rota_movimentacoes_aceita_limit_e_offset_customizados(client, session, engine):
    produto = make_produto(session, codigo="PAG005", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    _criar_movimentacoes(session, engine, produto.id, func.id, 10)

    r = client.get(f"/estoque/{produto.id}/movimentacoes?limit=3&offset=2", headers=_headers(token))
    assert r.status_code == 200
    assert len(r.json()) == 3


# ═══════════════════════════════════════════════════════════════════════════
# AJUSTE_INVENTARIO -- POST /estoque/{id}/ajustar-inventario (Fase 4)
#
# Decisão de arquitetura: PUT /estoque/atualizar deixou de mexer em
# quantidade (ver docstring de schemas.EstoqueUpdate) -- este é o único
# ponto de alteração manual de saldo a partir desta fase, e o único que
# exige `motivo` obrigatório.
# ═══════════════════════════════════════════════════════════════════════════

from repository.estoque import ajustar_inventario, atualizar_estoque
from schemas.schemas import AjusteInventarioInput, EstoqueUpdate


def test_ajustar_inventario_reduz_gera_movimentacao_negativa_com_motivo(engine, session):
    """Base criada via criar_estoque (cadastro), não make_produto direto --
    mesmo raciocínio de test_criar_estoque_incremento_gera_entrada_compra:
    sem saldo legado pré-existente, o delta_residual do ajuste bate
    exatamente com o delta nominal, sem surpresa."""
    setor = make_setor(session, tipo="ajuste1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Ajuste", quantidade=Decimal("10"),
                      preco=Decimal("10.00"), codigodebarras="AJUSTE001", categoria="Geral"),
        func.id,
    )

    resultado = ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("6"), motivo="Contagem física"), func.id,
    )
    assert resultado.quantidade == Decimal("6.000")

    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        # cadastro (quantidade=10) + ajuste (-4).
        assert len(movs) == 2
        ajuste = max(movs, key=lambda m: m.id)
        assert ajuste.tipo == "AJUSTE_INVENTARIO"
        assert ajuste.quantidade == Decimal("-4.000")
        assert ajuste.motivo == "Contagem física"
        # CRÍTICO 2 (revisão da Fase 4): lote_id agora aponta pro lote "sem
        # validade", não mais None.
        assert ajuste.lote_id is not None
        lote_residual = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
        assert ajuste.lote_id == lote_residual.id
        assert lote_residual.quantidade == Decimal("6.000")


def test_ajustar_inventario_aumenta_gera_movimentacao_positiva(engine, session):
    setor = make_setor(session, tipo="ajuste2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Ajuste 2", quantidade=Decimal("10"),
                      preco=Decimal("10.00"), codigodebarras="AJUSTE002", categoria="Geral"),
        func.id,
    )

    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("15"), motivo="Sobra encontrada"), func.id,
    )

    with Session(engine) as s:
        movs = _movimentacoes(s, produto.id)
        assert len(movs) == 2
        ajuste = max(movs, key=lambda m: m.id)
        assert ajuste.tipo == "AJUSTE_INVENTARIO"
        assert ajuste.quantidade == Decimal("5.000")


def test_ajustar_inventario_sem_mudanca_de_saldo_nao_gera_movimentacao(engine, session):
    """Uma contagem que confirma o saldo já registrado (nova_quantidade ==
    quantidade atual) não deixa rastro -- nada mudou, nada a registrar."""
    setor = make_setor(session, tipo="ajuste3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="AJUSTE003", qtd=10)

    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("10"), motivo="Confirmação de contagem"), func.id,
    )

    with Session(engine) as s:
        assert _movimentacoes(s, produto.id) == []
        assert s.get(Estoque, produto.id).quantidade == Decimal("10.000")


def test_ajustar_inventario_motivo_vazio_rejeitado_na_api(client, session, engine):
    produto = make_produto(session, codigo="AJUSTE004", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post(
        f"/estoque/{produto.id}/ajustar-inventario",
        json={"nova_quantidade": 5, "motivo": "   "},
        headers=_headers(token),
    )
    assert r.status_code == 422


def test_ajustar_inventario_motivo_maior_que_255_rejeitado_na_api(client, session, engine):
    """IMPORTANTE 2 (revisão da Fase 4): a coluna real
    (MovimentacaoEstoque.motivo) é VARCHAR(255) -- um motivo maior que isso
    precisa virar um 422 limpo na borda da API, não quebrar lá na frente
    contra o banco com um erro de banco não tratado."""
    produto = make_produto(session, codigo="AJUSTE005", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post(
        f"/estoque/{produto.id}/ajustar-inventario",
        json={"nova_quantidade": 5, "motivo": "x" * 256},
        headers=_headers(token),
    )
    assert r.status_code == 422


def test_ajustar_inventario_motivo_com_255_caracteres_e_aceito(client, session, engine):
    """Limite exato (255) continua válido -- só acima disso é rejeitado."""
    produto = make_produto(session, codigo="AJUSTE006", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post(
        f"/estoque/{produto.id}/ajustar-inventario",
        json={"nova_quantidade": 5, "motivo": "x" * 255},
        headers=_headers(token),
    )
    assert r.status_code == 200


def test_ajustar_inventario_produto_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        ajustar_inventario(9999, AjusteInventarioInput(nova_quantidade=Decimal("5"), motivo="Correção"), 1)
    assert exc.value.status_code == 404


def test_ajustar_inventario_un_rejeita_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="ajuste_un")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="AJUSTEUN001", unidade="UN", qtd=10)

    with pytest.raises(HTTPException) as exc:
        ajustar_inventario(
            produto.id, AjusteInventarioInput(nova_quantidade=Decimal("5.500"), motivo="Correção"), func.id,
        )
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_ajustar_inventario_mantem_invariante_de_lotes(engine, session):
    """Mesma invariante de Lote já estabelecida na Fase 3: um ajuste que
    reduz Estoque.quantidade sem dizer de qual lote tirar precisa continuar
    reconciliando o lote "sem validade" (ver repository/lotes.py)."""
    setor = make_setor(session, tipo="ajuste_lote")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="AJUSTELOTE001", qtd=10)
    make_lote(session, produto.id, codigo_lote="L-DATADO", qtd=10, validade=date.today() + timedelta(days=15))

    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("6"), motivo="Perda não contabilizada"), func.id,
    )

    with Session(engine) as s:
        produto_db = s.get(Estoque, produto.id)
        soma_lotes = sum(
            (l.quantidade for l in s.exec(select(Lote).where(Lote.estoque_id == produto.id)).all()),
            Decimal("0.000"),
        )
        assert produto_db.quantidade == Decimal("6.000")
        assert soma_lotes == produto_db.quantidade


# ── PUT /estoque/atualizar não mexe mais em quantidade nem gera movimentação ─

def test_atualizar_estoque_put_nao_gera_movimentacao(engine, session):
    setor = make_setor(session, tipo="put_sem_mov")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="PUTSEMMOV001", qtd=10)

    atualizar_estoque(
        produto.id,
        EstoqueUpdate(nomedoproduto="Produto Editado", unidade_medida="UN",
                      estoque_minimo=Decimal("0"), preco=Decimal("9.90"),
                      codigodebarras="PUTSEMMOV001", categoria="Geral"),
        func.id,
    )

    with Session(engine) as s:
        assert _movimentacoes(s, produto.id) == []
        assert s.get(Estoque, produto.id).quantidade == Decimal("10.000")


# ── deadlock/concorrência (mesmo padrão dos outros pontos de escrita) ───────

def _deadlock_mysql():
    from sqlalchemy.exc import OperationalError

    class FakeOrigDeadlock(Exception):
        args = (1213, "Deadlock found when trying to get lock; try restarting transaction")

    return OperationalError("COMMIT", {}, FakeOrigDeadlock())


def test_ajustar_inventario_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="ajuste_deadlock")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="AJUSTEDL001", qtd=10)

    def commit_que_falha(self, *args, **kwargs):
        raise _deadlock_mysql()

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha)

    with pytest.raises(HTTPException) as exc:
        ajustar_inventario(
            produto.id, AjusteInventarioInput(nova_quantidade=Decimal("5"), motivo="Correção"), func.id,
        )
    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_ajustar_inventario_consulta_produto_com_lock_for_update(engine, session, monkeypatch):
    """Mesmo padrão de lock dos outros pontos de escrita de estoque
    (criar_estoque/atualizar_estoque/confirmar_pendente/criar_venda) --
    este é um ponto de escrita NOVO desta fase, e a Fase 3 já teve a lição
    de deixar um ponto de escrita novo sem essa proteção."""
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="ajuste_lock")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="AJUSTELOCK001", qtd=10)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("5"), motivo="Correção"), func.id,
    )

    assert statements, "esperava que ajustar_inventario consultasse o produto via session.exec"
    assert getattr(statements[0], "_for_update_arg", None) is not None, (
        "a consulta ao produto em ajustar_inventario precisa usar with_for_update() "
        "para evitar lost update em ajustes concorrentes"
    )
    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada


# ── permissão via rota HTTP (POST /estoque/{id}/ajustar-inventario) ─────────

def test_rota_ajustar_inventario_nega_funcionario_fora_do_setor_estoque(client, session, engine):
    produto = make_produto(session, codigo="AJUSTEROTA001", qtd=10)
    setor = make_setor(session, tipo="ajuste_rota_neg")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post(
        f"/estoque/{produto.id}/ajustar-inventario",
        json={"nova_quantidade": 5, "motivo": "Correção"},
        headers=_headers(token),
    )
    assert r.status_code == 403


def test_rota_ajustar_inventario_permite_setor_estoque(client, session, engine):
    produto = make_produto(session, codigo="AJUSTEROTA002", qtd=10)
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post(
        f"/estoque/{produto.id}/ajustar-inventario",
        json={"nova_quantidade": 7, "motivo": "Contagem física"},
        headers=_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["quantidade"] == 7.0


# ── invariante completa: cadastro + venda + ajuste + confirmação de pendente ─

def test_invariante_soma_movimentacoes_operacoes_mistas_com_ajuste_de_inventario(engine, session):
    """
    Versão completa da invariante central desta fase (ver também
    test_invariante_soma_movimentacoes_bate_com_estoque_entrada_e_venda
    acima): percorre cadastro, venda, AJUSTE DE INVENTÁRIO e confirmação de
    pendente -- a soma das quantidades (signed) de MovimentacaoEstoque de um
    produto, desde sempre, continua batendo com Estoque.quantidade atual
    depois de cada passo.
    """
    setor = make_setor(session, tipo="mov_inv_completa")
    func = make_funcionario(session, setor_id=setor.id)

    # 1) Cadastro com quantidade inicial -> ENTRADA_MANUAL.
    produto = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Misto", quantidade=Decimal("30"),
                      preco=Decimal("10.00"), codigodebarras="MOVMISTO001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    # 2) Venda -> VENDA.
    criar_venda(_venda_input("MOVMISTO001", 10), func.id)
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    # 3) Ajuste de inventário (reduz, ex.: perda não contabilizada).
    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("17"), motivo="Perda não contabilizada"), func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    # 4) Ajuste de inventário (aumenta, ex.: sobra encontrada).
    ajustar_inventario(
        produto.id, AjusteInventarioInput(nova_quantidade=Decimal("22"), motivo="Sobra encontrada na contagem"), func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    # 5) Confirmação de compra pendente -> ENTRADA_COMPRA ligada a lote.
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "MOVMISTO001", "nomedoproduto": "Produto Misto", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 8, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto Misto", codigodebarras="MOVMISTO001",
                                preco_venda=10.0, categoria="Geral",
                                codigo_lote="LOTE-MOVMISTO001", validade=date(2030, 1, 1)),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade

    # 6) Mais uma venda, pra fechar com um consumo FEFO em cima de tudo isso.
    criar_venda(_venda_input("MOVMISTO001", 15), func.id)
    with Session(engine) as s:
        assert _soma_movimentacoes(s, produto.id) == s.get(Estoque, produto.id).quantidade


# ═══════════════════════════════════════════════════════════════════════════
# CRÍTICO 1 (revisão do painel -- Fase 4) -- deletar_estoque/deletar_funcionario
# com movimentação vinculada
#
# `migration.sql` criou a FK de `movimentacao_estoque` para `estoque`/`lote`/
# `funcionario` sem ON DELETE CASCADE -- nem deletar_estoque nem
# deletar_funcionario foram atualizados nesta fase pra apagar/desvincular as
# movimentações antes. Mesmo tipo de bug que a Fase 3 já tinha corrigido pra
# Lote, reintroduzido aqui.
# ═══════════════════════════════════════════════════════════════════════════

def _engine_com_fk_habilitada(monkeypatch):
    """Mesmo padrão de tests/test_fornecedores.py::_engine_com_fk_habilitada
    -- engine SQLite dedicado com PRAGMA foreign_keys=ON via event listener.

    SQLite não aplica FOREIGN KEY por padrão -- o engine global da suíte
    (fixture `engine` de conftest.py) não habilita essa checagem, então sem
    isso o bug de deletar_estoque/deletar_funcionario devolvendo
    IntegrityError/500 cru contra MySQL real nunca seria pego por nenhum
    teste automatizado, exatamente como o painel de revisão apontou."""
    from utils import database as db_mod
    from logs import logs as logs_mod
    from repository import estoque as est_repo
    from repository import funcionarios as func_repo

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _habilitar_fk(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    for mod in (db_mod, logs_mod, est_repo, func_repo):
        monkeypatch.setattr(mod, "engine", eng)
    return eng


def test_deletar_estoque_com_movimentacao_vinculada_nao_quebra(monkeypatch):
    """CRÍTICO 1a: deletar um produto que já tenha QUALQUER movimentação
    registrada (com lote_id ou sem) precisa continuar funcionando (200/sem
    erro), não quebrar com IntegrityError -- o caso normal de uso real, já
    que toda entrada/venda/ajuste gera uma movimentação."""
    eng = _engine_com_fk_habilitada(monkeypatch)
    with Session(eng) as s:
        setor = make_setor(s, tipo="crit1_del_estoque")
        func = make_funcionario(s, setor_id=setor.id)
        produto = make_produto(s, codigo="CRIT1DEL001", qtd=10)
        lote = make_lote(s, produto.id, codigo_lote="L1", qtd=10, validade=date.today() + timedelta(days=10))
        # Uma movimentação ligada a um lote e outra sem lote (lote_id=None)
        # -- cobre as duas FKs que o delete precisa respeitar.
        s.add(MovimentacaoEstoque(
            estoque_id=produto.id, lote_id=lote.id, tipo="ENTRADA_COMPRA",
            quantidade=Decimal("10.000"), funcionario_id=func.id,
        ))
        s.add(MovimentacaoEstoque(
            estoque_id=produto.id, lote_id=None, tipo="AJUSTE_INVENTARIO",
            quantidade=Decimal("0.000"), motivo="Teste", funcionario_id=func.id,
        ))
        s.commit()
        produto_id = produto.id

    resultado = deletar_estoque(produto_id)
    assert resultado["msg"] == "Estoque deletado com sucesso"

    with Session(eng) as s:
        assert s.get(Estoque, produto_id) is None
        assert s.exec(select(MovimentacaoEstoque).where(MovimentacaoEstoque.estoque_id == produto_id)).all() == []


def test_deletar_estoque_emite_delete_de_movimentacoes_antes_de_lotes_e_produto(engine, session, monkeypatch):
    """Mesmo padrão de tests/test_lotes.py::
    test_deletar_estoque_emite_delete_de_lotes_antes_do_delete_do_produto --
    agora cobrindo a cascata manual completa: movimentação -> lote ->
    produto (não só lote -> produto)."""
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="crit1_ordem")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="CRIT1ORDEM001", qtd=5)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=date.today() + timedelta(days=5))
    with Session(engine) as s:
        registrar_movimentacao(s, produto.id, "ENTRADA_COMPRA", Decimal("5"), func.id)
        s.commit()

    eventos = []
    orig_exec = sqlmodel_mod.Session.exec
    orig_flush = sqlmodel_mod.Session.flush

    def espiar_exec(self, statement, *args, **kwargs):
        texto = str(statement).strip().lower()
        if texto.startswith("delete"):
            if "movimentacao_estoque" in texto:
                eventos.append(("delete_mov_query",))
            elif texto.startswith("delete from lote"):
                eventos.append(("delete_lote_query",))
        return orig_exec(self, statement, *args, **kwargs)

    def espiar_flush(self, *args, **kwargs):
        eventos.append(("flush",))
        return orig_flush(self, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    monkeypatch.setattr(sqlmodel_mod.Session, "flush", espiar_flush)

    deletar_estoque(produto.id)

    tipos = [e[0] for e in eventos]
    assert "delete_mov_query" in tipos, "esperava um DELETE explícito das movimentações do produto"
    assert "delete_lote_query" in tipos, "esperava um DELETE explícito dos lotes do produto"
    idx_mov = tipos.index("delete_mov_query")
    idx_lote = tipos.index("delete_lote_query")
    assert idx_mov < idx_lote, "movimentações precisam ser apagadas ANTES dos lotes (lote_id -> lote.id)"
    assert "flush" in tipos[idx_mov:idx_lote], (
        "esperava um flush entre o delete das movimentações e o delete dos lotes, "
        "senão a ordem final fica por conta do SQLAlchemy"
    )


def test_deletar_funcionario_com_movimentacao_vinculada_seta_funcionario_id_null(monkeypatch):
    """CRÍTICO 1b: deletar um funcionário que já registrou movimentação de
    estoque precisa continuar funcionando -- DECISÃO: ON DELETE SET NULL
    (preserva o histórico de auditoria, só anonimiza a autoria) em vez de
    apagar as movimentações ou bloquear o delete do funcionário."""
    eng = _engine_com_fk_habilitada(monkeypatch)
    with Session(eng) as s:
        setor = make_setor(s, tipo="crit1_del_func")
        # with_password=False: isola o teste para cobrir SÓ a FK de
        # movimentacao_estoque.funcionario_id (ON DELETE SET NULL) -- a outra
        # FK pré-existente e separada (historico_senha.funcionario_id, sem
        # ON DELETE) tem teste dedicado logo abaixo
        # (test_deletar_funcionario_com_historico_senha_nao_quebra), que usa
        # with_password=True de propósito para exercitá-la.
        func = make_funcionario(s, setor_id=setor.id, with_password=False)
        produto = make_produto(s, codigo="CRIT1DELFUNC001", qtd=10)
        mov = MovimentacaoEstoque(
            estoque_id=produto.id, lote_id=None, tipo="ENTRADA_COMPRA",
            quantidade=Decimal("10.000"), funcionario_id=func.id,
        )
        s.add(mov)
        s.commit()
        s.refresh(mov)
        func_id, mov_id = func.id, mov.id

    resultado = deletar_funcionario(func_id)
    assert "deletado" in resultado["msg"]

    with Session(eng) as s:
        assert s.get(Funcionario, func_id) is None
        mov_db = s.get(MovimentacaoEstoque, mov_id)
        assert mov_db is not None, "a movimentação não deveria ser apagada -- histórico de auditoria preservado"
        assert mov_db.funcionario_id is None, "ON DELETE SET NULL deveria anonimizar a autoria, não bloquear o delete"


def test_deletar_funcionario_com_historico_senha_nao_quebra(monkeypatch):
    """Bug PRÉ-EXISTENTE (de uma fase anterior a esta, não um achado da Fase
    4 em si) descoberto durante a correção dos achados do painel de revisão
    da Fase 4: `historico_senha.funcionario_id -> funcionario.id` nunca teve
    ON DELETE configurado -- deletar um funcionário que já tivesse QUALQUER
    linha em historico_senha (todo funcionário real que já trocou de senha
    alguma vez, seja pelo fluxo de troca obrigatória no primeiro acesso ou
    por recuperação de senha -- `make_funcionario(with_password=True)`, o
    default, já cria essa linha, igual `criar_funcionario` faz de verdade)
    quebrava com IntegrityError/500.

    DECISÃO (diferente do caso acima de movimentacao_estoque/SET NULL):
    historico_senha é só um mecanismo interno de bloqueio de reuso de senha,
    não um log de auditoria de negócio -- sem motivo para sobreviver à saída
    do funcionário. A correção apaga o histórico de senha do funcionário
    junto, no mesmo DELETE explícito que o teste acima teria pego se não
    tivesse usado with_password=False."""
    eng = _engine_com_fk_habilitada(monkeypatch)
    with Session(eng) as s:
        setor = make_setor(s, tipo="hist_senha_del_func")
        func = make_funcionario(s, setor_id=setor.id, with_password=True)
        func_id = func.id
        hist_antes = s.exec(
            select(HistoricoSenha).where(HistoricoSenha.funcionario_id == func_id)
        ).all()
    assert len(hist_antes) >= 1, "pré-condição do teste: funcionário precisa ter histórico de senha"

    resultado = deletar_funcionario(func_id)
    assert "deletado" in resultado["msg"]

    with Session(eng) as s:
        assert s.get(Funcionario, func_id) is None
        hist_depois = s.exec(
            select(HistoricoSenha).where(HistoricoSenha.funcionario_id == func_id)
        ).all()
        assert hist_depois == [], "histórico de senha deveria ser apagado junto com o funcionário"


# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANTE 1 (revisão do painel -- Fase 4) -- registrar_movimentacao (e o
# bloco que a acompanha) precisa estar DENTRO do try/except de deadlock
#
# registrar_movimentacao() chama session.flush() imediatamente, disparando o
# INSERT contra o banco. Em 3 de 4 pontos novos (criar_estoque/incremento,
# confirmar_pendente/os dois ramos, ajustar_inventario) essa chamada estava
# ANTES do bloco try/except OperationalError -- um deadlock durante esse
# flush especificamente escaparia do tratamento e viraria 500 cru. Os testes
# abaixo monkeypatcham Session.flush para falhar especificamente quando há
# uma MovimentacaoEstoque pendente (ou seja, bem na hora do flush de
# registrar_movimentacao, não em qualquer flush/autoflush anterior da
# função) -- diferente dos testes de deadlock já existentes (que
# monkeypatcham session.commit, e por isso não pegavam esta regressão
# específica).
# ═══════════════════════════════════════════════════════════════════════════

def _flush_falha_com_movimentacao_pendente(monkeypatch):
    import sqlmodel as sqlmodel_mod

    orig_flush = sqlmodel_mod.Session.flush

    def flush_que_falha(self, *args, **kwargs):
        if any(isinstance(obj, MovimentacaoEstoque) for obj in self.new):
            raise _deadlock_mysql()
        return orig_flush(self, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "flush", flush_que_falha)


def test_criar_estoque_incremento_deadlock_no_flush_de_movimentacao_vira_409(engine, session, monkeypatch):
    setor = make_setor(session, tipo="imp1_incr")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="IMP1INCR001", qtd=5)

    _flush_falha_com_movimentacao_pendente(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        criar_estoque(
            EstoqueCreate(nomedoproduto="Produto", quantidade=Decimal("3"),
                          preco=Decimal("10.00"), codigodebarras="IMP1INCR001", categoria="Geral"),
            func.id,
        )
    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_ajustar_inventario_deadlock_no_flush_de_movimentacao_vira_409(engine, session, monkeypatch):
    setor = make_setor(session, tipo="imp1_ajuste")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="IMP1AJUSTE001", qtd=10)

    _flush_falha_com_movimentacao_pendente(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        ajustar_inventario(
            produto.id, AjusteInventarioInput(nova_quantidade=Decimal("6"), motivo="Contagem física"), func.id,
        )
    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_confirmar_pendente_produto_existente_deadlock_no_flush_de_movimentacao_vira_409(engine, session, monkeypatch):
    setor = make_setor(session, tipo="imp1_pend")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="IMP1PEND001", qtd=5)
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "IMP1PEND001", "nomedoproduto": "Produto", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 3, "preco_custo": 5.0},
    ])
    item_id = listar_pendentes()[0]["id"]

    _flush_falha_com_movimentacao_pendente(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        confirmar_pendente(
            item_id,
            ConfirmarPendenteInput(nomedoproduto="Produto", codigodebarras="IMP1PEND001",
                                    preco_venda=10.0, categoria="Geral",
                                    codigo_lote="LOTE-IMP1PEND001", validade=date(2030, 1, 1)),
            func.id,
        )
    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()
