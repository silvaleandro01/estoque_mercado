import pytest
from datetime import date
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from conftest import make_setor, make_funcionario, make_produto, set_token

ENDERECO = dict(
    cep="01310100", estado="SP", cidade="SP",
    bairro="Centro", rua="Paulista", numero="100",
)


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── auth / login ──────────────────────────────────────────────────────────────

def test_login_sucesso(client, session, engine):
    setor = make_setor(session, tipo="vnd_login")
    make_funcionario(session, "mario", "bross", setor.id, cpf="11144477735", email="mario@test.com")
    r = client.post("/funcionarios/login", json={"username": "mario.bross", "senha": "Test@123"})
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert "lembrete_senha" in body
    assert "senha_temporaria" in body


def test_login_senha_errada(client):
    r = client.post("/funcionarios/login", json={"username": "admin.master", "senha": "errada"})
    assert r.status_code == 401


def test_login_formato_invalido(client):
    r = client.post("/funcionarios/login", json={"username": "semPonto", "senha": "x"})
    assert r.status_code == 401


def test_sem_token_retorna_422(engine):
    from fastapi.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/funcionarios/listar")
    assert r.status_code == 422


def test_token_invalido_retorna_401(engine):
    from fastapi.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/funcionarios/listar", headers={"Authorization": "Bearer invalido"})
    assert r.status_code == 401


def test_token_mal_formatado_sem_bearer(engine):
    from fastapi.testclient import TestClient
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/funcionarios/listar", headers={"Authorization": "Token invalido"})
    assert r.status_code == 401


# ── recuperar senha ───────────────────────────────────────────────────────────

def test_recuperar_senha_sucesso(client, session, engine):
    setor = make_setor(session, tipo="rec_main")
    make_funcionario(session, "rec", "user", setor.id, cpf="11144477735", email="rec@test.com")
    with patch("repository.funcionarios.enviar_email"):
        r = client.post("/funcionarios/recuperar-senha", json={"cpf": "529.982.247-25"})
    assert r.status_code == 200
    assert "enviada" in r.json()["msg"]


def test_recuperar_senha_cpf_inexistente(client):
    r = client.post("/funcionarios/recuperar-senha", json={"cpf": "00000000000"})
    assert r.status_code == 404


def test_recuperar_senha_email_nao_configurado(client, session, engine):
    setor = make_setor(session, tipo="rec_main2")
    make_funcionario(session, "rec2", "user", setor.id, cpf="11144477735", email="rec2@test.com")
    with patch("repository.funcionarios.enviar_email", side_effect=RuntimeError("não configurado")):
        r = client.post("/funcionarios/recuperar-senha", json={"cpf": "52998224725"})
    assert r.status_code == 503


# ── funcionarios CRUD ─────────────────────────────────────────────────────────

def test_criar_funcionario_sucesso(client, session, engine):
    setor = make_setor(session, tipo="rh_create")
    payload = dict(
        nome="Novo", sobrenome="Func",
        data_nascimento="1995-03-15",
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha="Test@123",
        cpf="11144477735", email="novo@test.com",
        **ENDERECO,
    )
    r = client.post("/funcionarios/criar", json=payload)
    assert r.status_code == 200
    assert r.json()["cpf"] == "11144477735"


def test_criar_funcionario_sem_autenticacao(client):
    r = client.post("/funcionarios/criar", json={}, headers={})
    assert r.status_code == 422


def test_criar_funcionario_cpf_invalido(client, session, engine):
    setor = make_setor(session, tipo="rh_inv_cpf")
    payload = dict(
        nome="X", sobrenome="Y",
        data_nascimento="1995-01-01",
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha="Test@123",
        cpf="11111111111", email="cpfinv@test.com",
        **ENDERECO,
    )
    r = client.post("/funcionarios/criar", json=payload)
    assert r.status_code == 422


def test_criar_funcionario_email_invalido(client, session, engine):
    setor = make_setor(session, tipo="rh_inv_email")
    payload = dict(
        nome="X", sobrenome="Y",
        data_nascimento="1995-01-01",
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha="Test@123",
        cpf="11144477735", email="emailinvalido",
        **ENDERECO,
    )
    r = client.post("/funcionarios/criar", json=payload)
    assert r.status_code == 422


def test_listar_funcionarios(client, session, engine):
    r = client.get("/funcionarios/listar")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_buscar_funcionario_sucesso(client, session, engine):
    admin = client._test_admin
    r = client.get(f"/funcionarios/buscar/{admin.id}")
    assert r.status_code == 200
    assert r.json()["id"] == admin.id


def test_buscar_funcionario_inexistente(client):
    r = client.get("/funcionarios/buscar/99999")
    assert r.status_code == 404


def test_atualizar_funcionario_sucesso(client, session, engine):
    setor = make_setor(session, tipo="rh_upd")
    f = make_funcionario(session, "upd", "func", setor.id, cpf="11144477735", email="upd@test.com")
    payload = dict(
        nome="Atualizado", sobrenome="Func",
        data_nascimento="1990-01-01",
        genero="M", possui_filhos=False,
        setor_id=setor.id,
        cpf="11144477735", email="upd2@test.com",
        **ENDERECO,
    )
    r = client.put(f"/funcionarios/atualizar/{f.id}", json=payload)
    assert r.status_code == 200
    assert r.json()["nome"] == "Atualizado"


def test_deletar_funcionario_sucesso(client, session, engine):
    setor = make_setor(session, tipo="rh_del")
    f = make_funcionario(session, "del", "func", setor.id, cpf="11144477735", email="del@test.com")
    r = client.delete(f"/funcionarios/deletar/{f.id}")
    assert r.status_code == 200
    assert "deletado" in r.json()["msg"]


def test_trocar_senha_sucesso(client, session, engine):
    admin = client._test_admin
    payload = {"senha_atual": "Test@123", "nova_senha": "NovaSenha@999"}
    r = client.patch("/funcionarios/trocar-senha", json=payload)
    assert r.status_code == 200


def test_trocar_senha_atual_errada(client):
    payload = {"senha_atual": "Errada@123", "nova_senha": "Nova@999"}
    r = client.patch("/funcionarios/trocar-senha", json=payload)
    assert r.status_code == 401


# ── setores ───────────────────────────────────────────────────────────────────

def test_criar_setor_sucesso(client):
    r = client.post("/setores/criar", json={"nome": "Financeiro", "tipo": "financeiro"})
    assert r.status_code == 200
    assert r.json()["tipo"] == "financeiro"


def test_criar_setor_duplicado(client):
    client.post("/setores/criar", json={"nome": "Mkt", "tipo": "mkt"})
    r = client.post("/setores/criar", json={"nome": "Mkt2", "tipo": "mkt"})
    assert r.status_code == 400


def test_listar_setores(client):
    r = client.get("/setores/listar")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_buscar_setor_sucesso(client, session, engine):
    setor = make_setor(session, tipo="bsc_setor")
    r = client.get(f"/setores/{setor.id}")
    assert r.status_code == 200


def test_buscar_setor_inexistente(client):
    r = client.get("/setores/99999")
    assert r.status_code == 404


def test_atualizar_setor(client, session, engine):
    setor = make_setor(session, tipo="upd_setor")
    r = client.put(f"/setores/{setor.id}", json={"nome": "Novo Nome", "tipo": "upd_setor"})
    assert r.status_code == 200


def test_deletar_setor(client, session, engine):
    setor = make_setor(session, tipo="del_setor")
    r = client.delete(f"/setores/{setor.id}")
    assert r.status_code == 200


# ── estoque ───────────────────────────────────────────────────────────────────

def test_inserir_estoque_sucesso(client):
    payload = dict(
        titulo="Produto Teste",
        nomedoproduto="Produto Teste",
        quantidade=100, preco=5.99, preco_custo=2.0,
        codigodebarras="BAR_MAIN_001", categoria="Geral",
    )
    r = client.post("/estoque/inserir", json=payload)
    assert r.status_code == 200
    assert r.json()["codigodebarras"] == "BAR_MAIN_001"


def test_inserir_estoque_preco_invalido(client):
    payload = dict(
        nomedoproduto="X", quantidade=1, preco=0.0,
        codigodebarras="BAR_INV", categoria="Geral",
    )
    r = client.post("/estoque/inserir", json=payload)
    assert r.status_code == 422


def test_mostrar_estoque(client, session, engine):
    make_produto(session, codigo="SHOW001")
    r = client.get("/estoque/mostrar")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_buscar_estoque_sucesso(client, session, engine):
    p = make_produto(session, codigo="BSC_EST001")
    r = client.get(f"/estoque/buscar/{p.id}")
    assert r.status_code == 200
    assert r.json()["id"] == p.id


def test_buscar_estoque_inexistente(client):
    r = client.get("/estoque/buscar/99999")
    assert r.status_code == 404


def test_atualizar_estoque(client, session, engine):
    p = make_produto(session, codigo="UPD_EST_MAIN")
    payload = dict(
        titulo="Atualizado", nomedoproduto="Atualizado",
        quantidade=200, preco=12.0,
        codigodebarras="UPD_EST_MAIN", categoria="Geral",
    )
    r = client.put(f"/estoque/atualizar/{p.id}", json=payload)
    assert r.status_code == 200
    assert r.json()["quantidade"] == 200


def test_deletar_estoque(client, session, engine):
    p = make_produto(session, codigo="DEL_EST_MAIN")
    r = client.delete(f"/estoque/deletar/{p.id}")
    assert r.status_code == 200


# ── vendas ────────────────────────────────────────────────────────────────────

def test_inserir_venda_sucesso(client, session, engine):
    setor_vnd = make_setor(session, tipo="vendas")
    func_vnd = make_funcionario(session, "vnd", "user", setor_vnd.id, cpf="11144477735", email="vnd@test.com")
    token = set_token(session, func_vnd)
    make_produto(session, codigo="VND_MAIN_001", qtd=10, preco=5.0)
    r = client.post(
        "/vendas/inserir",
        json={"itens": [{"codigodebarras": "VND_MAIN_001", "quantidade": 2}]},
        headers=_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["valor_total"] == 10.0


def test_inserir_venda_sem_estoque(client, session, engine):
    setor_vnd = make_setor(session, tipo="vendas")
    func_vnd = make_funcionario(session, "vnd2", "user", setor_vnd.id, cpf="11144477735", email="vnd2@test.com")
    token = set_token(session, func_vnd)
    make_produto(session, codigo="VND_MAIN_002", qtd=0, preco=5.0)
    r = client.post(
        "/vendas/inserir",
        json={"itens": [{"codigodebarras": "VND_MAIN_002", "quantidade": 1}]},
        headers=_headers(token),
    )
    assert r.status_code == 400


def test_inserir_venda_produto_inexistente(client, session, engine):
    setor_vnd = make_setor(session, tipo="vendas")
    func_vnd = make_funcionario(session, "vnd3", "user", setor_vnd.id, cpf="11144477735", email="vnd3@test.com")
    token = set_token(session, func_vnd)
    r = client.post(
        "/vendas/inserir",
        json={"itens": [{"codigodebarras": "NAEXISTE", "quantidade": 1}]},
        headers=_headers(token),
    )
    assert r.status_code == 404


def test_vendas_do_dia(client, session, engine):
    setor_vnd = make_setor(session, tipo="vendas")
    func_vnd = make_funcionario(session, "vnd4", "user", setor_vnd.id, cpf="11144477735", email="vnd4@test.com")
    token = set_token(session, func_vnd)
    r = client.get("/vendas/vendasdodia", headers=_headers(token))
    assert r.status_code == 200
    assert "total_vendido" in r.json()


# ── logs ──────────────────────────────────────────────────────────────────────

def test_ver_logs_sucesso(client):
    r = client.get("/logs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ver_logs_sem_autenticacao(engine):
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/logs")
    assert r.status_code == 422


# ── rh router ────────────────────────────────────────────────────────────────

def test_renovar_token_rh(client, session, engine):
    setor = make_setor(session, tipo="ren_main")
    f = make_funcionario(session, "ren", "func", setor.id, cpf="11144477735", email="ren@test.com")
    r = client.post(f"/rh/renovar-token/{f.id}")
    assert r.status_code == 200
    assert "token" in r.json()


def test_permissao_negada_setor_errado(client, session, engine):
    setor_est = make_setor(session, tipo="estoque_perm")
    func_est = make_funcionario(session, "est", "user", setor_est.id, cpf="11144477735", email="est@test.com")
    token = set_token(session, func_est)
    r = client.get("/funcionarios/listar", headers=_headers(token))
    assert r.status_code == 403
