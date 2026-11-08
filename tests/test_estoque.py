import pytest
from fastapi import HTTPException
from unittest.mock import patch
from sqlmodel import Session

from repository.estoque import (
    criar_estoque, mostrar_produtos, buscar_estoque,
    atualizar_estoque, deletar_estoque,
)
from schemas.schemas import EstoqueCreate, EstoqueUpdate
from conftest import make_setor, make_funcionario, make_produto


def _dados_create(codigo="111", nome="Pao", qtd=10, preco=5.0, custo=2.0, cat="Padaria"):
    return EstoqueCreate(
        titulo=nome, nomedoproduto=nome,
        quantidade=qtd, preco=preco, preco_custo=custo,
        codigodebarras=codigo, categoria=cat,
    )


def _dados_update(codigo="111", nome="Pao Atualizado", qtd=20, preco=6.0, cat="Padaria"):
    return EstoqueUpdate(
        titulo=nome, nomedoproduto=nome,
        quantidade=qtd, preco=preco,
        codigodebarras=codigo, categoria=cat,
    )


# ── criar_estoque ─────────────────────────────────────────────────────────────

def test_criar_estoque_novo_produto(engine, session):
    setor = make_setor(session, tipo="est")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_create(codigo="BAR001")
    resultado = criar_estoque(dados, func.id)
    assert resultado.id is not None
    assert resultado.nomedoproduto == "Pao"
    assert resultado.quantidade == 10
    assert resultado.preco_custo == 2.0


def test_criar_estoque_sem_preco_custo_usa_default(engine, session):
    setor = make_setor(session, tipo="est2")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Item", quantidade=5, preco=3.0,
        codigodebarras="BAR002", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.preco_custo == 0.0


def test_criar_estoque_produto_existente_incrementa(engine, session):
    setor = make_setor(session, tipo="est3")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="BAR003", qtd=10)
    dados = _dados_create(codigo="BAR003", qtd=5)
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == 15


def test_criar_estoque_produto_existente_atualiza_funcionario(engine, session):
    setor = make_setor(session, tipo="est4")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="BAR004", qtd=10)
    dados = _dados_create(codigo="BAR004", qtd=1)
    resultado = criar_estoque(dados, func.id)
    assert resultado.funcionario_id == func.id


def test_criar_estoque_titulo_opcional(engine, session):
    setor = make_setor(session, tipo="est5")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Sem Titulo", quantidade=1, preco=1.0,
        codigodebarras="BAR005", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.titulo is None


def test_criar_estoque_erro_interno(engine, session):
    setor = make_setor(session, tipo="est6")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_create(codigo="BAR999")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            criar_estoque(dados, func.id)
        assert exc.value.status_code == 500


def test_criar_estoque_existente_erro_interno(engine, session):
    setor = make_setor(session, tipo="est7")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="BAR006", qtd=5)
    dados = _dados_create(codigo="BAR006", qtd=1)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            criar_estoque(dados, func.id)
        assert exc.value.status_code == 500


# ── mostrar_produtos ──────────────────────────────────────────────────────────

def test_mostrar_produtos_vazio(engine, session):
    assert mostrar_produtos() == []


def test_mostrar_produtos_multiplos(engine, session):
    make_produto(session, codigo="P001")
    make_produto(session, codigo="P002")
    make_produto(session, codigo="P003")
    assert len(mostrar_produtos()) == 3


# ── buscar_estoque ────────────────────────────────────────────────────────────

def test_buscar_estoque_encontrado(engine, session):
    p = make_produto(session, codigo="P010")
    resultado = buscar_estoque(p.id)
    assert resultado.id == p.id


def test_buscar_estoque_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_estoque(9999)
    assert exc.value.status_code == 404


# ── atualizar_estoque ─────────────────────────────────────────────────────────

def test_atualizar_estoque_sucesso(engine, session):
    setor = make_setor(session, tipo="upd_est")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="UPD001")
    dados = _dados_update(codigo="UPD001", nome="Produto Atualizado", qtd=99, preco=15.0)
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.nomedoproduto == "Produto Atualizado"
    assert resultado.quantidade == 99
    assert resultado.preco == 15.0


def test_atualizar_estoque_mesmo_codigo(engine, session):
    setor = make_setor(session, tipo="upd_est2")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="SAME001")
    dados = _dados_update(codigo="SAME001", nome="Mesmo Codigo", qtd=50, preco=8.0)
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.codigodebarras == "SAME001"


def test_atualizar_estoque_codigo_duplicado(engine, session):
    setor = make_setor(session, tipo="upd_est3")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="EXIST001")
    p2 = make_produto(session, codigo="OUTRO001")
    dados = _dados_update(codigo="EXIST001")
    with pytest.raises(HTTPException) as exc:
        atualizar_estoque(p2.id, dados, func.id)
    assert exc.value.status_code == 400
    assert "Código de barras" in exc.value.detail


def test_atualizar_estoque_inexistente(engine, session):
    setor = make_setor(session, tipo="upd_est4")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_update(codigo="NAO_EXISTE")
    with pytest.raises(HTTPException) as exc:
        atualizar_estoque(9999, dados, func.id)
    assert exc.value.status_code == 404


def test_atualizar_estoque_erro_interno(engine, session):
    setor = make_setor(session, tipo="upd_est5")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="ERR_UPD")
    dados = _dados_update(codigo="ERR_UPD")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            atualizar_estoque(p.id, dados, func.id)
        assert exc.value.status_code == 500


# ── deletar_estoque ───────────────────────────────────────────────────────────

def test_deletar_estoque_sucesso(engine, session):
    p = make_produto(session, codigo="DEL001")
    resultado = deletar_estoque(p.id)
    assert "deletado" in resultado["msg"]


def test_deletar_estoque_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        deletar_estoque(9999)
    assert exc.value.status_code == 404


def test_deletar_estoque_duas_vezes(engine, session):
    p = make_produto(session, codigo="DEL002")
    deletar_estoque(p.id)
    with pytest.raises(HTTPException) as exc:
        deletar_estoque(p.id)
    assert exc.value.status_code == 404


def test_deletar_estoque_erro_interno(engine, session):
    p = make_produto(session, codigo="DEL_ERR")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            deletar_estoque(p.id)
        assert exc.value.status_code == 500


# ── integridade de dados ──────────────────────────────────────────────────────

def test_criar_estoque_salva_categoria(engine, session):
    setor = make_setor(session, tipo="intg")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_create(codigo="CAT001", cat="Bebidas")
    resultado = criar_estoque(dados, func.id)
    assert resultado.categoria == "Bebidas"


def test_incremento_nao_substitui_preco(engine, session):
    setor = make_setor(session, tipo="intg2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="PRECO001", preco=10.0)
    dados = _dados_create(codigo="PRECO001", qtd=5, preco=20.0)
    resultado = criar_estoque(dados, func.id)
    assert resultado.preco == 10.0
