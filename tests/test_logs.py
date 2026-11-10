import pytest
from logs.logs import criar_log, listar_logs
from conftest import make_setor, make_funcionario


def test_listar_logs_vazio(engine, session):
    assert listar_logs() == []


def test_criar_log_sucesso(engine, session):
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    criar_log(func.id, "teste de log")
    logs = listar_logs()
    assert len(logs) == 1
    assert logs[0].tipo_movimentacao == "teste de log"
    assert logs[0].funcionario_id == func.id


def test_criar_varios_logs(engine, session):
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    criar_log(func.id, "acao 1")
    criar_log(func.id, "acao 2")
    criar_log(func.id, "acao 3")
    assert len(listar_logs()) == 3


def test_log_preserva_funcionario_id(engine, session):
    setor = make_setor(session)
    f1 = make_funcionario(session, setor_id=setor.id)
    f2 = make_funcionario(session, setor_id=setor.id)
    criar_log(f1.id, "f1")
    criar_log(f2.id, "f2")
    ids = {l.funcionario_id for l in listar_logs()}
    assert f1.id in ids and f2.id in ids


def test_log_data_hora_preenchida(engine, session):
    from datetime import datetime
    setor = make_setor(session)
    func = make_funcionario(session, setor_id=setor.id)
    criar_log(func.id, "check data")
    log = listar_logs()[0]
    assert isinstance(log.data_hora, datetime)
