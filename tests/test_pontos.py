from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from repository.pontos import (
    bater_ponto, status_hoje, relatorio_funcionario, relatorio_geral,
    _calcular_horas_dia, _proximo_marco,
)
from utils.database import Ponto, Salario
from conftest import make_setor, make_funcionario, set_token


def make_ponto(session, funcionario_id, dia, entrada=None, saida_almoco=None, retorno_almoco=None, saida=None):
    p = Ponto(
        funcionario_id=funcionario_id, data=dia,
        entrada=entrada, saida_almoco=saida_almoco, retorno_almoco=retorno_almoco, saida=saida,
    )
    if entrada and saida:
        _calcular_horas_dia(p)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def make_salario(session, funcionario_id, valor_mensal):
    s = Salario(
        funcionario_id=funcionario_id,
        valor_mensal=Decimal(str(valor_mensal)),
        valor_hora=Decimal(str(valor_mensal)) / Decimal("220"),
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def test_proximo_marco_sequencia():
    p = Ponto(funcionario_id=1, data=date.today())
    assert _proximo_marco(p) == "entrada"
    p.entrada = datetime.now(timezone.utc)
    assert _proximo_marco(p) == "saida_almoco"
    p.saida_almoco = datetime.now(timezone.utc)
    assert _proximo_marco(p) == "retorno_almoco"
    p.retorno_almoco = datetime.now(timezone.utc)
    assert _proximo_marco(p) == "saida"
    p.saida = datetime.now(timezone.utc)
    assert _proximo_marco(p) is None


def test_bater_ponto_sequencia_completa(engine, session):
    setor = make_setor(session, tipo="estoque_pt1")
    f = make_funcionario(session, setor_id=setor.id)

    for marco in ("entrada", "saida_almoco", "retorno_almoco", "saida"):
        res = bater_ponto(f.id)
        assert "registrado" in res["detail"].lower()

    with Session(engine) as s:
        ponto = s.exec(select(Ponto).where(Ponto.funcionario_id == f.id)).first()
    assert ponto.entrada is not None
    assert ponto.saida_almoco is not None
    assert ponto.retorno_almoco is not None
    assert ponto.saida is not None


def test_bater_ponto_quinta_vez_erro_400(engine, session):
    setor = make_setor(session, tipo="estoque_pt2")
    f = make_funcionario(session, setor_id=setor.id)

    for _ in range(4):
        bater_ponto(f.id)

    with pytest.raises(HTTPException) as exc:
        bater_ponto(f.id)
    assert exc.value.status_code == 400


def test_calcular_horas_dia_exato_sem_extra_nem_devida():
    hoje = date.today()
    p = Ponto(
        funcionario_id=1, data=hoje,
        entrada=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
        saida_almoco=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        retorno_almoco=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 1, 5, 17, 0, tzinfo=timezone.utc),
    )
    _calcular_horas_dia(p)
    assert p.horas_trabalhadas == Decimal("8.00")
    assert p.horas_extras == Decimal("0.00")
    assert p.horas_devidas == Decimal("0.00")


def test_calcular_horas_dia_com_extra():
    p = Ponto(
        funcionario_id=1, data=date.today(),
        entrada=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
        saida_almoco=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        retorno_almoco=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 1, 5, 19, 0, tzinfo=timezone.utc),
    )
    _calcular_horas_dia(p)
    assert p.horas_trabalhadas == Decimal("10.00")
    assert p.horas_extras == Decimal("2.00")
    assert p.horas_devidas == Decimal("0.00")


def test_calcular_horas_dia_com_devida():
    p = Ponto(
        funcionario_id=1, data=date.today(),
        entrada=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
        saida_almoco=datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc),
        retorno_almoco=datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 1, 5, 16, 0, tzinfo=timezone.utc),
    )
    _calcular_horas_dia(p)
    assert p.horas_trabalhadas == Decimal("7.00")
    assert p.horas_extras == Decimal("0.00")
    assert p.horas_devidas == Decimal("1.00")


def test_calcular_horas_dia_sem_saida_nao_calcula():
    p = Ponto(
        funcionario_id=1, data=date.today(),
        entrada=datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc),
    )
    _calcular_horas_dia(p)
    assert p.horas_trabalhadas == Decimal("0.00")
    assert p.horas_extras == Decimal("0.00")
    assert p.horas_devidas == Decimal("0.00")


def test_status_hoje_sem_registro_devolve_vazio(engine, session):
    setor = make_setor(session, tipo="estoque_pt3")
    f = make_funcionario(session, setor_id=setor.id)
    status = status_hoje(f.id)
    assert status.entrada is None
    assert status.saida is None


def test_status_hoje_com_registro(engine, session):
    setor = make_setor(session, tipo="estoque_pt4")
    f = make_funcionario(session, setor_id=setor.id)
    bater_ponto(f.id)
    status = status_hoje(f.id)
    assert status.entrada is not None
    assert status.saida is None


def test_meu_relatorio_resumo_agregado(engine, session):
    setor = make_setor(session, tipo="estoque_pt5")
    f = make_funcionario(session, setor_id=setor.id)
    make_salario(session, f.id, 2200)  # valor_hora = 10.00

    make_ponto(
        session, f.id, date(2026, 3, 2),
        entrada=datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc),
        saida_almoco=datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc),
        retorno_almoco=datetime(2026, 3, 2, 13, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 3, 2, 19, 0, tzinfo=timezone.utc),  # 10h -> 2h extra
    )
    make_ponto(
        session, f.id, date(2026, 3, 3),
        entrada=datetime(2026, 3, 3, 8, 0, tzinfo=timezone.utc),
        saida_almoco=datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
        retorno_almoco=datetime(2026, 3, 3, 13, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 3, 3, 16, 0, tzinfo=timezone.utc),  # 7h -> 1h devida
    )
    # Fora do mês de março -- não deve entrar no resumo.
    make_ponto(
        session, f.id, date(2026, 4, 1),
        entrada=datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 4, 1, 16, 0, tzinfo=timezone.utc),
    )

    relatorio = relatorio_funcionario(f.id, 3, 2026)
    assert relatorio.funcionario == f"{f.nome} {f.sobrenome}"
    assert len(relatorio.pontos) == 2
    assert relatorio.resumo.total_trabalhado_mes == Decimal("17.00")
    assert relatorio.resumo.total_extra_mes == Decimal("2.00")
    assert relatorio.resumo.total_devido_mes == Decimal("1.00")
    assert relatorio.resumo.saldo_mensal == Decimal("1.00")
    # dia 1: 8h normais (10.00/h) + 2h extra (10.00*1.5) = 80 + 30 = 110
    # dia 2: 7h normais = 70
    assert relatorio.resumo.total_a_receber == Decimal("180.00")


def test_meu_relatorio_sem_salario_valor_zero(engine, session):
    setor = make_setor(session, tipo="estoque_pt6")
    f = make_funcionario(session, setor_id=setor.id)
    make_ponto(
        session, f.id, date(2026, 3, 2),
        entrada=datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 3, 2, 16, 0, tzinfo=timezone.utc),
    )
    relatorio = relatorio_funcionario(f.id, 3, 2026)
    assert relatorio.resumo.total_a_receber == Decimal("0.00")


def test_meu_relatorio_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        relatorio_funcionario(9999, 3, 2026)
    assert exc.value.status_code == 404


def test_relatorio_geral_junta_nome_funcionario(engine, session):
    setor = make_setor(session, tipo="estoque_pt7")
    f1 = make_funcionario(session, nome="Ana", sobrenome="Souza", setor_id=setor.id)
    f2 = make_funcionario(session, nome="Bruno", sobrenome="Lima", setor_id=setor.id)

    make_ponto(
        session, f1.id, date(2026, 5, 10),
        entrada=datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 5, 10, 16, 0, tzinfo=timezone.utc),
    )
    make_ponto(
        session, f2.id, date(2026, 5, 10),
        entrada=datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc),
        saida=datetime(2026, 5, 10, 16, 0, tzinfo=timezone.utc),
    )

    geral = relatorio_geral(5, 2026)
    nomes = {item.funcionario for item in geral}
    assert nomes == {"Ana Souza", "Bruno Lima"}


def test_rh_geral_bloqueado_para_outro_setor(client, session):
    setor = make_setor(session, tipo="vendas_pt1")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    client.headers.update({"Authorization": f"Bearer {token}"})

    res = client.get("/pontos/rh/geral", params={"mes": 1, "ano": 2026})
    assert res.status_code == 403


def test_rh_funcionario_bloqueado_para_outro_setor(client, session):
    setor = make_setor(session, tipo="vendas_pt2")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    client.headers.update({"Authorization": f"Bearer {token}"})

    res = client.get(f"/pontos/rh/funcionario/{func.id}", params={"mes": 1, "ano": 2026})
    assert res.status_code == 403


def test_bater_ponto_rota(client, session):
    res = client.post("/pontos/bater")
    assert res.status_code == 200
    assert "registrado" in res.json()["detail"].lower()


# ── proteção de concorrência (achado do painel de revisão) ──────────────────

def test_ponto_unique_constraint_impede_duplicata(engine, session):
    """Prova que a UniqueConstraint(funcionario_id, data) está de verdade
    ativa no banco -- não só declarada no modelo. Sem ela, duas linhas de
    Ponto pro mesmo funcionário/dia inflariam horas em relatório/folha."""
    setor = make_setor(session, tipo="estoque_pt_uq")
    f = make_funcionario(session, setor_id=setor.id)
    hoje = date.today()
    make_ponto(session, f.id, hoje, entrada=datetime.now(timezone.utc))

    duplicata = Ponto(funcionario_id=f.id, data=hoje, entrada=datetime.now(timezone.utc))
    session.add(duplicata)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_bater_ponto_corrida_concorrente_vira_409(engine, session, monkeypatch):
    """Simula a janela de corrida real: a SELECT de 'existe Ponto hoje?'
    dentro de bater_ponto não enxerga um Ponto que JÁ existe (pretende ser
    o resultado de outra requisição concorrente que ainda não tinha
    commitado quando este SELECT rodou) -- ao tentar INSERIR, a
    UniqueConstraint rejeita, e bater_ponto precisa converter isso num 409
    claro, não deixar o IntegrityError escapar cru como 500."""
    setor = make_setor(session, tipo="estoque_pt_race")
    f = make_funcionario(session, setor_id=setor.id)
    hoje = date.today()
    # "Outra requisição" que já criou o Ponto de hoje antes desta chamada
    # tentar inserir o dela.
    make_ponto(session, f.id, hoje, entrada=datetime.now(timezone.utc))

    exec_original = Session.exec

    def exec_forcando_ponto_nao_encontrado(self, statement, *args, **kwargs):
        descricoes = getattr(statement, "column_descriptions", [])
        eh_consulta_de_ponto = any(col.get("entity") is Ponto for col in descricoes)
        if eh_consulta_de_ponto:
            class _ResultadoVazio:
                def first(self_inner):
                    return None
            return _ResultadoVazio()
        return exec_original(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "exec", exec_forcando_ponto_nao_encontrado)

    with pytest.raises(HTTPException) as exc:
        bater_ponto(f.id)
    assert exc.value.status_code == 409
