"""Testes de lotes e validade (Fase 3): consumo FEFO na venda, invariante
soma(Lote.quantidade) == Estoque.quantidade, e tratamento de produto legado
sem nenhum lote cadastrado.

A confirmação de compra pendente ainda não informa lote/validade nesta
etapa (isso é tratado num commit seguinte) -- aqui ela se comporta como
qualquer outro incremento manual: cai no lote "sem validade".
"""

from datetime import date, timedelta, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select
from sqlalchemy.dialects import mysql

from repository.estoque import criar_estoque, atualizar_estoque, deletar_estoque, confirmar_pendente
from repository.vendas import criar_venda
from repository.lotes import ajustar_lote_sem_validade, consumir_fefo, CODIGO_LOTE_LEGADO
from schemas.schemas import EstoqueCreate, EstoqueUpdate, VendaInput, ItemVendaSchema, ConfirmarPendenteInput
from utils.database import Lote, Estoque
from conftest import make_setor, make_funcionario, make_produto, make_lote, make_compra, make_fornecedor


def _venda_input(codigo, quantidade):
    return VendaInput(itens=[ItemVendaSchema(codigodebarras=codigo, quantidade=quantidade)])


def _soma_lotes(session, estoque_id):
    lotes = session.exec(select(Lote).where(Lote.estoque_id == estoque_id)).all()
    return sum((l.quantidade for l in lotes), Decimal("0.000"))


# ── FEFO: venda consome o lote que vence mais cedo primeiro ────────────────

def test_criar_venda_consome_lote_que_vence_primeiro(engine, session):
    setor = make_setor(session, tipo="fefo1")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFO001", qtd=10, preco=5.0)
    lote_longe = make_lote(session, produto.id, codigo_lote="L-LONGE", qtd=4, validade=date.today() + timedelta(days=30))
    lote_perto = make_lote(session, produto.id, codigo_lote="L-PERTO", qtd=6, validade=date.today() + timedelta(days=5))

    criar_venda(_venda_input("FEFO001", 5), func.id)

    with Session(engine) as s:
        lote_perto_db = s.get(Lote, lote_perto.id)
        lote_longe_db = s.get(Lote, lote_longe.id)
        produto_db = s.get(Estoque, produto.id)

    # Lote que vence mais cedo (lote_perto) é consumido primeiro: 6 - 5 = 1.
    # Lote que vence mais tarde (lote_longe) não é tocado.
    assert lote_perto_db.quantidade == Decimal("1.000")
    assert lote_longe_db.quantidade == Decimal("4.000")
    assert produto_db.quantidade == Decimal("5.000")


def test_criar_venda_consome_multiplos_lotes_quando_um_sozinho_nao_basta(engine, session):
    """Venda de 5 unidades, nenhum lote isolado tem 5 (lotes de 3 e 4), mas
    a soma (7) cobre -- precisa baixar do primeiro e completar no segundo."""
    setor = make_setor(session, tipo="fefo2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFO002", qtd=7, preco=5.0)
    lote1 = make_lote(session, produto.id, codigo_lote="L1", qtd=3, validade=date.today() + timedelta(days=2))
    lote2 = make_lote(session, produto.id, codigo_lote="L2", qtd=4, validade=date.today() + timedelta(days=10))

    criar_venda(_venda_input("FEFO002", 5), func.id)

    with Session(engine) as s:
        lote1_db = s.get(Lote, lote1.id)
        lote2_db = s.get(Lote, lote2.id)
        produto_db = s.get(Estoque, produto.id)

    assert lote1_db.quantidade == Decimal("0.000")  # esgotado primeiro (vence antes)
    assert lote2_db.quantidade == Decimal("2.000")  # completa o restante (4 - 2)
    assert produto_db.quantidade == Decimal("2.000")


def test_consumir_fefo_lote_sem_validade_e_consumido_por_ultimo(engine, session):
    """Mesmo que o lote "sem validade" tenha entrado ANTES (data_entrada
    mais antiga), um lote com validade real definida é consumido primeiro --
    senão um produto perto de vencer de verdade ficaria "escondido atrás" de
    um lote legado de validade desconhecida (ver docstring do módulo)."""
    setor = make_setor(session, tipo="fefo3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFO003", qtd=10, preco=5.0)
    lote_legado = make_lote(
        session, produto.id, codigo_lote=CODIGO_LOTE_LEGADO, qtd=6, validade=None,
        data_entrada=datetime.now(timezone.utc) - timedelta(days=100),
    )
    lote_datado = make_lote(session, produto.id, codigo_lote="L-NOVO", qtd=4, validade=date.today() + timedelta(days=3))

    criar_venda(_venda_input("FEFO003", 4), func.id)

    with Session(engine) as s:
        lote_legado_db = s.get(Lote, lote_legado.id)
        lote_datado_db = s.get(Lote, lote_datado.id)

    assert lote_datado_db.quantidade == Decimal("0.000")  # consumido primeiro
    assert lote_legado_db.quantidade == Decimal("6.000")  # intocado


# ── produto legado sem nenhum lote cadastrado ───────────────────────────────

def test_criar_venda_produto_sem_nenhum_lote_materializa_lote_legado(engine, session):
    """Produto cadastrado antes desta fase (ou nunca tocado por ela) não
    tem nenhuma linha em `Lote` -- a venda não pode travar por causa disso:
    consumir_fefo materializa um lote "sem validade" cobrindo o saldo atual
    e consome dele normalmente."""
    setor = make_setor(session, tipo="fefo4")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFO004", qtd=8, preco=5.0)

    with Session(engine) as s:
        assert s.exec(select(Lote).where(Lote.estoque_id == produto.id)).all() == []

    criar_venda(_venda_input("FEFO004", 3), func.id)

    with Session(engine) as s:
        lotes = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).all()
        produto_db = s.get(Estoque, produto.id)

    assert len(lotes) == 1
    assert lotes[0].validade is None
    assert lotes[0].codigo_lote == CODIGO_LOTE_LEGADO
    assert lotes[0].quantidade == Decimal("5.000")  # 8 - 3
    assert produto_db.quantidade == Decimal("5.000")
    assert _soma_lotes(s, produto.id) == produto_db.quantidade


def test_consumir_fefo_estoque_insuficiente_levanta_400(engine, session):
    """Defesa em profundidade: se a soma dos lotes não bastar (só deveria
    acontecer numa divergência que não deveria existir em operação normal),
    consumir_fefo levanta 400 em vez de deixar lote negativo."""
    setor = make_setor(session, tipo="fefo5")
    make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFO005", qtd=3, preco=5.0)
    make_lote(session, produto.id, codigo_lote="L1", qtd=3, validade=date.today() + timedelta(days=5))

    with Session(engine) as s:
        with pytest.raises(HTTPException) as exc:
            consumir_fefo(s, produto.id, Decimal("10"), produto.nomedoproduto)
    assert exc.value.status_code == 400
    assert "insuficiente" in exc.value.detail


# ── trava de concorrência (with_for_update) ────────────────────────────────

def test_consumir_fefo_consulta_lotes_com_lock_for_update(engine, session, monkeypatch):
    """
    Mesma lógica de trava já validada em criar_venda/criar_estoque/
    confirmar_pendente (ver testes homônimos): a consulta que consumir_fefo
    faz aos lotes do produto também precisa pedir o lock pessimista, senão
    duas vendas concorrentes do mesmo produto poderiam decrementar o MESMO
    lote a partir do mesmo saldo "velho" (lost update nos lotes, mesmo que
    `Estoque.quantidade` continue protegido pela trava que já existia).

    SQLite não implementa `SELECT ... FOR UPDATE` -- mesma limitação
    documentada nos outros testes de lock desta suíte. Verifica-se aqui que
    a consulta pede o lock (SQL compilado para o dialeto do MySQL).
    """
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="fefo_lock")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="FEFOLOCK001", qtd=5, preco=5.0)
    make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=date.today() + timedelta(days=5))

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    criar_venda(_venda_input("FEFOLOCK001", 2), func.id)

    consultas_lote = [s for s in statements if "lote" in str(s).lower() and "estoque_id" in str(s).lower()]
    assert consultas_lote, "esperava que consumir_fefo consultasse os lotes do produto via session.exec"
    for stmt in consultas_lote:
        assert getattr(stmt, "_for_update_arg", None) is not None, (
            "a consulta aos lotes em consumir_fefo precisa usar with_for_update() "
            "para evitar lost update em vendas concorrentes"
        )
    compilada = str(consultas_lote[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada


# ── invariante: soma(Lote.quantidade) == Estoque.quantidade ────────────────

def test_invariante_soma_lotes_igual_estoque_apos_operacoes_mistas(engine, session):
    """
    Documenta e garante a invariante central desta fase: a soma de
    Lote.quantidade de um produto nunca diverge de Estoque.quantidade,
    mesmo passando por uma sequência de operações que "falam línguas"
    diferentes (lote/validade explícitos vs. ajuste manual sem lote) --
    cadastro com quantidade inicial, incremento manual via /estoque/inserir,
    edição direta via PUT /estoque/atualizar, confirmação de pendente
    (ainda sem lote nesta etapa) e venda com consumo FEFO.

    SQLite não reproduz concorrência real (ver outros testes de lock desta
    suíte) -- o que se verifica aqui, de forma honesta, é que a invariante
    se mantém META após cada operação sequencial, que é o que toda a lógica
    de repository/lotes.py foi desenhada para garantir.
    """
    setor = make_setor(session, tipo="invariante1")
    func = make_funcionario(session, setor_id=setor.id)

    # 1) Cadastro com quantidade inicial (sem lote/validade informados).
    criado = criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Invariante", quantidade=Decimal("20"),
                      preco=Decimal("10.00"), codigodebarras="INV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade

    # 2) Incremento manual via /estoque/inserir (mesmo código de barras).
    criar_estoque(
        EstoqueCreate(nomedoproduto="Produto Invariante", quantidade=Decimal("5"),
                      preco=Decimal("10.00"), codigodebarras="INV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade

    # 3) Edição direta via PUT /estoque/atualizar (reduz quantidade).
    atualizar_estoque(
        criado.id,
        EstoqueUpdate(nomedoproduto="Produto Invariante", quantidade=Decimal("18"),
                      unidade_medida="UN", estoque_minimo=Decimal("0"),
                      preco=Decimal("10.00"), codigodebarras="INV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade

    # 4) Edição direta via PUT /estoque/atualizar (aumenta quantidade).
    atualizar_estoque(
        criado.id,
        EstoqueUpdate(nomedoproduto="Produto Invariante", quantidade=Decimal("25"),
                      unidade_medida="UN", estoque_minimo=Decimal("0"),
                      preco=Decimal("10.00"), codigodebarras="INV001", categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade

    # 5) Confirmação de compra pendente (ainda sem lote nesta etapa -- cai
    # no lote "sem validade", igual ao incremento manual).
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "INV001", "nomedoproduto": "Produto Invariante", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 7, "preco_custo": 5.0},
    ])
    from repository.estoque import listar_pendentes
    item_id = listar_pendentes()[0]["id"]
    confirmar_pendente(
        item_id,
        ConfirmarPendenteInput(nomedoproduto="Produto Invariante", codigodebarras="INV001",
                                preco_venda=10.0, categoria="Geral"),
        func.id,
    )
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade

    # 6) Venda (consumo FEFO).
    criar_venda(_venda_input("INV001", 12), func.id)
    with Session(engine) as s:
        assert _soma_lotes(s, criado.id) == s.get(Estoque, criado.id).quantidade


def test_ajustar_lote_sem_validade_satura_em_zero_nao_fica_negativo(engine, session):
    setor = make_setor(session, tipo="invariante2")
    produto = make_produto(session, codigo="INV002", qtd=5, preco=5.0)
    with Session(engine) as s:
        ajustar_lote_sem_validade(s, produto.id, Decimal("5"))  # materializa lote = 5
        s.commit()
        ajustar_lote_sem_validade(s, produto.id, Decimal("-999"))  # delta maior que o saldo
        s.commit()
        lote = s.exec(select(Lote).where(Lote.estoque_id == produto.id)).first()
    assert lote.quantidade == Decimal("0.000")


# ── deletar produto com lotes não falha (FK lote.estoque_id -> estoque.id) ──

def test_deletar_estoque_com_lotes_remove_lotes_junto(engine, session):
    setor = make_setor(session, tipo="invariante3")
    produto = make_produto(session, codigo="DELLOTE001", qtd=5, preco=5.0)
    lote = make_lote(session, produto.id, codigo_lote="L1", qtd=5, validade=date.today() + timedelta(days=5))

    resultado = deletar_estoque(produto.id)
    assert resultado["msg"] == "Estoque deletado com sucesso"

    with Session(engine) as s:
        assert s.get(Estoque, produto.id) is None
        assert s.get(Lote, lote.id) is None
