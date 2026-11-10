"""
Testes adicionais de integração e casos extremos do sistema.
"""
import pytest
from decimal import Decimal
from fastapi import HTTPException
from sqlmodel import Session, select

from repository.funcionarios import trocar_senha, criar_funcionario
from repository.estoque import criar_estoque, deletar_estoque
from repository.vendas import criar_venda
from schemas.schemas import (
    TrocarSenhaRequest, FuncionarioCreate, EstoqueCreate, VendaInput, ItemVendaSchema,
)
from utils.database import HistoricoSenha, Estoque
from conftest import make_setor, make_funcionario, make_produto
from datetime import date

ENDERECO = dict(
    cep="01310100", estado="SP", cidade="SP",
    bairro="Centro", rua="Paulista", numero="100",
)


# ── Casos extremos de senha ────────────────────────────────────────────────────

def test_historico_senha_registra_multiplas_trocas(engine, session):
    setor = make_setor(session, tipo="hist_ext")
    f = make_funcionario(session, setor_id=setor.id)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Segunda@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Segunda@999", nova_senha="Terceira@999"))
    with Session(engine) as s:
        historico = s.exec(
            select(HistoricoSenha).where(HistoricoSenha.funcionario_id == f.id)
        ).all()
    assert len(historico) == 3


def test_trocar_senha_senha_vazia_atual(engine, session):
    setor = make_setor(session, tipo="vazia_ext")
    f = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="", nova_senha="Nova@99999"))
    assert exc.value.status_code == 401


def test_trocar_senha_funcionario_sem_hash(engine, session):
    setor = make_setor(session, tipo="sem_hash")
    f = make_funcionario(session, setor_id=setor.id, with_password=False)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Nova@99999"))
    assert exc.value.status_code == 401


# ── Casos extremos de estoque ─────────────────────────────────────────────────

def test_criar_estoque_quantidade_zero(engine, session):
    setor = make_setor(session, tipo="qtd_zero")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Sem estoque", quantidade=0, preco=1.0,
        codigodebarras="ZERO001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == 0


def test_incremento_em_produto_com_zero_estoque(engine, session):
    setor = make_setor(session, tipo="incr_zero")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="INCR001", qtd=0)
    dados = EstoqueCreate(
        nomedoproduto="Produto", quantidade=10, preco=5.0,
        codigodebarras="INCR001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == 10


def test_venda_esgota_estoque_completamente(engine, session):
    setor = make_setor(session, tipo="esgot_ext")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="ESG001", qtd=3, preco=10.0)
    venda = criar_venda(
        VendaInput(itens=[ItemVendaSchema(codigodebarras="ESG001", quantidade=3)]),
        func.id,
    )
    assert venda.valor_total == 30.0
    with Session(engine) as s:
        p = s.exec(select(Estoque).where(Estoque.codigodebarras == "ESG001")).first()
    assert p.quantidade == 0


def test_venda_apos_esgotamento_falha(engine, session):
    setor = make_setor(session, tipo="esgot_ext2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="ESG002", qtd=1, preco=10.0)
    criar_venda(
        VendaInput(itens=[ItemVendaSchema(codigodebarras="ESG002", quantidade=1)]),
        func.id,
    )
    with pytest.raises(HTTPException) as exc:
        criar_venda(
            VendaInput(itens=[ItemVendaSchema(codigodebarras="ESG002", quantidade=1)]),
            func.id,
        )
    assert exc.value.status_code == 400


# ── Casos extremos de funcionario ─────────────────────────────────────────────

def test_criar_dois_funcionarios_cpf_diferentes(engine, session):
    setor = make_setor(session, tipo="dois_cpf")
    dados1 = FuncionarioCreate(
        nome="A", sobrenome="B", data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False, setor_id=setor.id,
        senha="Test@123", cpf="52998224725", email="a@test.com", **ENDERECO,
    )
    dados2 = FuncionarioCreate(
        nome="C", sobrenome="D", data_nascimento=date(1990, 1, 1),
        genero="F", possui_filhos=False, setor_id=setor.id,
        senha="Test@123", cpf="11144477735", email="b@test.com", **ENDERECO,
    )
    f1 = criar_funcionario(dados1)
    f2 = criar_funcionario(dados2)
    assert f1.cpf != f2.cpf


def test_historico_senha_separado_por_funcionario(engine, session):
    setor = make_setor(session, tipo="sep_hist")
    f1 = make_funcionario(session, setor_id=setor.id, cpf="52998224725")
    f2 = make_funcionario(session, setor_id=setor.id, cpf="11144477735")
    trocar_senha(f1.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaF1@999"))
    trocar_senha(f2.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaF2@999"))
    with Session(engine) as s:
        hist_f1 = s.exec(select(HistoricoSenha).where(HistoricoSenha.funcionario_id == f1.id)).all()
        hist_f2 = s.exec(select(HistoricoSenha).where(HistoricoSenha.funcionario_id == f2.id)).all()
    assert len(hist_f1) == 2
    assert len(hist_f2) == 2


def test_estoque_titulo_none_aceito(engine, session):
    setor = make_setor(session, tipo="titulo_none")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        titulo=None, nomedoproduto="Sem Titulo", quantidade=5, preco=1.0,
        codigodebarras="NT001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.titulo is None


def test_produto_preco_alto(engine, session):
    setor = make_setor(session, tipo="preco_alto")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Caro", quantidade=1, preco=999999.99,
        codigodebarras="CARO001", categoria="Premium",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.preco == Decimal("999999.99")


def test_venda_multiplos_produtos_decrementa_todos(engine, session):
    setor = make_setor(session, tipo="multi_dec")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="MD001", qtd=10, preco=5.0)
    make_produto(session, codigo="MD002", qtd=20, preco=3.0)
    make_produto(session, codigo="MD003", qtd=15, preco=2.0)
    criar_venda(
        VendaInput(itens=[
            ItemVendaSchema(codigodebarras="MD001", quantidade=3),
            ItemVendaSchema(codigodebarras="MD002", quantidade=5),
            ItemVendaSchema(codigodebarras="MD003", quantidade=7),
        ]),
        func.id,
    )
    with Session(engine) as s:
        p1 = s.exec(select(Estoque).where(Estoque.codigodebarras == "MD001")).first()
        p2 = s.exec(select(Estoque).where(Estoque.codigodebarras == "MD002")).first()
        p3 = s.exec(select(Estoque).where(Estoque.codigodebarras == "MD003")).first()
    assert p1.quantidade == 7
    assert p2.quantidade == 15
    assert p3.quantidade == 8
