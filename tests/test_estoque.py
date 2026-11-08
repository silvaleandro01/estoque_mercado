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


# ── trava de concorrência (with_for_update) ────────────────────────────────────

def test_criar_estoque_incremento_consulta_produto_com_lock_for_update(engine, session, monkeypatch):
    """
    Ao incrementar `Estoque.quantidade` de um produto já existente,
    criar_estoque() precisa travar a linha (`with_for_update()`), do
    mesmo jeito que repository/vendas.py já faz na venda. Sem a trava,
    duas entradas de estoque simultâneas para o mesmo produto (ex.: dois
    lançamentos manuais concorrentes) podem ler a mesma `quantidade`
    "antiga" e uma sobrescrever o incremento da outra ao salvar (lost
    update).

    SQLite não implementa `SELECT ... FOR UPDATE` (a cláusula é ignorada
    pelo driver), então -- mesma limitação já documentada em
    test_criar_venda_consulta_produto_com_lock_for_update -- não dá para
    reproduzir o bloqueio real do MySQL dentro da suíte. O teste verifica
    o contrato que importa: a consulta ao produto existente pede o lock
    pessimista, conferido compilando a instrução para o dialeto do MySQL.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lockest1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="LOCKEST001", qtd=10)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    dados = _dados_create(codigo="LOCKEST001", qtd=5)
    criar_estoque(dados, func.id)

    assert statements, "esperava que criar_estoque consultasse o produto existente via session.exec"
    assert getattr(statements[0], "_for_update_arg", None) is not None, (
        "a consulta ao produto existente em criar_estoque precisa usar "
        "with_for_update() para evitar lost update em entradas de estoque "
        "concorrentes"
    )
    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada
