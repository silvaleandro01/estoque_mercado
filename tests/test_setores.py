import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock
from sqlmodel import Session

from schemas.schemas import SetorCreate
from repository.setores import (
    criar_setor, listar_setores, buscar_setor,
    atualizar_setor, deletar_setor,
)
from conftest import make_setor


def test_criar_setor_sucesso(engine, session):
    dados = SetorCreate(nome="Vendas", tipo="vendas")
    resultado = criar_setor(dados)
    assert resultado.id is not None
    assert resultado.tipo == "vendas"


def test_criar_setor_duplicado(engine, session):
    make_setor(session, nome="RH", tipo="rh")
    with pytest.raises(HTTPException) as exc:
        criar_setor(SetorCreate(nome="RH2", tipo="rh"))
    assert exc.value.status_code == 400


def test_criar_setor_tipos_diferentes(engine, session):
    criar_setor(SetorCreate(nome="A", tipo="tipo_a"))
    resultado = criar_setor(SetorCreate(nome="B", tipo="tipo_b"))
    assert resultado.tipo == "tipo_b"


def test_listar_setores_vazio(engine, session):
    assert listar_setores() == []


def test_listar_setores_multiplos(engine, session):
    make_setor(session, tipo="s1")
    make_setor(session, tipo="s2")
    assert len(listar_setores()) == 2


def test_buscar_setor_encontrado(engine, session):
    s = make_setor(session, tipo="estoque")
    resultado = buscar_setor(s.id)
    assert resultado.id == s.id


def test_buscar_setor_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_setor(9999)
    assert exc.value.status_code == 404


def test_atualizar_setor_sucesso(engine, session):
    s = make_setor(session, nome="Antigo", tipo="antigo")
    resultado = atualizar_setor(s.id, SetorCreate(nome="Novo", tipo="novo"))
    assert resultado.nome == "Novo"
    assert resultado.tipo == "novo"


def test_atualizar_setor_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        atualizar_setor(9999, SetorCreate(nome="X", tipo="x"))
    assert exc.value.status_code == 404


def test_atualizar_setor_tipo_conflito(engine, session):
    make_setor(session, tipo="ocupado")
    s2 = make_setor(session, tipo="livre")
    with pytest.raises(HTTPException) as exc:
        atualizar_setor(s2.id, SetorCreate(nome="X", tipo="ocupado"))
    assert exc.value.status_code == 400


def test_atualizar_setor_mesmo_tipo(engine, session):
    s = make_setor(session, nome="Original", tipo="mesmo")
    resultado = atualizar_setor(s.id, SetorCreate(nome="Atualizado", tipo="mesmo"))
    assert resultado.nome == "Atualizado"


def test_deletar_setor_sucesso(engine, session):
    s = make_setor(session, tipo="del")
    resultado = deletar_setor(s.id)
    assert "deletado" in resultado["msg"]


def test_deletar_setor_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        deletar_setor(9999)
    assert exc.value.status_code == 404


def test_deletar_setor_erro_interno(engine, session):
    s = make_setor(session, tipo="del_err")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            deletar_setor(s.id)
        assert exc.value.status_code == 500


def test_deletar_setor_duas_vezes(engine, session):
    s = make_setor(session, tipo="duplo")
    deletar_setor(s.id)
    with pytest.raises(HTTPException) as exc:
        deletar_setor(s.id)
    assert exc.value.status_code == 404


def test_criar_setor_erro_interno(engine, session):
    from sqlmodel import Session
    with patch.object(Session, "commit", side_effect=Exception("DB error")):
        with pytest.raises(HTTPException) as exc:
            criar_setor(SetorCreate(nome="X", tipo="err_create"))
        assert exc.value.status_code == 500


def test_atualizar_setor_erro_interno(engine, session):
    s = make_setor(session, tipo="err_upd")
    from sqlmodel import Session
    with patch.object(Session, "commit", side_effect=Exception("DB error")):
        with pytest.raises(HTTPException) as exc:
            atualizar_setor(s.id, SetorCreate(nome="Y", tipo="err_upd"))
        assert exc.value.status_code == 500
