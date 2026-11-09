import pytest
from decimal import Decimal
from pydantic import ValidationError
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


def _dados_update(codigo="111", nome="Pao Atualizado", preco=6.0, cat="Padaria",
                   unidade="UN", estoque_minimo=Decimal("0.000")):
    # Fase 4: EstoqueUpdate não tem mais `quantidade` (ver docstring do
    # schema) -- este helper nunca mudou quantidade de verdade desde então.
    return EstoqueUpdate(
        titulo=nome, nomedoproduto=nome,
        unidade_medida=unidade, estoque_minimo=estoque_minimo, preco=preco,
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
    p = make_produto(session, codigo="UPD001", qtd=50)
    dados = _dados_update(codigo="UPD001", nome="Produto Atualizado", preco=15.0)
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.nomedoproduto == "Produto Atualizado"
    assert resultado.preco == 15.0


def test_atualizar_estoque_nao_muda_quantidade(engine, session):
    """
    Fase 4: PUT /estoque/atualizar não mexe mais em quantidade (ver
    docstring de schemas.EstoqueUpdate) -- `EstoqueUpdate` nem tem mais
    esse campo. Alteração de saldo manual agora é sempre via
    `ajustar_inventario` (POST /estoque/{id}/ajustar-inventario).
    """
    setor = make_setor(session, tipo="upd_est_qtd")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="UPDQTD001", qtd=50)
    dados = _dados_update(codigo="UPDQTD001", nome="Produto Atualizado", preco=15.0)
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.quantidade == Decimal("50.000")


def test_atualizar_estoque_mesmo_codigo(engine, session):
    setor = make_setor(session, tipo="upd_est2")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="SAME001")
    dados = _dados_update(codigo="SAME001", nome="Mesmo Codigo", preco=8.0)
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


# ── unidade de medida (UN/KG/L) ────────────────────────────────────────────────

def test_criar_estoque_unidade_medida_padrao_un(engine, session):
    setor = make_setor(session, tipo="un_default")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_create(codigo="UN_DEFAULT001")
    resultado = criar_estoque(dados, func.id)
    assert resultado.unidade_medida == "UN"


def test_criar_estoque_unidade_medida_un(engine, session):
    setor = make_setor(session, tipo="un_un")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Caixa de Leite", quantidade=10, unidade_medida="UN",
        preco=5.0, codigodebarras="UNID001", categoria="Laticinios",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.unidade_medida == "UN"


def test_criar_estoque_unidade_medida_kg(engine, session):
    setor = make_setor(session, tipo="un_kg")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Carne Bovina", quantidade=20, unidade_medida="KG",
        preco=35.0, codigodebarras="UNID002", categoria="Acougue",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.unidade_medida == "KG"


def test_criar_estoque_unidade_medida_litro(engine, session):
    setor = make_setor(session, tipo="un_l")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Oleo de Soja a Granel", quantidade=50, unidade_medida="L",
        preco=8.0, codigodebarras="UNID003", categoria="Mercearia",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.unidade_medida == "L"


def test_criar_estoque_unidade_medida_invalida_rejeitada(engine, session):
    with pytest.raises(ValidationError):
        EstoqueCreate(
            nomedoproduto="Produto Invalido", quantidade=1, unidade_medida="KM",
            preco=1.0, codigodebarras="UNIDINV001", categoria="Geral",
        )


def test_atualizar_estoque_unidade_medida(engine, session):
    setor = make_setor(session, tipo="un_upd")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="UNIDUPD001", unidade="UN")
    dados = EstoqueUpdate(
        nomedoproduto="Produto Atualizado", unidade_medida="KG",
        estoque_minimo=Decimal("0.000"), preco=12.0, codigodebarras="UNIDUPD001", categoria="Geral",
    )
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.unidade_medida == "KG"


def test_criar_estoque_incremento_mantem_unidade_medida_original(engine, session):
    setor = make_setor(session, tipo="un_incr")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="UNIDINCR001", unidade="KG")
    dados = EstoqueCreate(
        nomedoproduto="Produto", quantidade=5, unidade_medida="UN",
        preco=10.0, codigodebarras="UNIDINCR001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.unidade_medida == "KG"


# ── quantidade decimal (venda por peso) ─────────────────────────────────────────

def test_criar_estoque_quantidade_decimal_kg(engine, session):
    setor = make_setor(session, tipo="qtd_kg")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Queijo Minas", quantidade=Decimal("12.750"), unidade_medida="KG",
        preco=45.0, codigodebarras="QTDKG001", categoria="Laticinios",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == Decimal("12.750")


def test_criar_estoque_quantidade_decimal_litro(engine, session):
    setor = make_setor(session, tipo="qtd_l")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Leite a Granel", quantidade=Decimal("0.500"), unidade_medida="L",
        preco=4.5, codigodebarras="QTDL001", categoria="Laticinios",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == Decimal("0.500")


def test_criar_estoque_quantidade_com_mais_de_tres_casas_rejeitada(engine, session):
    with pytest.raises(ValidationError):
        EstoqueCreate(
            nomedoproduto="Produto Invalido", quantidade=Decimal("1.2345"), unidade_medida="KG",
            preco=1.0, codigodebarras="QTDINV001", categoria="Geral",
        )


def test_criar_estoque_incremento_quantidade_decimal(engine, session):
    setor = make_setor(session, tipo="qtd_incr")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="QTDINCR001", qtd=Decimal("10.000"), unidade="KG")
    dados = EstoqueCreate(
        nomedoproduto="Produto", quantidade=Decimal("0.350"), unidade_medida="KG",
        preco=10.0, codigodebarras="QTDINCR001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == Decimal("10.350")


# ── estoque mínimo ───────────────────────────────────────────────────────────────

def test_criar_estoque_minimo_padrao_zero(engine, session):
    setor = make_setor(session, tipo="min_default")
    func = make_funcionario(session, setor_id=setor.id)
    dados = _dados_create(codigo="MIN_DEFAULT001")
    resultado = criar_estoque(dados, func.id)
    assert resultado.estoque_minimo == Decimal("0.000")


def test_criar_estoque_minimo_definido(engine, session):
    setor = make_setor(session, tipo="min_def")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto", quantidade=100, estoque_minimo=Decimal("15.000"),
        preco=5.0, codigodebarras="MINDEF001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.estoque_minimo == Decimal("15.000")


def test_atualizar_estoque_minimo(engine, session):
    setor = make_setor(session, tipo="min_upd")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="MINUPD001")
    dados = EstoqueUpdate(
        nomedoproduto="Produto Atualizado", unidade_medida="UN",
        estoque_minimo=Decimal("3.000"), preco=12.0, codigodebarras="MINUPD001", categoria="Geral",
    )
    resultado = atualizar_estoque(p.id, dados, func.id)
    assert resultado.estoque_minimo == Decimal("3.000")


def test_criar_estoque_minimo_negativo_rejeitado(engine, session):
    with pytest.raises(ValidationError):
        EstoqueCreate(
            nomedoproduto="Produto", quantidade=1, estoque_minimo=Decimal("-1.000"),
            preco=1.0, codigodebarras="MINNEG001", categoria="Geral",
        )


def test_estoque_minimo_respeitado_em_relacao_a_quantidade(engine, session):
    """
    O endpoint de reposição automática (que agiria quando quantidade <=
    estoque_minimo) é de uma fase futura -- aqui só garantimos que o campo
    existe, é persistido corretamente e dá pra comparar os dois valores,
    que é o que o cadastro de produto completo precisa entregar nesta fase.
    """
    setor = make_setor(session, tipo="min_resp")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto Critico", quantidade=Decimal("2.000"), estoque_minimo=Decimal("5.000"),
        preco=10.0, codigodebarras="MINRESP001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade <= resultado.estoque_minimo


# ── quantidade inteira obrigatória para produto UN ──────────────────────────────
# A validação "produto UN só aceita quantidade inteira" existia só no
# frontend (Number.isInteger em app.js) -- confirmado (painel de revisão da
# Fase 2) que POST /estoque/inserir aceitava fração direto contra a API para
# produto UN, tanto no cadastro de produto novo quanto no incremento de
# produto já existente. Teste direto no repository, sem passar pelo frontend.

def test_criar_estoque_novo_produto_un_rejeita_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac_novo")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto Fracionado", quantidade=Decimal("1.500"), unidade_medida="UN",
        preco=5.0, codigodebarras="UNFRACNOVO001", categoria="Geral",
    )
    with pytest.raises(HTTPException) as exc:
        criar_estoque(dados, func.id)
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_criar_estoque_incremento_un_rejeita_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac_incr")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="UNFRACINCR001", qtd=10, unidade="UN")
    dados = _dados_create(codigo="UNFRACINCR001", qtd=Decimal("1.500"))
    with pytest.raises(HTTPException) as exc:
        criar_estoque(dados, func.id)
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_atualizar_estoque_un_rejeita_quando_quantidade_atual_e_fracionaria(engine, session):
    """
    Fase 4: `quantidade` saiu de EstoqueUpdate -- PUT não recebe mais
    quantidade no payload (ver docstring do schema). A validação "produto
    UN só aceita quantidade inteira" passa a ser feita contra a quantidade
    JÁ EXISTENTE do produto: um PUT que tente trocar a unidade de medida
    para UN de um produto que hoje tem saldo fracionário (ex.: 1.5 kg)
    precisa continuar sendo rejeitado.
    """
    setor = make_setor(session, tipo="un_frac_upd")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="UNFRACUPD001", unidade="KG", qtd=Decimal("1.500"))
    dados = EstoqueUpdate(
        nomedoproduto="Produto", unidade_medida="UN",
        estoque_minimo=Decimal("0.000"), preco=10.0, codigodebarras="UNFRACUPD001", categoria="Geral",
    )
    with pytest.raises(HTTPException) as exc:
        atualizar_estoque(p.id, dados, func.id)
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_criar_estoque_kg_continua_aceitando_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac_kg")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto KG", quantidade=Decimal("1.500"), unidade_medida="KG",
        preco=5.0, codigodebarras="UNFRACKG001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == Decimal("1.500")


def test_rota_inserir_un_rejeita_quantidade_fracionaria(client, session, engine):
    """
    Confirmação direta na API (não só no repository): POST /estoque/inserir
    para um produto UN com quantidade fracionária precisa devolver 400 --
    era exatamente este o caminho batido contra a API real (sem passar pelo
    frontend) que o painel de revisão usou para confirmar o bug.
    """
    from conftest import set_token

    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post("/estoque/inserir", json={
        "nomedoproduto": "Produto Rota", "unidade_medida": "UN",
        "quantidade": 1.5, "preco": 5.0, "codigodebarras": "ROTAUNFRAC001", "categoria": "Geral",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert "unidade inteira" in r.json()["detail"]


def test_criar_estoque_incremento_kg_continua_aceitando_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac_kg_incr")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="UNFRACKGINCR001", qtd=Decimal("10.000"), unidade="KG")
    dados = EstoqueCreate(
        nomedoproduto="Produto KG", quantidade=Decimal("1.500"), unidade_medida="KG",
        preco=5.0, codigodebarras="UNFRACKGINCR001", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.quantidade == Decimal("11.500")


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


# ── tratamento de deadlock (IMPORTANTE da revisão da Fase 3) ────────────────────

def _deadlock_mysql():
    from sqlalchemy.exc import OperationalError

    class FakeOrigDeadlock(Exception):
        args = (1213, "Deadlock found when trying to get lock; try restarting transaction")

    return OperationalError("COMMIT", {}, FakeOrigDeadlock())


def test_criar_estoque_incremento_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    """
    IMPORTANTE (revisão da Fase 3): nenhum dos 3 pontos de escrita que
    passaram a usar with_for_update() nesta fase (criar_estoque,
    atualizar_estoque, confirmar_pendente) capturava o deadlock do MySQL
    (OperationalError 1213) como repository/vendas.py já fazia -- o erro
    subia cru como um 500. Reaproveita o mesmo tratamento (agora extraído
    para utils/erros_banco.py) no caminho de incremento de criar_estoque.
    """
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="deadlockest1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="DLEST001", qtd=5)

    def commit_que_falha(self, *args, **kwargs):
        raise _deadlock_mysql()

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha)

    with pytest.raises(HTTPException) as exc:
        criar_estoque(_dados_create(codigo="DLEST001", qtd=1), func.id)

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_criar_estoque_novo_produto_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    """Mesmo tratamento no caminho de cadastro de produto NOVO de
    criar_estoque (ramo que não encontra produto_existente)."""
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="deadlockest2")
    func = make_funcionario(session, setor_id=setor.id)

    def commit_que_falha(self, *args, **kwargs):
        raise _deadlock_mysql()

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha)

    with pytest.raises(HTTPException) as exc:
        criar_estoque(_dados_create(codigo="DLEST002", qtd=1), func.id)

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_atualizar_estoque_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    """Mesmo tratamento em atualizar_estoque (PUT)."""
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="deadlockest3")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="DLEST003", qtd=5)

    def commit_que_falha(self, *args, **kwargs):
        raise _deadlock_mysql()

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha)

    with pytest.raises(HTTPException) as exc:
        atualizar_estoque(produto.id, _dados_update(codigo="DLEST003"), func.id)

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()


def test_atualizar_estoque_outro_operational_error_nao_vira_409(engine, session, monkeypatch):
    """
    O tratamento é específico do código de erro 1213 do MySQL -- outro
    OperationalError qualquer (ex.: perda de conexão) continua propagando
    em vez de ser mascarado como "tente novamente" (mesma regra já
    validada em repository/vendas.py, agora centralizada em
    utils/erros_banco.py e reaproveitada aqui).
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="deadlockest4")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="DLEST004", qtd=5)

    class FakeOrigOutroErro(Exception):
        args = (2006, "MySQL server has gone away")

    def commit_que_falha_outro_erro(self, *args, **kwargs):
        raise OperationalError("COMMIT", {}, FakeOrigOutroErro())

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha_outro_erro)

    with pytest.raises(OperationalError):
        atualizar_estoque(produto.id, _dados_update(codigo="DLEST004"), func.id)


def test_atualizar_estoque_consulta_produto_com_lock_for_update(engine, session, monkeypatch):
    """
    CRÍTICO 2 (revisão da Fase 3): diferente de criar_estoque/
    confirmar_pendente/criar_venda (todos já testados acima/em
    test_vendas.py), atualizar_estoque() lia o produto com `session.get()`
    puro, sem `with_for_update()` -- um lost update pré-existente que
    passou a alimentar direto reconciliar_lote_sem_validade, amplificando
    para uma divergência PERMANENTE também em Lote.quantidade sob
    concorrência real (confirmado: 15/15 rodadas de PUT concorrente real
    contra MySQL quebraram a invariante soma(Lote.quantidade) ==
    Estoque.quantidade, sem nenhuma exceção reportada).

    SQLite não implementa `SELECT ... FOR UPDATE` -- mesma limitação já
    documentada no teste de criar_estoque acima. Verifica-se aqui que a
    PRIMEIRA consulta que atualizar_estoque faz ao produto pede o lock
    pessimista, compilando a instrução para o dialeto do MySQL.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lockest2")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="LOCKEST002", qtd=10)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    dados = _dados_update(codigo="LOCKEST002")
    atualizar_estoque(produto.id, dados, func.id)

    assert statements, "esperava que atualizar_estoque consultasse o produto via session.exec"
    assert getattr(statements[0], "_for_update_arg", None) is not None, (
        "a consulta ao produto em atualizar_estoque precisa usar "
        "with_for_update() para evitar lost update em edições concorrentes"
    )
    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada
