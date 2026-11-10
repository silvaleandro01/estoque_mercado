import pytest
from fastapi import HTTPException

from repository.despesas import criar_despesa, listar_despesas
from services.auth import verificar_permissao
from schemas.schemas import DespesaInput
from conftest import make_setor, make_funcionario, set_token


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── permissão (via verificar_permissao estendido) ───────────────────────────

def test_verificar_permissao_tupla_setor_rh(engine, session):
    setor = make_setor(session, tipo="rh")
    func = make_funcionario(session, setor_id=setor.id)
    assert verificar_permissao(func, ("rh", "gerencia")) is True


def test_verificar_permissao_tupla_setor_gerencia(engine, session):
    setor = make_setor(session, tipo="gerencia")
    func = make_funcionario(session, setor_id=setor.id)
    assert verificar_permissao(func, ("rh", "gerencia")) is True


def test_verificar_permissao_tupla_setor_fora_da_lista_nega(engine, session):
    setor = make_setor(session, tipo="vendas")
    func = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        verificar_permissao(func, ("rh", "gerencia"))
    assert exc.value.status_code == 403


def test_verificar_permissao_string_continua_funcionando(engine, session):
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id)
    assert verificar_permissao(func, "estoque") is True


# ── criar_despesa / listar_despesas ─────────────────────────────────────────

def test_criar_despesa_sucesso(engine, session):
    setor = make_setor(session, tipo="rh2")
    func = make_funcionario(session, setor_id=setor.id)
    dados = DespesaInput(descricao="Aluguel", valor=1500.0, categoria="Fixo")
    despesa = criar_despesa(dados, func.id)
    assert despesa.id is not None
    assert despesa.descricao == "Aluguel"
    assert despesa.valor == 1500.0
    assert despesa.categoria == "Fixo"
    assert despesa.funcionario_id == func.id


def test_listar_despesas_retorna_criadas(engine, session):
    setor = make_setor(session, tipo="rh3")
    func = make_funcionario(session, setor_id=setor.id)
    criar_despesa(DespesaInput(descricao="Energia", valor=300.0, categoria="Variavel"), func.id)
    criar_despesa(DespesaInput(descricao="Reparo", valor=200.0, categoria="Manutencao"), func.id)
    lista = listar_despesas()
    descricoes = {d.descricao for d in lista}
    assert {"Energia", "Reparo"}.issubset(descricoes)


# ── rotas HTTP ───────────────────────────────────────────────────────────────

def test_rota_inserir_despesa_rh(client, session, engine):
    func = make_funcionario(session, setor_id=client._test_setor_rh.id)
    token = set_token(session, func)
    r = client.post("/despesas/inserir", json={
        "descricao": "Internet", "valor": 150.0, "categoria": "Fixo",
    }, headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["descricao"] == "Internet"


def test_rota_inserir_despesa_gerencia(client, session, engine):
    setor = make_setor(session, tipo="gerencia")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.post("/despesas/inserir", json={
        "descricao": "Brinde cliente", "valor": 50.0, "categoria": "Outros",
    }, headers=_headers(token))
    assert r.status_code == 200


def test_rota_inserir_despesa_nega_setor_errado(client, session, engine):
    setor = make_setor(session, tipo="vendas2")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.post("/despesas/inserir", json={
        "descricao": "X", "valor": 10.0, "categoria": "Outros",
    }, headers=_headers(token))
    assert r.status_code == 403


def test_rota_inserir_despesa_categoria_invalida_422(client, session, engine):
    setor = make_setor(session, tipo="rh5")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.post("/despesas/inserir", json={
        "descricao": "X", "valor": 10.0, "categoria": "NaoExiste",
    }, headers=_headers(token))
    assert r.status_code == 422


def test_rota_inserir_despesa_valor_negativo_422(client, session, engine):
    setor = make_setor(session, tipo="rh6")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.post("/despesas/inserir", json={
        "descricao": "X", "valor": -10.0, "categoria": "Fixo",
    }, headers=_headers(token))
    assert r.status_code == 422


def test_rota_listar_despesas(client, session, engine):
    func = make_funcionario(session, setor_id=client._test_setor_rh.id)
    token = set_token(session, func)
    client.post("/despesas/inserir", json={
        "descricao": "Agua", "valor": 80.0, "categoria": "Fixo",
    }, headers=_headers(token))
    r = client.get("/despesas/listar", headers=_headers(token))
    assert r.status_code == 200
    assert any(d["descricao"] == "Agua" for d in r.json())


def test_rota_listar_despesas_nega_setor_errado(client, session, engine):
    setor = make_setor(session, tipo="vendas3")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    r = client.get("/despesas/listar", headers=_headers(token))
    assert r.status_code == 403
