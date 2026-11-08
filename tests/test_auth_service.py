"""
Testes para o serviço de autenticação (services/auth.py).
"""
import pytest
from fastapi import HTTPException

from services.auth import get_funcionario, verificar_permissao
from conftest import make_setor, make_funcionario, set_token


def test_get_funcionario_bearer_valido(engine, session):
    setor = make_setor(session, tipo="auth1")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    resultado = get_funcionario(authorization=f"Bearer {token}")
    assert resultado.id == func.id


def test_get_funcionario_sem_bearer_prefix(engine, session):
    with pytest.raises(HTTPException) as exc:
        get_funcionario(authorization="Token invalido")
    assert exc.value.status_code == 401


def test_get_funcionario_bearer_case_insensitive(engine, session):
    setor = make_setor(session, tipo="auth2")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    resultado = get_funcionario(authorization=f"BEARER {token}")
    assert resultado.id == func.id


def test_get_funcionario_token_invalido(engine, session):
    with pytest.raises(HTTPException) as exc:
        get_funcionario(authorization="Bearer tokeninvalido")
    assert exc.value.status_code == 401


def test_verificar_permissao_admin_acessa_tudo(engine, session):
    setor = make_setor(session, tipo="auth3")
    admin = make_funcionario(session, setor_id=setor.id, is_admin=True)
    assert verificar_permissao(admin, "qualquer_rota") is True
    assert verificar_permissao(admin, "rh") is True
    assert verificar_permissao(admin, "vendas") is True
    assert verificar_permissao(admin, "estoque") is True


def test_verificar_permissao_setor_correto(engine, session):
    setor = make_setor(session, tipo="rh")
    func = make_funcionario(session, setor_id=setor.id)
    assert verificar_permissao(func, "rh") is True


def test_verificar_permissao_setor_errado(engine, session):
    setor = make_setor(session, tipo="vendas_perm")
    func = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        verificar_permissao(func, "rh")
    assert exc.value.status_code == 403


def test_verificar_permissao_setor_inexistente(engine, session):
    setor = make_setor(session, tipo="temp_perm")
    func = make_funcionario(session, setor_id=setor.id)
    func.setor_id = 99999
    with pytest.raises(HTTPException) as exc:
        verificar_permissao(func, "rh")
    assert exc.value.status_code == 403
