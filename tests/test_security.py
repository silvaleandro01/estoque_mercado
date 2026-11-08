import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt

from utils.security import (
    hash_senha, verificar_senha, criar_token, verificar_token,
    validar_funcionario_por_token, SECRET_KEY, ALGORITHM,
)
from conftest import make_setor, make_funcionario, set_token


def test_hash_senha_retorna_string_nao_vazia():
    h = hash_senha("minhasenha")
    assert isinstance(h, str) and len(h) > 0


def test_hash_senha_diferente_do_original():
    assert hash_senha("abc") != "abc"


def test_hash_senha_dois_hashes_diferentes_mesmo_input():
    assert hash_senha("abc") != hash_senha("abc")


def test_verificar_senha_correta():
    h = hash_senha("Test@123")
    assert verificar_senha("Test@123", h) is True


def test_verificar_senha_errada():
    h = hash_senha("Test@123")
    assert verificar_senha("errada", h) is False


def test_verificar_senha_vazia():
    h = hash_senha("Test@123")
    assert verificar_senha("", h) is False


def test_criar_token_retorna_string():
    token = criar_token(1, False)
    assert isinstance(token, str) and len(token) > 0


def test_criar_token_possui_expiracao():
    token = criar_token(1, False)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert "exp" in payload
    assert payload["exp"] > payload["iat"]


def test_verificar_token_expirado_retorna_none():
    payload = {
        "sub": "1",
        "is_admin": False,
        "iat": (datetime.now(timezone.utc) - timedelta(hours=9)).timestamp(),
        "exp": (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp(),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    assert verificar_token(token) is None


def test_criar_token_contem_sub_e_is_admin():
    token = criar_token(42, True)
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
    assert payload["sub"] == "42"
    assert payload["is_admin"] is True


def test_verificar_token_valido():
    token = criar_token(7, False)
    assert verificar_token(token) == 7


def test_verificar_token_admin():
    token = criar_token(99, True)
    assert verificar_token(token) == 99


def test_verificar_token_invalido_retorna_none():
    assert verificar_token("token.invalido.aqui") is None


def test_verificar_token_vazio_retorna_none():
    assert verificar_token("") is None


def test_verificar_token_sem_sub():
    payload = {"is_admin": False}
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    assert verificar_token(token) is None


def test_validar_funcionario_por_token_valido(engine, session):
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)

    resultado = validar_funcionario_por_token(token)
    assert resultado.id == func.id


def test_validar_funcionario_token_invalido(engine, session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        validar_funcionario_por_token("tokeninvalido")
    assert exc.value.status_code == 401


def test_validar_funcionario_token_nao_corresponde(engine, session):
    from fastapi import HTTPException
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    token_real = set_token(session, func)
    token_outro = criar_token(func.id, False)

    with pytest.raises(HTTPException) as exc:
        validar_funcionario_por_token(token_outro)
    assert exc.value.status_code == 401


def test_validar_funcionario_inexistente(engine, session):
    from fastapi import HTTPException
    token = criar_token(99999, False)
    with pytest.raises(HTTPException) as exc:
        validar_funcionario_por_token(token)
    assert exc.value.status_code == 401


def test_novo_login_invalida_token_anterior(engine, session):
    from fastapi import HTTPException
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    token_antigo = set_token(session, func)
    token_novo = set_token(session, func)

    with pytest.raises(HTTPException):
        validar_funcionario_por_token(token_antigo)

    resultado = validar_funcionario_por_token(token_novo)
    assert resultado.id == func.id
