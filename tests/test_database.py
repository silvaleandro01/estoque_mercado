import pytest
from datetime import date, datetime, timezone
from sqlmodel import Session, select

from utils.database import (
    Setor, Funcionario, HistoricoSenha, Estoque, Venda, ItemVenda, Log,
    criar_admin_padrao,
)
from conftest import make_setor, make_funcionario


def test_criar_admin_padrao_cria_admin(engine, session):
    criar_admin_padrao()
    admins = session.exec(select(Funcionario).where(Funcionario.is_admin == True)).all()
    assert len(admins) == 1
    assert admins[0].nome == "admin"


def test_criar_admin_padrao_idempotente(engine, session):
    criar_admin_padrao()
    criar_admin_padrao()
    admins = session.exec(select(Funcionario).where(Funcionario.is_admin == True)).all()
    assert len(admins) == 1


def test_criar_admin_padrao_cria_setor_admin(engine, session):
    criar_admin_padrao()
    setores = session.exec(select(Setor).where(Setor.tipo == "admin")).all()
    assert len(setores) == 1


def test_criar_admin_padrao_registra_historico(engine, session):
    criar_admin_padrao()
    admin = session.exec(select(Funcionario).where(Funcionario.is_admin == True)).first()
    hist = session.exec(
        select(HistoricoSenha).where(HistoricoSenha.funcionario_id == admin.id)
    ).all()
    assert len(hist) == 1


def test_funcionario_senha_temporaria_default_false(engine, session):
    setor = make_setor(session)
    f = make_funcionario(session, setor_id=setor.id)
    assert f.senha_temporaria is False


def test_funcionario_campos_endereco(engine, session):
    setor = make_setor(session)
    f = make_funcionario(session, setor_id=setor.id)
    assert f.cep == "01310100"
    assert f.estado == "SP"
    assert f.cidade == "Sao Paulo"
    assert f.bairro == "Centro"
    assert f.rua == "Av Paulista"
    assert f.numero == "1000"


def test_estoque_preco_custo_default_zero(engine, session):
    p = Estoque(
        nomedoproduto="Teste", quantidade=10, preco=5.0,
        codigodebarras="TEST001", categoria="Geral",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    assert p.preco_custo == 0.0


def test_estoque_com_preco_custo(engine, session):
    p = Estoque(
        nomedoproduto="Item", quantidade=5, preco=10.0, preco_custo=4.5,
        codigodebarras="TEST002", categoria="Geral",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    assert p.preco_custo == 4.5


def test_venda_data_preenchida_automaticamente(engine, session):
    setor = make_setor(session)
    f = make_funcionario(session, setor_id=setor.id)
    v = Venda(funcionario_id=f.id, valor_total=100.0)
    session.add(v)
    session.commit()
    session.refresh(v)
    assert isinstance(v.data, datetime)


def test_log_data_hora_preenchida(engine, session):
    setor = make_setor(session)
    f = make_funcionario(session, setor_id=setor.id)
    log = Log(funcionario_id=f.id, tipo_movimentacao="teste")
    session.add(log)
    session.commit()
    session.refresh(log)
    assert isinstance(log.data_hora, datetime)


def test_historico_senha_criado_em_preenchido(engine, session):
    setor = make_setor(session)
    f = make_funcionario(session, setor_id=setor.id)
    hist = HistoricoSenha(funcionario_id=f.id, password_hash="hash")
    session.add(hist)
    session.commit()
    session.refresh(hist)
    assert isinstance(hist.criado_em, datetime)


def test_setor_tipo_unico(engine, session):
    make_setor(session, tipo="unico")
    setor2 = Setor(nome="Outro", tipo="unico")
    session.add(setor2)
    with pytest.raises(Exception):
        session.commit()


def test_funcionario_cpf_unico(engine, session):
    setor = make_setor(session)
    make_funcionario(session, setor_id=setor.id, cpf="52998224725")
    f2 = Funcionario(
        nome="X", sobrenome="Y", data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False, setor_id=setor.id,
        cpf="52998224725", email="outro@test.com",
    )
    session.add(f2)
    with pytest.raises(Exception):
        session.commit()


def test_estoque_codigo_de_barras_unico(engine, session):
    p1 = Estoque(nomedoproduto="P1", quantidade=1, preco=1.0, codigodebarras="DUP", categoria="A")
    p2 = Estoque(nomedoproduto="P2", quantidade=1, preco=1.0, codigodebarras="DUP", categoria="A")
    session.add(p1)
    session.commit()
    session.add(p2)
    with pytest.raises(Exception):
        session.commit()
