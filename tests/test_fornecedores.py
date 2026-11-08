import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session as SQLSession

from repository.fornecedores import (
    criar_fornecedor, mostrar_fornecedores, buscar_fornecedor,
    atualizar_fornecedor, deletar_fornecedor,
)
from repository.estoque import criar_estoque
from repository.compras import registrar_compra
from schemas.schemas import FornecedorInput, EstoqueCreate, CompraInput, ItemCompraInput
from conftest import make_setor, make_funcionario, make_fornecedor, make_produto


def _dados(nome="Distribuidora ABC", documento="11144477735", telefone="11988887777",
           email="contato@abc.com", prazo=7):
    return FornecedorInput(
        nome=nome, documento=documento, telefone=telefone, email=email,
        prazo_medio_entrega_dias=prazo,
    )


# ── validação de documento (CPF ou CNPJ) ────────────────────────────────────────

def test_documento_aceita_cpf_valido():
    m = FornecedorInput(nome="Pessoa Fisica", documento="529.982.247-25")
    assert m.documento == "52998224725"


def test_documento_aceita_cnpj_valido():
    m = FornecedorInput(nome="Empresa LTDA", documento="11.222.333/0001-81")
    assert m.documento == "11222333000181"


def test_documento_cpf_digito_invalido_rejeitado():
    with pytest.raises(ValidationError):
        FornecedorInput(nome="X", documento="52998224700")


def test_documento_cnpj_digito_invalido_rejeitado():
    with pytest.raises(ValidationError):
        FornecedorInput(nome="X", documento="11222333000199")


def test_documento_tamanho_invalido_rejeitado():
    with pytest.raises(ValidationError):
        FornecedorInput(nome="X", documento="12345")


def test_email_invalido_rejeitado():
    with pytest.raises(ValidationError):
        FornecedorInput(nome="X", documento="11144477735", email="nao-e-email")


def test_email_opcional():
    m = FornecedorInput(nome="X", documento="11144477735")
    assert m.email is None


def test_prazo_entrega_negativo_rejeitado():
    with pytest.raises(ValidationError):
        FornecedorInput(nome="X", documento="11144477735", prazo_medio_entrega_dias=-1)


# ── criar_fornecedor ─────────────────────────────────────────────────────────────

def test_criar_fornecedor_sucesso(engine, session):
    setor = make_setor(session, tipo="forn1")
    func = make_funcionario(session, setor_id=setor.id)
    resultado = criar_fornecedor(_dados(), func.id)
    assert resultado.id is not None
    assert resultado.nome == "Distribuidora ABC"
    assert resultado.documento == "11144477735"
    assert resultado.prazo_medio_entrega_dias == 7


def test_criar_fornecedor_documento_duplicado_falha(engine, session):
    setor = make_setor(session, tipo="forn2")
    func = make_funcionario(session, setor_id=setor.id)
    criar_fornecedor(_dados(documento="11144477735"), func.id)
    with pytest.raises(HTTPException) as exc:
        criar_fornecedor(_dados(nome="Outra", documento="11144477735"), func.id)
    assert exc.value.status_code == 400


class _ResultadoVazio:
    """Fake de resultado do session.exec(): simula um SELECT que não
    encontra nenhuma linha -- usado para forçar o caminho de corrida
    (TOCTOU) nos testes abaixo, sem precisar de threads reais."""

    def first(self):
        return None


def test_criar_fornecedor_race_condition_integrity_error_vira_400(engine, session, monkeypatch):
    """
    criar_fornecedor faz um SELECT para checar documento duplicado e só
    depois faz o INSERT -- um TOCTOU clássico (time-of-check to
    time-of-use). Sob concorrência real (MySQL), duas requisições passam
    pelo SELECT antes de qualquer uma comitar (nenhuma encontra duplicado
    ainda), e a segunda bate na UNIQUE KEY do banco ao tentar o INSERT,
    virando um 500 cru em vez do 400 esperado (reproduzido em ~22% das
    colisões em teste de carga real contra MySQL via Docker).

    Simula a corrida sem precisar de threads reais: o documento duplicado
    já existe de verdade no banco (`make_fornecedor` abaixo), e o SELECT de
    checagem é forçado a não encontrar nada (como aconteceria se a outra
    transação concorrente ainda não tivesse comitado) -- o INSERT que segue
    bate na UNIQUE KEY de verdade (IntegrityError real do SQLite), e a
    correção precisa capturar isso especificamente e devolver 400.
    """
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="forn_race1")
    func = make_funcionario(session, setor_id=setor.id)
    make_fornecedor(session, documento="11144477735")

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", lambda self, *a, **kw: _ResultadoVazio())

    with pytest.raises(HTTPException) as exc:
        criar_fornecedor(_dados(nome="Outra Distribuidora", documento="11144477735"), func.id)
    assert exc.value.status_code == 400
    assert "Já existe fornecedor" in exc.value.detail


def test_atualizar_fornecedor_race_condition_integrity_error_vira_400(engine, session, monkeypatch):
    """Mesmo TOCTOU de test_criar_fornecedor_race_condition_..., agora em
    atualizar_fornecedor: o SELECT de duplicado é forçado a não encontrar
    nada, mas o documento já existe de verdade em OUTRO fornecedor, então o
    UPDATE bate na UNIQUE KEY de verdade."""
    import sqlmodel as sqlmodel_mod

    setor = make_setor(session, tipo="forn_race2")
    func = make_funcionario(session, setor_id=setor.id)
    make_fornecedor(session, documento="11144477735")
    outro = make_fornecedor(session, documento="52998224725")

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", lambda self, *a, **kw: _ResultadoVazio())

    with pytest.raises(HTTPException) as exc:
        atualizar_fornecedor(outro.id, _dados(documento="11144477735"), func.id)
    assert exc.value.status_code == 400
    assert "já cadastrado" in exc.value.detail.lower()


# ── mostrar / buscar ─────────────────────────────────────────────────────────────

def test_mostrar_fornecedores_vazio(engine, session):
    assert mostrar_fornecedores() == []


def test_mostrar_fornecedores_multiplos(engine, session):
    make_fornecedor(session, documento="11144477735")
    make_fornecedor(session, documento="52998224725")
    assert len(mostrar_fornecedores()) == 2


def test_buscar_fornecedor_encontrado(engine, session):
    f = make_fornecedor(session)
    resultado = buscar_fornecedor(f.id)
    assert resultado.id == f.id


def test_buscar_fornecedor_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_fornecedor(99999)
    assert exc.value.status_code == 404


# ── atualizar_fornecedor ─────────────────────────────────────────────────────────

def test_atualizar_fornecedor_sucesso(engine, session):
    setor = make_setor(session, tipo="forn3")
    func = make_funcionario(session, setor_id=setor.id)
    f = make_fornecedor(session, nome="Nome Antigo")
    dados = _dados(nome="Nome Novo", documento=f.documento)
    resultado = atualizar_fornecedor(f.id, dados, func.id)
    assert resultado.nome == "Nome Novo"


def test_atualizar_fornecedor_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        atualizar_fornecedor(99999, _dados(), 1)
    assert exc.value.status_code == 404


def test_atualizar_fornecedor_documento_duplicado_falha(engine, session):
    setor = make_setor(session, tipo="forn4")
    func = make_funcionario(session, setor_id=setor.id)
    make_fornecedor(session, documento="11144477735")
    outro = make_fornecedor(session, documento="52998224725")
    dados = _dados(documento="11144477735")
    with pytest.raises(HTTPException) as exc:
        atualizar_fornecedor(outro.id, dados, func.id)
    assert exc.value.status_code == 400


# ── deletar_fornecedor ───────────────────────────────────────────────────────────

def test_deletar_fornecedor_sucesso(engine, session):
    f = make_fornecedor(session)
    resultado = deletar_fornecedor(f.id)
    assert "deletado" in resultado["msg"]


def test_deletar_fornecedor_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        deletar_fornecedor(99999)
    assert exc.value.status_code == 404


def _engine_com_fk_habilitada(monkeypatch):
    """
    Cria um engine de teste SQLite dedicado, com PRAGMA foreign_keys=ON
    aplicado via event listener do SQLAlchemy na conexão, e substitui o
    `engine` usado pelos repositories envolvidos (mesmo padrão da fixture
    `engine` de conftest.py, mas com FK habilitada).

    SQLite não aplica FOREIGN KEY por padrão -- o engine global da suíte
    (fixture `engine` de conftest.py) não habilita essa checagem, então sem
    isso o bug de deletar_fornecedor devolvendo 500 cru em vez de 409 numa
    FK violada (em MySQL real) nunca seria pego por nenhum teste, como o
    painel de revisão apontou.
    """
    from utils import database as db_mod
    from logs import logs as logs_mod
    from repository import fornecedores as forn_repo
    from repository import estoque as est_repo
    from repository import compras as compras_repo

    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(eng, "connect")
    def _habilitar_fk(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    for mod in (db_mod, logs_mod, forn_repo, est_repo, compras_repo):
        monkeypatch.setattr(mod, "engine", eng)
    return eng


def test_deletar_fornecedor_vinculado_a_produto_retorna_409(monkeypatch):
    eng = _engine_com_fk_habilitada(monkeypatch)
    with SQLSession(eng) as s:
        setor = make_setor(s, tipo="forn_fk1")
        make_funcionario(s, setor_id=setor.id)
        fornecedor = make_fornecedor(s, documento="11144477735")
        make_produto(s, codigo="FKPROD001", fornecedor_id=fornecedor.id)
        fornecedor_id = fornecedor.id

    with pytest.raises(HTTPException) as exc:
        deletar_fornecedor(fornecedor_id)
    assert exc.value.status_code == 409
    assert "vinculad" in exc.value.detail.lower()


def test_deletar_fornecedor_vinculado_a_compra_retorna_409(monkeypatch):
    eng = _engine_com_fk_habilitada(monkeypatch)
    with SQLSession(eng) as s:
        setor = make_setor(s, tipo="forn_fk2")
        func = make_funcionario(s, setor_id=setor.id, cargo="operacional")
        fornecedor = make_fornecedor(s, documento="52998224725")
        func_id = func.id
        fornecedor_id = fornecedor.id

    dados = CompraInput(
        itens=[ItemCompraInput(
            codigodebarras="FKCOMP001", quantidade=5, preco_custo=3.0,
            nomedoproduto="Produto FK", preco_venda=6.0, categoria="Geral",
        )],
        fornecedor_id=fornecedor_id,
    )
    registrar_compra(dados, func_id)

    with pytest.raises(HTTPException) as exc:
        deletar_fornecedor(fornecedor_id)
    assert exc.value.status_code == 409
    assert "vinculad" in exc.value.detail.lower()


def test_deletar_fornecedor_sem_vinculo_continua_funcionando_com_fk_habilitada(monkeypatch):
    """Garante que a FK habilitada não quebra o caso feliz (sem vínculo)."""
    eng = _engine_com_fk_habilitada(monkeypatch)
    with SQLSession(eng) as s:
        fornecedor = make_fornecedor(s, documento="11144477735")
        fornecedor_id = fornecedor.id

    resultado = deletar_fornecedor(fornecedor_id)
    assert "deletado" in resultado["msg"]


# ── vínculo opcional produto <-> fornecedor ─────────────────────────────────────

def test_criar_estoque_com_fornecedor(engine, session):
    setor = make_setor(session, tipo="forn_prod1")
    func = make_funcionario(session, setor_id=setor.id)
    fornecedor = make_fornecedor(session)
    dados = EstoqueCreate(
        nomedoproduto="Produto com Fornecedor", quantidade=10, preco=5.0,
        codigodebarras="FORNPROD001", categoria="Geral", fornecedor_id=fornecedor.id,
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.fornecedor_id == fornecedor.id


def test_criar_estoque_sem_fornecedor_continua_funcionando(engine, session):
    setor = make_setor(session, tipo="forn_prod2")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto sem Fornecedor", quantidade=10, preco=5.0,
        codigodebarras="FORNPROD002", categoria="Geral",
    )
    resultado = criar_estoque(dados, func.id)
    assert resultado.fornecedor_id is None


def test_criar_estoque_fornecedor_inexistente_404(engine, session):
    setor = make_setor(session, tipo="forn_prod3")
    func = make_funcionario(session, setor_id=setor.id)
    dados = EstoqueCreate(
        nomedoproduto="Produto", quantidade=10, preco=5.0,
        codigodebarras="FORNPROD003", categoria="Geral", fornecedor_id=99999,
    )
    with pytest.raises(HTTPException) as exc:
        criar_estoque(dados, func.id)
    assert exc.value.status_code == 404


# ── vínculo opcional compra <-> fornecedor ──────────────────────────────────────

def _item_compra(codigo="FORNCOMP001", qtd=10, custo=5.0):
    return ItemCompraInput(
        codigodebarras=codigo, quantidade=qtd, preco_custo=custo,
        nomedoproduto="Produto Compra", preco_venda=10.0, categoria="Geral",
    )


def test_registrar_compra_com_fornecedor(engine, session):
    setor = make_setor(session, tipo="forn_compra1")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    fornecedor = make_fornecedor(session)
    dados = CompraInput(itens=[_item_compra()], fornecedor_id=fornecedor.id)
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"

    from repository.compras import listar_compras
    encontrada = next(c for c in listar_compras() if c["id"] == resultado["id"])
    assert encontrada["fornecedor"] == fornecedor.nome


def test_registrar_compra_sem_fornecedor_continua_funcionando(engine, session):
    setor = make_setor(session, tipo="forn_compra2")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[_item_compra(codigo="FORNCOMP002")])
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"

    from repository.compras import listar_compras
    encontrada = next(c for c in listar_compras() if c["id"] == resultado["id"])
    assert encontrada["fornecedor"] is None


def test_registrar_compra_fornecedor_inexistente_404(engine, session):
    setor = make_setor(session, tipo="forn_compra3")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[_item_compra(codigo="FORNCOMP003")], fornecedor_id=99999)
    with pytest.raises(HTTPException) as exc:
        registrar_compra(dados, func.id)
    assert exc.value.status_code == 404


# ── permissão via rotas HTTP ─────────────────────────────────────────────────────

def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_rota_inserir_fornecedor_nega_funcionario_fora_do_setor(client, session, engine):
    from conftest import set_token

    setor = make_setor(session, tipo="forn_vendas")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.post("/fornecedores/inserir", json={
        "nome": "X", "documento": "11144477735",
    }, headers=_headers(token))
    assert r.status_code == 403


def test_rota_fluxo_completo_fornecedor(client, session, engine):
    from conftest import set_token

    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    r = client.post("/fornecedores/inserir", json={
        "nome": "Fornecedor Rota", "documento": "11144477735",
        "telefone": "11999998888", "email": "rota@teste.com", "prazo_medio_entrega_dias": 10,
    }, headers=_headers(token))
    assert r.status_code == 200
    fornecedor_id = r.json()["id"]

    r = client.get("/fornecedores/mostrar", headers=_headers(token))
    assert r.status_code == 200
    assert any(f["id"] == fornecedor_id for f in r.json())

    r = client.put(f"/fornecedores/atualizar/{fornecedor_id}", json={
        "nome": "Fornecedor Atualizado", "documento": "11144477735",
    }, headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["nome"] == "Fornecedor Atualizado"

    r = client.delete(f"/fornecedores/deletar/{fornecedor_id}", headers=_headers(token))
    assert r.status_code == 200
