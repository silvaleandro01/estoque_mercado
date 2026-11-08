import pytest
from datetime import date, datetime, timezone, timedelta
from fastapi import HTTPException
from unittest.mock import patch
from sqlmodel import Session

from repository.funcionarios import (
    autenticar_funcionario, criar_funcionario, listar_funcionarios,
    buscar_funcionario, atualizar_funcionario, deletar_funcionario,
    renovar_token, trocar_senha, recuperar_senha,
    _senha_ja_usada, _registrar_historico,
)
from schemas.schemas import (
    LoginRequest, FuncionarioCreate, TrocarSenhaRequest, RecuperarSenhaRequest,
)
from utils.database import HistoricoSenha
from conftest import make_setor, make_funcionario, pwd

ENDERECO = dict(
    cep="01310100", estado="SP", cidade="SP",
    bairro="Centro", rua="Paulista", numero="100",
)


def _dados_create(setor_id, cpf="52998224725", email="joao@test.com", senha="Test@123"):
    return FuncionarioCreate(
        nome="Joao", sobrenome="Silva",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor_id, senha=senha,
        cpf=cpf, email=email, **ENDERECO,
    )


# ── autenticar_funcionario ────────────────────────────────────────────────────

def test_login_sucesso(engine, session):
    setor = make_setor(session, tipo="rh")
    make_funcionario(session, "joao", "silva", setor.id, cpf="52998224725", email="j@test.com")
    res = autenticar_funcionario(LoginRequest(username="joao.silva", senha="Test@123"))
    assert "token" in res
    assert res["lembrete_senha"] is False
    assert res["senha_temporaria"] is False


def test_login_formato_invalido(engine, session):
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="semPonto", senha="x"))
    assert exc.value.status_code == 401
    assert "Formato" in exc.value.detail


def test_login_usuario_nao_encontrado(engine, session):
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="nao.existe", senha="x"))
    assert exc.value.status_code == 401


def test_login_sem_senha_definida(engine, session):
    setor = make_setor(session, tipo="rh2")
    make_funcionario(session, "sem", "senha", setor.id, with_password=False)
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="sem.senha", senha="Test@123"))
    assert exc.value.status_code == 401
    assert "não definida" in exc.value.detail


def test_login_senha_errada(engine, session):
    setor = make_setor(session, tipo="rh3")
    make_funcionario(session, "pedro", "certo", setor.id)
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="pedro.certo", senha="SenhaErrada"))
    assert exc.value.status_code == 401
    assert "incorreta" in exc.value.detail


def test_login_lembrete_senha_um_ano(engine, session):
    setor = make_setor(session, tipo="rh4")
    make_funcionario(session, "ana", "velha", setor.id, password_age_days=366)
    res = autenticar_funcionario(LoginRequest(username="ana.velha", senha="Test@123"))
    assert res["lembrete_senha"] is True


def test_login_lembrete_senha_menos_de_um_ano(engine, session):
    setor = make_setor(session, tipo="rh5")
    make_funcionario(session, "ana", "nova", setor.id, password_age_days=200)
    res = autenticar_funcionario(LoginRequest(username="ana.nova", senha="Test@123"))
    assert res["lembrete_senha"] is False


def test_login_sem_data_senha(engine, session):
    setor = make_setor(session, tipo="rh6")
    f = make_funcionario(session, "sem", "data", setor.id)
    with Session(engine) as s:
        func = s.get(type(f), f.id)
        func.senha_atualizada_em = None
        s.add(func)
        s.commit()
    res = autenticar_funcionario(LoginRequest(username="sem.data", senha="Test@123"))
    assert res["lembrete_senha"] is False


def test_login_senha_temporaria_true(engine, session):
    setor = make_setor(session, tipo="rh7")
    make_funcionario(session, "temp", "user", setor.id, senha_temporaria=True)
    res = autenticar_funcionario(LoginRequest(username="temp.user", senha="Test@123"))
    assert res["senha_temporaria"] is True


def test_login_case_insensitive(engine, session):
    setor = make_setor(session, tipo="rh8")
    make_funcionario(session, "maria", "jose", setor.id)
    res = autenticar_funcionario(LoginRequest(username="MARIA.JOSE", senha="Test@123"))
    assert "token" in res


def test_login_gera_novo_token_a_cada_vez(engine, session):
    setor = make_setor(session, tipo="rh9")
    make_funcionario(session, "log", "duplo", setor.id)
    r1 = autenticar_funcionario(LoginRequest(username="log.duplo", senha="Test@123"))
    r2 = autenticar_funcionario(LoginRequest(username="log.duplo", senha="Test@123"))
    assert r1["token"] != r2["token"]


# ── criar_funcionario ─────────────────────────────────────────────────────────

def test_criar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="est")
    dados = _dados_create(setor.id)
    f = criar_funcionario(dados)
    assert f.id is not None
    assert f.cpf == "52998224725"
    assert f.email == "joao@test.com"


def test_criar_funcionario_sem_senha(engine, session):
    setor = make_setor(session, tipo="est2")
    dados = _dados_create(setor.id, senha=None)
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "Senha" in exc.value.detail


def test_criar_funcionario_cpf_duplicado(engine, session):
    setor = make_setor(session, tipo="est3")
    make_funcionario(session, cpf="52998224725", email="a@test.com", setor_id=setor.id)
    dados = _dados_create(setor.id, cpf="52998224725", email="b@test.com")
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "CPF" in exc.value.detail


def test_criar_funcionario_email_duplicado(engine, session):
    setor = make_setor(session, tipo="est4")
    make_funcionario(session, cpf="11144477735", email="dup@test.com", setor_id=setor.id)
    dados = _dados_create(setor.id, cpf="52998224725", email="dup@test.com")
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "Email" in exc.value.detail


def test_criar_funcionario_registra_historico(engine, session):
    setor = make_setor(session, tipo="est5")
    dados = _dados_create(setor.id, cpf="52998224725", email="hist@test.com")
    f = criar_funcionario(dados)
    with Session(engine) as s:
        hist = s.exec(
            __import__("sqlmodel").select(HistoricoSenha).where(HistoricoSenha.funcionario_id == f.id)
        ).all()
    assert len(hist) == 1


def test_criar_funcionario_erro_interno(engine, session):
    setor = make_setor(session, tipo="est6")
    dados = _dados_create(setor.id, cpf="52998224725", email="err@test.com")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            criar_funcionario(dados)
        assert exc.value.status_code == 500


# ── listar / buscar ───────────────────────────────────────────────────────────

def test_listar_funcionarios_vazio(engine, session):
    assert listar_funcionarios() == []


def test_listar_funcionarios_multiplos(engine, session):
    setor = make_setor(session, tipo="lst")
    make_funcionario(session, setor_id=setor.id)
    make_funcionario(session, setor_id=setor.id)
    assert len(listar_funcionarios()) == 2


def test_buscar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="bsc")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = buscar_funcionario(f.id)
    assert resultado.id == f.id


def test_buscar_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_funcionario(9999)
    assert exc.value.status_code == 404


# ── atualizar_funcionario ─────────────────────────────────────────────────────

def test_atualizar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="upd")
    f = make_funcionario(session, nome="Antigo", setor_id=setor.id, cpf="52998224725", email="old@test.com")
    dados = FuncionarioCreate(
        nome="Novo", sobrenome="Silva",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha=None,
        cpf="52998224725", email="new@test.com", **ENDERECO,
    )
    resultado = atualizar_funcionario(f.id, dados)
    assert resultado.nome == "Novo"
    assert resultado.email == "new@test.com"


def test_atualizar_sem_senha_mantem_hash(engine, session):
    setor = make_setor(session, tipo="upd2")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="keep@test.com")
    hash_original = f.password_hash
    dados = _dados_create(setor.id, cpf="52998224725", email="keep@test.com", senha=None)
    atualizar_funcionario(f.id, dados)
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.password_hash == hash_original


def test_atualizar_com_nova_senha(engine, session):
    setor = make_setor(session, tipo="upd3")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="chg@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="chg@test.com", senha="Nova@123456")
    atualizar_funcionario(f.id, dados)
    res = autenticar_funcionario(LoginRequest(username="joao.silva", senha="Nova@123456"))
    assert "token" in res


def test_atualizar_funcionario_inexistente(engine, session):
    setor = make_setor(session, tipo="upd4")
    dados = _dados_create(setor.id)
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(9999, dados)
    assert exc.value.status_code == 404


def test_atualizar_cpf_duplicado_outro_funcionario(engine, session):
    setor = make_setor(session, tipo="upd5")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="a@test.com")
    f2 = make_funcionario(session, setor_id=setor.id, cpf="11144477735", email="b@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="b@test.com")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f2.id, dados)
    assert exc.value.status_code == 400
    assert "CPF" in exc.value.detail


def test_atualizar_email_duplicado_outro_funcionario(engine, session):
    setor = make_setor(session, tipo="upd6")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="dup@test.com")
    f2 = make_funcionario(session, setor_id=setor.id, cpf="11144477735", email="b@test.com")
    dados = _dados_create(setor.id, cpf="11144477735", email="dup@test.com")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f2.id, dados)
    assert exc.value.status_code == 400
    assert "Email" in exc.value.detail


def test_atualizar_senha_historico_bloqueado(engine, session):
    setor = make_setor(session, tipo="upd7")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="hist2@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="hist2@test.com", senha="Test@123")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f.id, dados)
    assert exc.value.status_code == 400
    assert "últimas senhas" in exc.value.detail


def test_atualizar_erro_interno(engine, session):
    setor = make_setor(session, tipo="upd8")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="interr@test.com")
    dados = FuncionarioCreate(
        nome="X", sobrenome="Y",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha=None,
        cpf="52998224725", email="interr@test.com", **ENDERECO,
    )
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            atualizar_funcionario(f.id, dados)
        assert exc.value.status_code == 500


# ── deletar_funcionario ───────────────────────────────────────────────────────

def test_deletar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="del")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = deletar_funcionario(f.id)
    assert "deletado" in resultado["msg"]


def test_deletar_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        deletar_funcionario(9999)
    assert exc.value.status_code == 404


def test_deletar_funcionario_duas_vezes(engine, session):
    setor = make_setor(session, tipo="del2")
    f = make_funcionario(session, setor_id=setor.id)
    deletar_funcionario(f.id)
    with pytest.raises(HTTPException) as exc:
        deletar_funcionario(f.id)
    assert exc.value.status_code == 404


def test_deletar_erro_interno(engine, session):
    setor = make_setor(session, tipo="del3")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            deletar_funcionario(f.id)
        assert exc.value.status_code == 500


# ── renovar_token ─────────────────────────────────────────────────────────────

def test_renovar_token_sucesso(engine, session):
    setor = make_setor(session, tipo="ren")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = renovar_token(f.id)
    assert "token" in resultado
    assert isinstance(resultado["token"], str)


def test_renovar_token_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        renovar_token(9999)
    assert exc.value.status_code == 404


def test_renovar_token_erro_interno(engine, session):
    setor = make_setor(session, tipo="ren2")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            renovar_token(f.id)
        assert exc.value.status_code == 500


# ── trocar_senha ──────────────────────────────────────────────────────────────

def test_trocar_senha_sucesso(engine, session):
    setor = make_setor(session, tipo="troca")
    f = make_funcionario(session, setor_id=setor.id)
    dados = TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaSenha@999")
    resultado = trocar_senha(f.id, dados)
    assert "sucesso" in resultado["msg"]


def test_trocar_senha_atual_errada(engine, session):
    setor = make_setor(session, tipo="troca2")
    f = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Errada@123", nova_senha="Nova@999"))
    assert exc.value.status_code == 401


def test_trocar_senha_reutilizacao_bloqueada(engine, session):
    setor = make_setor(session, tipo="troca3")
    f = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Test@123"))
    assert exc.value.status_code == 400
    assert "últimas senhas" in exc.value.detail


def test_trocar_senha_historico_tres_ultimas(engine, session):
    setor = make_setor(session, tipo="troca4")
    f = make_funcionario(session, setor_id=setor.id)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Segunda@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Segunda@999", nova_senha="Terceira@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Terceira@999", nova_senha="Quarta@999"))
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Quarta@999", nova_senha="Segunda@999"))
    assert exc.value.status_code == 400


def test_trocar_senha_depois_de_quatro_trocas_permite_primeira(engine, session):
    setor = make_setor(session, tipo="troca5")
    f = make_funcionario(session, setor_id=setor.id)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Segunda@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Segunda@999", nova_senha="Terceira@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Terceira@999", nova_senha="Quarta@999"))
    resultado = trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Quarta@999", nova_senha="Test@123"))
    assert "sucesso" in resultado["msg"]


def test_trocar_senha_marca_temporaria_false(engine, session):
    setor = make_setor(session, tipo="troca6")
    f = make_funcionario(session, setor_id=setor.id, senha_temporaria=True)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Nova@99999"))
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.senha_temporaria is False


def test_trocar_senha_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        trocar_senha(9999, TrocarSenhaRequest(senha_atual="x", nova_senha="y"))
    assert exc.value.status_code == 404


def test_trocar_senha_erro_interno(engine, session):
    setor = make_setor(session, tipo="troca7")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Nova@99999"))
        assert exc.value.status_code == 500


# ── recuperar_senha ───────────────────────────────────────────────────────────

def test_recuperar_senha_sucesso(engine, session):
    setor = make_setor(session, tipo="rec")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec@test.com")

    with patch("repository.funcionarios.enviar_email") as mock_email:
        resultado = recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    mock_email.assert_called_once()
    assert "enviada" in resultado["msg"]


def test_recuperar_senha_marca_temporaria(engine, session):
    setor = make_setor(session, tipo="rec2")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec2@test.com")
    with patch("repository.funcionarios.enviar_email"):
        recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.senha_temporaria is True


def test_recuperar_senha_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        recuperar_senha(RecuperarSenhaRequest(cpf="00000000000"))
    assert exc.value.status_code == 404


def test_recuperar_senha_sem_email(engine, session):
    setor = make_setor(session, tipo="rec3")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec3@test.com")
    with Session(engine) as s:
        func = s.get(type(f), f.id)
        func.email = None
        s.add(func)
        s.commit()
    with pytest.raises(HTTPException) as exc:
        recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 400


def test_recuperar_senha_email_nao_configurado(engine, session):
    setor = make_setor(session, tipo="rec4")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec4@test.com")
    with patch("repository.funcionarios.enviar_email", side_effect=RuntimeError("não configurado")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 503


def test_recuperar_senha_erro_smtp(engine, session):
    setor = make_setor(session, tipo="rec5")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec5@test.com")
    with patch("repository.funcionarios.enviar_email", side_effect=Exception("SMTP Error")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 500


def test_recuperar_senha_erro_db(engine, session):
    setor = make_setor(session, tipo="rec6")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec6@test.com")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 500


# ── helpers internos ──────────────────────────────────────────────────────────

def test_senha_ja_usada_true(engine, session):
    setor = make_setor(session, tipo="hlp")
    f = make_funcionario(session, setor_id=setor.id)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "Test@123") is True


def test_senha_ja_usada_false(engine, session):
    setor = make_setor(session, tipo="hlp2")
    f = make_funcionario(session, setor_id=setor.id)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "SenhaNova@999") is False


def test_senha_ja_usada_sem_historico(engine, session):
    setor = make_setor(session, tipo="hlp3")
    f = make_funcionario(session, setor_id=setor.id, with_password=False)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "Qualquer@123") is False
