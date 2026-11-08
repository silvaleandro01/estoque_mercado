import sys
import os
import itertools
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.environ.setdefault("SECRET_KEY", "chave-de-teste-nao-usar-em-producao")

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from datetime import date, datetime, timezone, timedelta
from passlib.context import CryptContext

from utils import database as db_mod
from utils.database import Setor, Funcionario, HistoricoSenha, Estoque, Compra, ItemCompra, Fornecedor, Lote
from utils.money import arredondar
from logs import logs as logs_mod
from repository import funcionarios as func_repo
from repository import estoque as est_repo
from repository import vendas as vend_repo
from repository import setores as set_repo
from repository import compras as compras_repo
from repository import despesas as despesas_repo
from repository import comunicados as com_repo
from repository import fornecedores as forn_repo
from repository import lotes as lotes_repo
from services import auth as auth_mod
from main import app

TEST_DB = "sqlite:///:memory:"
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_cpf_gen = itertools.count(1)
_email_gen = itertools.count(1)


def next_cpf():
    return f"{next(_cpf_gen):011d}"


def next_email():
    return f"user{next(_email_gen)}@test.com"


@pytest.fixture()
def engine(monkeypatch):
    eng = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)

    for mod in (db_mod, logs_mod, func_repo, est_repo, vend_repo, set_repo, compras_repo, despesas_repo, com_repo, forn_repo, lotes_repo, auth_mod):
        monkeypatch.setattr(mod, "engine", eng)

    yield eng
    SQLModel.metadata.drop_all(eng)


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


def make_setor(session, nome="Geral", tipo=None):
    tipo = tipo or f"tipo_{next(_cpf_gen)}"
    s = Setor(nome=nome, tipo=tipo)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def make_funcionario(session, nome="Joao", sobrenome="Silva", setor_id=None,
                     is_admin=False, with_password=True, password_age_days=0,
                     cpf=None, email=None, senha_temporaria=False, cargo="operacional"):
    if setor_id is None:
        setor = make_setor(session)
        setor_id = setor.id

    age = timedelta(days=password_age_days)
    password_hash = pwd.hash("Test@123") if with_password else None

    f = Funcionario(
        nome=nome, sobrenome=sobrenome,
        data_nascimento=date(1990, 1, 1),
        genero="M",
        possui_filhos=False,
        setor_id=setor_id,
        cargo=cargo,
        is_admin=is_admin,
        cpf=cpf or next_cpf(),
        email=email or next_email(),
        cep="01310100",
        estado="SP",
        cidade="Sao Paulo",
        bairro="Centro",
        rua="Av Paulista",
        numero="1000",
        password_hash=password_hash,
        senha_atualizada_em=datetime.now(timezone.utc) - age if with_password else None,
        senha_temporaria=senha_temporaria,
    )
    session.add(f)
    session.flush()

    if password_hash:
        session.add(HistoricoSenha(funcionario_id=f.id, password_hash=password_hash))

    session.commit()
    session.refresh(f)
    return f


def make_produto(session, nome="Produto Teste", codigo=None, qtd=50, preco=10.0, custo=5.0, cat="Geral",
                  unidade="UN", fornecedor_id=None):
    codigo = codigo or f"cod{next(_cpf_gen)}"
    p = Estoque(
        titulo=nome,
        nomedoproduto=nome,
        quantidade=qtd,
        unidade_medida=unidade,
        preco=arredondar(preco),
        preco_custo=arredondar(custo),
        codigodebarras=codigo,
        categoria=cat,
        funcionario_id=None,
        fornecedor_id=fornecedor_id,
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def make_lote(session, estoque_id, codigo_lote="L1", qtd=10, validade=None, data_entrada=None):
    lote = Lote(
        estoque_id=estoque_id,
        codigo_lote=codigo_lote,
        quantidade=qtd,
        validade=validade,
        data_entrada=data_entrada or datetime.now(timezone.utc),
    )
    session.add(lote)
    session.commit()
    session.refresh(lote)
    return lote


def make_fornecedor(session, nome="Fornecedor Teste", documento="11144477735",
                     telefone="11999999999", email=None, prazo_medio_entrega_dias=5):
    f = Fornecedor(
        nome=nome,
        documento=documento,
        telefone=telefone,
        email=email or f"fornecedor{next(_email_gen)}@test.com",
        prazo_medio_entrega_dias=prazo_medio_entrega_dias,
    )
    session.add(f)
    session.commit()
    session.refresh(f)
    return f


def make_compra(session, solicitante_id, status="pendente", aprovador_id=None, itens=None,
                 data_autorizacao=None, fornecedor_id=None):
    compra = Compra(
        solicitante_id=solicitante_id,
        aprovador_id=aprovador_id,
        status=status,
        valor_total=Decimal("0.00"),
        data_autorizacao=data_autorizacao,
        fornecedor_id=fornecedor_id,
    )
    session.add(compra)
    session.flush()

    total = Decimal("0.00")
    for item in (itens or [{"codigodebarras": "ITEMCOMPRA1", "nomedoproduto": "Produto Compra",
                             "categoria": "Geral", "preco_venda": 15.0, "quantidade": 10, "preco_custo": 5.0}]):
        preco_custo_total = arredondar(arredondar(item["preco_custo"]) * item["quantidade"])
        total += preco_custo_total
        session.add(ItemCompra(
            compra_id=compra.id,
            codigodebarras=item["codigodebarras"],
            nomedoproduto=item["nomedoproduto"],
            categoria=item.get("categoria"),
            preco_venda=arredondar(item["preco_venda"]) if item.get("preco_venda") is not None else None,
            quantidade=item["quantidade"],
            preco_custo_unitario=arredondar(item["preco_custo"]),
            preco_custo_total=preco_custo_total,
            lancado_em=item.get("lancado_em"),
        ))

    compra.valor_total = arredondar(total)
    session.add(compra)
    session.commit()
    session.refresh(compra)
    return compra


def set_token(session, funcionario):
    from utils.security import criar_token
    token = criar_token(funcionario.id, funcionario.is_admin)
    funcionario.token = token
    session.add(funcionario)
    session.commit()
    return token


@pytest.fixture()
def client(engine, session):
    setor = make_setor(session, nome="RH", tipo="rh")
    admin = make_funcionario(
        session, nome="admin", sobrenome="master",
        setor_id=setor.id, is_admin=True,
        cpf="52998224725", email="admin@test.com",
    )
    token = set_token(session, admin)
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update({"Authorization": f"Bearer {token}"})
    c._test_admin = admin
    c._test_token = token
    c._test_setor_rh = setor
    return c
