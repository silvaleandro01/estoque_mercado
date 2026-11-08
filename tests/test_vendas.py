import pytest
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from fastapi import HTTPException
from unittest.mock import patch
from sqlmodel import Session, select

from repository.vendas import criar_venda, vendas_do_dia, listar_vendas
from schemas.schemas import VendaInput, ItemVendaSchema
from utils.database import Venda, ItemVenda
from conftest import make_setor, make_funcionario, make_produto


def _input(itens):
    return VendaInput(itens=[ItemVendaSchema(codigodebarras=c, quantidade=q) for c, q in itens])


# ── criar_venda ───────────────────────────────────────────────────────────────

def test_criar_venda_sucesso_simples(engine, session):
    setor = make_setor(session, tipo="vnd")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="BAR001", qtd=50, preco=10.0)
    venda = criar_venda(_input([("BAR001", 3)]), func.id)
    assert venda.id is not None
    assert venda.valor_total == 30.0
    assert venda.funcionario_id == func.id


def test_criar_venda_multiplos_itens(engine, session):
    setor = make_setor(session, tipo="vnd2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="A001", qtd=10, preco=5.0)
    make_produto(session, codigo="B001", qtd=10, preco=3.0)
    venda = criar_venda(_input([("A001", 2), ("B001", 4)]), func.id)
    assert venda.valor_total == round(5.0 * 2 + 3.0 * 4, 2)


def test_criar_venda_decrementa_estoque(engine, session):
    setor = make_setor(session, tipo="vnd3")
    func = make_funcionario(session, setor_id=setor.id)
    p = make_produto(session, codigo="C001", qtd=20, preco=10.0)
    criar_venda(_input([("C001", 7)]), func.id)
    with Session(engine) as s:
        produto = s.get(type(p), p.id)
    assert produto.quantidade == 13


def test_criar_venda_produto_nao_encontrado(engine, session):
    setor = make_setor(session, tipo="vnd4")
    func = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        criar_venda(_input([("INEXISTENTE", 1)]), func.id)
    assert exc.value.status_code == 404


def test_criar_venda_estoque_insuficiente(engine, session):
    setor = make_setor(session, tipo="vnd5")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="D001", qtd=2, preco=10.0)
    with pytest.raises(HTTPException) as exc:
        criar_venda(_input([("D001", 10)]), func.id)
    assert exc.value.status_code == 400
    assert "insuficiente" in exc.value.detail


def test_criar_venda_estoque_exatamente_suficiente(engine, session):
    setor = make_setor(session, tipo="vnd6")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="E001", qtd=5, preco=10.0)
    venda = criar_venda(_input([("E001", 5)]), func.id)
    assert venda.valor_total == 50.0


def test_criar_venda_estoque_zerado_invalido(engine, session):
    setor = make_setor(session, tipo="vnd7")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="F001", qtd=0, preco=10.0)
    with pytest.raises(HTTPException) as exc:
        criar_venda(_input([("F001", 1)]), func.id)
    assert exc.value.status_code == 400


def test_criar_venda_nao_cria_venda_orfao_se_produto_invalido(engine, session):
    setor = make_setor(session, tipo="vnd8")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="G001", qtd=5, preco=10.0)
    try:
        criar_venda(_input([("G001", 1), ("INEXISTENTE", 1)]), func.id)
    except HTTPException:
        pass
    with Session(engine) as s:
        vendas = s.exec(select(Venda)).all()
    assert len(vendas) == 0


def test_criar_venda_valor_arredondado(engine, session):
    # O preço do produto já é um Decimal(10,2) desde o cadastro (ROUND_HALF_UP):
    # 1.005 vira 1.01 na criação do produto, então a venda de 2 unidades soma
    # exatamente 2.02 (1.01 * 2), sem nenhuma imprecisão de ponto flutuante.
    setor = make_setor(session, tipo="vnd9")
    func = make_funcionario(session, setor_id=setor.id)
    produto = make_produto(session, codigo="H001", qtd=10, preco=1.005)
    assert produto.preco == Decimal("1.01")
    venda = criar_venda(_input([("H001", 2)]), func.id)
    assert venda.valor_total == Decimal("2.02")


# ── trava de concorrência (with_for_update) ────────────────────────────────────

def test_criar_venda_consulta_produto_com_lock_for_update(engine, session, monkeypatch):
    """
    Duas vendas concorrentes do último item em estoque só não deixam o
    estoque negativo (ou vendem mais do que existe) porque a consulta ao
    produto trava a linha (`with_for_update()`) até o fim da transação --
    em produção (MySQL/InnoDB) isso faz a segunda venda esperar a primeira
    confirmar, e então reler o saldo já atualizado antes de decidir se há
    estoque suficiente.

    SQLite não implementa `SELECT ... FOR UPDATE` (a cláusula é apenas
    ignorada pelo driver), então não dá para reproduzir o bloqueio real do
    banco usado em produção dentro da suíte de testes. Em vez de simular um
    lock que o SQLite não tem como garantir, este teste verifica o contrato
    que realmente importa: a consulta que `criar_venda` executa pede o lock
    pessimista. Isso é verificado compilando a própria instrução para o
    dialeto do MySQL (o banco de produção) e conferindo que o `FOR UPDATE`
    aparece no SQL gerado -- se alguém remover o `.with_for_update()` do
    código, este teste quebra.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lock1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="LOCK001", qtd=5, preco=10.0)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    criar_venda(_input([("LOCK001", 1)]), func.id)

    assert statements, "esperava que criar_venda consultasse o produto via session.exec"

    for statement in statements:
        assert getattr(statement, "_for_update_arg", None) is not None, (
            "a consulta ao produto em criar_venda precisa usar with_for_update() "
            "para travar a linha e evitar estoque negativo em vendas concorrentes"
        )

    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada


def test_criar_venda_ordena_itens_por_codigodebarras_antes_do_lock(engine, session, monkeypatch):
    """
    Numa venda com múltiplos itens, `criar_venda` trava um produto por vez
    (`with_for_update()`) na ordem em que percorre `dados.itens`. Se essa
    ordem for a ordem literal em que o carrinho chegou no payload, duas
    vendas concorrentes com os MESMOS produtos em ordem invertida (venda A
    trava X e depois Y; venda B trava Y e depois X) ficam cada uma
    segurando o lock que a outra está esperando -- um deadlock clássico do
    MySQL/InnoDB (reproduzido com 53% de falha, HTTP 500 cru, em teste de
    carga real com vendas concorrentes).

    A correção ordena os itens por `codigodebarras` (chave estável e
    determinística) ANTES do loop que trava os produtos, garantindo que
    toda venda adquira os locks sempre na mesma ordem, não importa a ordem
    em que o cliente mandou no carrinho.

    Esse deadlock só se manifesta entre transações de verdade competindo
    pelo mesmo lock (SQLite não implementa bloqueio de linha com FOR
    UPDATE, então não há como reproduzir o deadlock em si dentro da suíte).
    O que dá para verificar aqui, e é o que realmente previne o problema, é
    que as consultas que travam os produtos saem em ordem alfabética de
    `codigodebarras` mesmo quando o payload chega em ordem invertida.
    """
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="ordem1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="Z999", qtd=5, preco=10.0)
    make_produto(session, codigo="A001", qtd=5, preco=10.0)

    codigos_consultados = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        if "estoque" in sql.lower() and "codigodebarras" in sql.lower():
            if "'Z999'" in sql:
                codigos_consultados.append("Z999")
            elif "'A001'" in sql:
                codigos_consultados.append("A001")
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)

    # Payload em ordem invertida (Z antes de A) -- os locks precisam sair
    # em ordem alfabética mesmo assim.
    criar_venda(_input([("Z999", 1), ("A001", 1)]), func.id)

    assert codigos_consultados == ["A001", "Z999"], (
        "criar_venda precisa ordenar dados.itens por codigodebarras antes "
        "do loop que trava os produtos (with_for_update()), para toda "
        "venda adquirir os locks sempre na mesma ordem -- isso é o que "
        "evita deadlock em vendas concorrentes com os mesmos produtos em "
        "ordem invertida"
    )


# ── trava de concorrência (deadlock) ────────────────────────────────────────────

def test_criar_venda_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    """
    Mesmo com a ordenação eliminando o deadlock entre vendas concorrentes,
    uma transação ainda pode colidir com outra parte do sistema que trave
    os mesmos produtos em ordem diferente (defesa em profundidade). Nesse
    caso o MySQL recusa a transação com OperationalError (código 1213,
    "Deadlock found when trying to get lock; try restarting transaction").
    Sem tratamento, isso vazava como um 500 cru pro cliente. Agora
    `criar_venda` captura especificamente esse erro e devolve um 409
    limpo, com uma mensagem que convida a tentar de novo.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="deadlock1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="DL001", qtd=5, preco=10.0)

    class FakeOrigDeadlock(Exception):
        args = (1213, "Deadlock found when trying to get lock; try restarting transaction")

    orig_commit = sqlmodel_mod.Session.commit
    chamadas = {"n": 0}

    def commit_que_falha_com_deadlock(self, *args, **kwargs):
        chamadas["n"] += 1
        raise OperationalError("COMMIT", {}, FakeOrigDeadlock())

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha_com_deadlock)

    with pytest.raises(HTTPException) as exc:
        criar_venda(_input([("DL001", 1)]), func.id)

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()
    assert chamadas["n"] == 1


def test_criar_venda_outro_operational_error_nao_vira_409(engine, session, monkeypatch):
    """
    O tratamento de deadlock é específico do código de erro 1213 do MySQL.
    Outro OperationalError qualquer (ex.: perda de conexão) não deve ser
    mascarado como "tente novamente" -- precisa continuar propagando para
    não esconder um problema de infraestrutura real por trás de uma
    mensagem de concorrência.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="deadlock2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="DL002", qtd=5, preco=10.0)

    class FakeOrigOutroErro(Exception):
        args = (2006, "MySQL server has gone away")

    def commit_que_falha_outro_erro(self, *args, **kwargs):
        raise OperationalError("COMMIT", {}, FakeOrigOutroErro())

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha_outro_erro)

    with pytest.raises(OperationalError):
        criar_venda(_input([("DL002", 1)]), func.id)


# ── vendas_do_dia ─────────────────────────────────────────────────────────────

def test_vendas_do_dia_sem_vendas(engine, session):
    resultado = vendas_do_dia()
    assert resultado["total_vendido"] == 0.0


def test_vendas_do_dia_com_venda(engine, session):
    setor = make_setor(session, tipo="dia")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="VD001", qtd=10, preco=20.0)
    criar_venda(_input([("VD001", 2)]), func.id)
    resultado = vendas_do_dia()
    assert resultado["total_vendido"] == 40.0


def test_vendas_do_dia_nao_conta_ontem(engine, session):
    setor = make_setor(session, tipo="dia2")
    func = make_funcionario(session, setor_id=setor.id)
    venda_ontem = Venda(
        funcionario_id=func.id,
        valor_total=100.0,
        data=datetime.now(timezone.utc) - timedelta(days=1),
    )
    session.add(venda_ontem)
    session.commit()
    resultado = vendas_do_dia()
    assert resultado["total_vendido"] == 0.0


def test_vendas_do_dia_soma_multiplas(engine, session):
    setor = make_setor(session, tipo="dia3")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="VD002", qtd=20, preco=10.0)
    criar_venda(_input([("VD002", 1)]), func.id)
    criar_venda(_input([("VD002", 2)]), func.id)
    resultado = vendas_do_dia()
    assert resultado["total_vendido"] == 30.0


def test_vendas_do_dia_retorna_data(engine, session):
    from datetime import date
    resultado = vendas_do_dia()
    assert isinstance(resultado["data"], date)


def test_vendas_do_dia_usa_fuso_brasil_nao_utc(engine, session, monkeypatch):
    """
    Brasília é UTC-3 (sem horário de verão desde 2019). Então das ~21h às
    23h59 em Brasília já é "amanhã" em UTC. O código antigo calculava "hoje"
    com `datetime.now(timezone.utc).date()`, então nesse intervalo o corte
    do dia virava cedo demais: vendas feitas de manhã/tarde do mesmo dia
    civil brasileiro ficavam de fora, e a venda feita à noite (hoje, para o
    lojista) era contada isoladamente como se fosse de amanhã.
    """
    import utils.timezone as tz_mod

    # 21h30 em Brasília do dia 15/06/2026 == 00h30 UTC do dia 16/06/2026.
    agora_utc = datetime(2026, 6, 16, 0, 30, tzinfo=timezone.utc)

    class DataHoraFixa(datetime):
        @classmethod
        def now(cls, tz=None):
            return agora_utc if tz is None else agora_utc.astimezone(tz)

    monkeypatch.setattr(tz_mod, "datetime", DataHoraFixa)

    setor = make_setor(session, tipo="fuso1")
    func = make_funcionario(session, setor_id=setor.id)

    # Venda de manhã do MESMO dia civil brasileiro: 10h BRT == 13h UTC (15/06).
    venda_manha = Venda(
        funcionario_id=func.id, valor_total=Decimal("15.00"),
        data=datetime(2026, 6, 15, 13, 0, tzinfo=timezone.utc),
    )
    # Venda feita "agora" à noite: 21h30 BRT == 00h30 UTC do dia seguinte.
    venda_noite = Venda(
        funcionario_id=func.id, valor_total=Decimal("20.00"),
        data=agora_utc,
    )
    # Venda do dia civil ANTERIOR (14/06, 20h BRT == 23h UTC) não deve contar.
    venda_ontem = Venda(
        funcionario_id=func.id, valor_total=Decimal("999.00"),
        data=datetime(2026, 6, 14, 23, 0, tzinfo=timezone.utc),
    )
    session.add_all([venda_manha, venda_noite, venda_ontem])
    session.commit()

    resultado = vendas_do_dia()

    assert resultado["data"] == date(2026, 6, 15)
    assert resultado["total_vendido"] == Decimal("35.00")


# ── listar_vendas ─────────────────────────────────────────────────────────────

def test_listar_vendas_vazio(engine, session):
    assert listar_vendas() == []


def test_listar_vendas_retorna_todas(engine, session):
    setor = make_setor(session, tipo="lst_vnd")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="LV001", qtd=10, preco=5.0)
    criar_venda(_input([("LV001", 1)]), func.id)
    criar_venda(_input([("LV001", 2)]), func.id)
    assert len(listar_vendas()) == 2


# ── integridade dos itens ─────────────────────────────────────────────────────

def test_criar_venda_cria_itens_venda(engine, session):
    setor = make_setor(session, tipo="itens")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="IV001", qtd=10, preco=7.5)
    venda = criar_venda(_input([("IV001", 3)]), func.id)
    with Session(engine) as s:
        itens = s.exec(select(ItemVenda).where(ItemVenda.venda_id == venda.id)).all()
    assert len(itens) == 1
    assert itens[0].quantidade == 3
    assert itens[0].preco_unitario == 7.5
    assert itens[0].preco_total == 22.5


# ── venda por peso (quantidade decimal) ─────────────────────────────────────────

def test_criar_venda_por_peso_quantidade_decimal(engine, session):
    setor = make_setor(session, tipo="peso1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="PESO001", qtd=Decimal("10.000"), preco=20.0, unidade="KG")

    venda = criar_venda(_input([("PESO001", Decimal("0.350"))]), func.id)

    assert venda.valor_total == Decimal("7.00")  # 20.00 * 0.350

    from utils.database import Estoque
    with Session(engine) as s:
        produto = s.exec(select(Estoque).where(Estoque.codigodebarras == "PESO001")).first()
    assert produto.quantidade == Decimal("9.650")


def test_criar_venda_por_peso_item_registra_quantidade_fracionada(engine, session):
    setor = make_setor(session, tipo="peso2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="PESO002", qtd=Decimal("5.000"), preco=10.0, unidade="KG")

    venda = criar_venda(_input([("PESO002", Decimal("1.250"))]), func.id)

    with Session(engine) as s:
        itens = s.exec(select(ItemVenda).where(ItemVenda.venda_id == venda.id)).all()
    assert itens[0].quantidade == Decimal("1.250")
    assert itens[0].preco_total == Decimal("12.50")


# ── quantidade inteira obrigatória para produto UN ──────────────────────────────
# A validação "produto UN só aceita quantidade inteira" existia só no
# frontend (Number.isInteger em app.js) -- confirmado (painel de revisão da
# Fase 2) que POST /vendas/inserir aceitava fração direto contra a API para
# produto UN. Teste direto no repository, sem passar pelo frontend.

def test_criar_venda_produto_un_rejeita_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac1")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="UNFRAC001", qtd=10, preco=5.0, unidade="UN")
    with pytest.raises(HTTPException) as exc:
        criar_venda(_input([("UNFRAC001", Decimal("1.5"))]), func.id)
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_criar_venda_produto_kg_continua_aceitando_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="un_frac2")
    func = make_funcionario(session, setor_id=setor.id)
    make_produto(session, codigo="UNFRAC002", qtd=Decimal("10.000"), preco=5.0, unidade="KG")
    venda = criar_venda(_input([("UNFRAC002", Decimal("1.5"))]), func.id)
    assert venda.valor_total == Decimal("7.50")
