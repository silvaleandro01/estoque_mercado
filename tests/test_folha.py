from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from repository.folha import (
    fechar_folha, meu_holerite, buscar_holerite, assinar_holerite,
    _calcular_inss, _calcular_irpf,
)
from repository.funcionarios import definir_salario, salario_historico
from utils.database import Holerite
from utils.money import arredondar
from conftest import make_setor, make_funcionario, set_token
from tests.test_pontos import make_ponto, make_salario


# ── _calcular_inss / _calcular_irpf (tabelas progressivas) ──────────────────

def test_calcular_inss_dentro_da_primeira_faixa():
    assert _calcular_inss(Decimal("1000.00")) == Decimal("75.00")


def test_calcular_inss_no_teto_da_primeira_faixa():
    assert _calcular_inss(Decimal("1412.00")) == Decimal("105.90")


def test_calcular_inss_progressivo_segunda_faixa():
    esperado = arredondar(Decimal("1412.00") * Decimal("0.075") + Decimal("588.00") * Decimal("0.09"))
    assert _calcular_inss(Decimal("2000.00")) == esperado


def test_calcular_inss_limitado_ao_teto():
    valor_no_teto = _calcular_inss(Decimal("7786.02"))
    assert valor_no_teto > Decimal("0.00")
    assert _calcular_inss(Decimal("50000.00")) == valor_no_teto


def test_calcular_irpf_isento():
    assert _calcular_irpf(Decimal("2000.00")) == Decimal("0.00")


def test_calcular_irpf_primeira_faixa():
    esperado = arredondar(Decimal("2500.00") * Decimal("0.075") - Decimal("169.44"))
    assert _calcular_irpf(Decimal("2500.00")) == esperado


def test_calcular_irpf_acima_do_teto():
    esperado = arredondar(Decimal("10000.00") * Decimal("0.275") - Decimal("896.00"))
    assert _calcular_irpf(Decimal("10000.00")) == esperado


def test_calcular_irpf_nunca_negativo():
    assert _calcular_irpf(Decimal("2300.00")) >= Decimal("0.00")


# ── fechar_folha ─────────────────────────────────────────────────────────────

def _dias_uteis(mes, ano, limite=None):
    """Mesma lógica de folha.py::_dias_uteis_mes, mas devolve a LISTA de dias
    (não só a contagem) -- usado pelos testes pra bater ponto só em dias que
    o próprio sistema considera "dia útil", sem reimplementar outra regra."""
    from calendar import monthrange
    total = monthrange(ano, mes)[1]
    dias = [d for d in range(1, total + 1) if date(ano, mes, d).weekday() < 5]
    return dias if limite is None else dias[:limite]


def _bater_dias(session, funcionario_id, mes, ano, dias, saida_hora=17):
    for dia in dias:
        make_ponto(
            session, funcionario_id, date(ano, mes, dia),
            entrada=datetime(ano, mes, dia, 8, 0, tzinfo=timezone.utc),
            saida_almoco=datetime(ano, mes, dia, 12, 0, tzinfo=timezone.utc),
            retorno_almoco=datetime(ano, mes, dia, 13, 0, tzinfo=timezone.utc),
            saida=datetime(ano, mes, dia, saida_hora, 0, tzinfo=timezone.utc),
        )


def test_fechar_folha_frequencia_perfeita_paga_salario_cheio(engine, session):
    """Achado do painel de revisão: a versão anterior dividia por 30 dias
    corridos, então mesmo frequência perfeita pagava só ~73% do nominal
    (dias úteis nunca chegam a 30). Bate ponto em TODOS os dias úteis do
    mês -- salario_base precisa sair igual ao valor_mensal cheio."""
    setor = make_setor(session, tipo="estoque_fl1")
    f = make_funcionario(session, setor_id=setor.id)
    make_salario(session, f.id, 3000)  # valor_hora = 3000/220

    dias_uteis_junho = _dias_uteis(6, 2026)
    _bater_dias(session, f.id, 6, 2026, dias_uteis_junho)  # 8h exatas, sem extra/devida

    res = fechar_folha(6, 2026, f.id)
    assert "1 funcionário" in res["detail"]

    holerite = meu_holerite(f.id, 6, 2026)
    assert holerite is not None
    assert holerite.dias_trabalhados == len(dias_uteis_junho)
    assert holerite.salario_base == Decimal("3000.00")  # frequência perfeita == salário cheio
    assert holerite.horas_extras_valor == Decimal("0.00")
    assert holerite.valor_bruto == holerite.salario_base
    assert holerite.fgts == arredondar(holerite.valor_bruto * Decimal("0.08"))
    assert holerite.vale_transporte == arredondar(holerite.salario_base * Decimal("0.06"))
    assert holerite.inss == _calcular_inss(holerite.valor_bruto)
    assert holerite.irpf == _calcular_irpf(arredondar(holerite.valor_bruto - holerite.inss))
    # Campos sem regra definida nesta versão -- sempre zero.
    assert holerite.ajuda_custo == Decimal("0.00")
    assert holerite.adiantamento == Decimal("0.00")
    assert holerite.contribuicao_assistencial == Decimal("0.00")
    assert holerite.vale_refeicao == Decimal("0.00")
    esperado_liquido = arredondar(
        holerite.valor_bruto - holerite.inss - holerite.irpf - holerite.vale_transporte
    )
    assert holerite.valor_liquido == esperado_liquido
    assert holerite.assinado is False


def test_fechar_folha_falta_real_reduz_proporcionalmente(engine, session):
    """Faltou metade dos dias úteis do mês -- salario_base precisa cair
    pela metade (não mais por 1/30 cada falta, que distorcia o impacto de
    faltas reais)."""
    setor = make_setor(session, tipo="estoque_fl1b")
    f = make_funcionario(session, setor_id=setor.id)
    make_salario(session, f.id, 3000)

    dias_uteis_junho = _dias_uteis(6, 2026)
    metade = dias_uteis_junho[: len(dias_uteis_junho) // 2]
    _bater_dias(session, f.id, 6, 2026, metade)

    holerite_antes = fechar_folha(6, 2026, f.id)
    assert "1 funcionário" in holerite_antes["detail"]
    holerite = meu_holerite(f.id, 6, 2026)
    assert holerite.dias_trabalhados == len(metade)
    assert holerite.salario_base == arredondar(
        Decimal("3000.00") * Decimal(len(metade)) / Decimal(len(dias_uteis_junho))
    )
    assert holerite.salario_base < Decimal("3000.00")


def test_fechar_folha_desconta_horas_devidas(engine, session):
    """Simétrico à hora extra: um dia incompleto (saiu 2h mais cedo) desconta
    o valor dessas horas do bruto -- não fica só informativo no holerite."""
    setor = make_setor(session, tipo="estoque_fl1c")
    f = make_funcionario(session, setor_id=setor.id)
    make_salario(session, f.id, 2200)  # valor_hora = 10.00

    dias_uteis_junho = _dias_uteis(6, 2026)
    _bater_dias(session, f.id, 6, 2026, dias_uteis_junho[:1], saida_hora=15)  # 6h -> 2h devida

    fechar_folha(6, 2026, f.id)
    holerite = meu_holerite(f.id, 6, 2026)
    salario_base_esperado = arredondar(
        Decimal("2200.00") * Decimal("1") / Decimal(len(dias_uteis_junho))
    )
    assert holerite.horas_devidas == Decimal("2.00")
    # 2h devidas * R$10,00/h = R$20,00 descontados do bruto.
    assert holerite.valor_bruto == arredondar(salario_base_esperado - Decimal("20.00"))


def test_fechar_folha_idempotente(engine, session):
    setor = make_setor(session, tipo="estoque_fl2")
    f = make_funcionario(session, setor_id=setor.id)
    make_salario(session, f.id, 2000)
    _bater_dias(session, f.id, 7, 2026, _dias_uteis(7, 2026, limite=8))

    fechar_folha(7, 2026, f.id)
    fechar_folha(7, 2026, f.id)

    holerites = session.exec(
        select(Holerite).where(Holerite.funcionario_id == f.id, Holerite.mes == 7, Holerite.ano == 2026)
    ).all()
    assert len(holerites) == 1


def test_fechar_folha_ignora_quem_nao_bate_ponto(engine, session):
    setor = make_setor(session, tipo="estoque_fl3")
    f = make_funcionario(session, setor_id=setor.id)
    f.bate_ponto = False
    session.add(f)
    session.commit()
    make_salario(session, f.id, 2000)

    fechar_folha(8, 2026, f.id)

    assert meu_holerite(f.id, 8, 2026) is None


def test_fechar_folha_sem_pontos_sem_salario(engine, session):
    setor = make_setor(session, tipo="estoque_fl4")
    f = make_funcionario(session, setor_id=setor.id)

    res = fechar_folha(9, 2026, f.id)
    assert "1 funcionário" in res["detail"]

    holerite = meu_holerite(f.id, 9, 2026)
    assert holerite.dias_trabalhados == 0
    assert holerite.salario_base == Decimal("0.00")
    assert holerite.valor_bruto == Decimal("0.00")
    assert holerite.valor_liquido == Decimal("0.00")


# ── assinar_holerite ─────────────────────────────────────────────────────────

def test_assinar_holerite_dono_ok(engine, session):
    setor = make_setor(session, tipo="estoque_fl5")
    f = make_funcionario(session, setor_id=setor.id)
    fechar_folha(10, 2026, f.id)
    holerite = meu_holerite(f.id, 10, 2026)

    atualizado = assinar_holerite(holerite.id, f.id)
    assert atualizado.assinado is True
    assert atualizado.data_assinatura is not None


def test_assinar_holerite_outro_funcionario_403(engine, session):
    setor = make_setor(session, tipo="estoque_fl6")
    f = make_funcionario(session, setor_id=setor.id)
    outro = make_funcionario(session, setor_id=setor.id)
    fechar_folha(11, 2026, f.id)
    holerite = meu_holerite(f.id, 11, 2026)

    with pytest.raises(HTTPException) as exc:
        assinar_holerite(holerite.id, outro.id)
    assert exc.value.status_code == 403


def test_assinar_holerite_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        assinar_holerite(99999, 1)
    assert exc.value.status_code == 404


def test_assinar_holerite_idempotente(engine, session):
    setor = make_setor(session, tipo="estoque_fl7")
    f = make_funcionario(session, setor_id=setor.id)
    fechar_folha(12, 2026, f.id)
    holerite = meu_holerite(f.id, 12, 2026)

    primeira = assinar_holerite(holerite.id, f.id)
    segunda = assinar_holerite(holerite.id, f.id)
    assert primeira.data_assinatura == segunda.data_assinatura


# ── definir_salario / salario_historico ─────────────────────────────────────

def test_definir_salario_cria_registro_novo(engine, session):
    setor = make_setor(session, tipo="estoque_fl8")
    f = make_funcionario(session, setor_id=setor.id)

    definir_salario(f.id, Decimal("2200.00"), f.id)

    historico = salario_historico(f.id)
    assert historico == []  # primeira definição não gera histórico, só cria


def test_definir_salario_gera_historico_quando_muda(engine, session):
    setor = make_setor(session, tipo="estoque_fl9")
    f = make_funcionario(session, setor_id=setor.id)

    definir_salario(f.id, Decimal("2200.00"), f.id)
    definir_salario(f.id, Decimal("2500.00"), f.id)

    historico = salario_historico(f.id)
    assert len(historico) == 1
    assert historico[0].valor_antigo == Decimal("2200.00")
    assert historico[0].valor_novo == Decimal("2500.00")


def test_definir_salario_mesmo_valor_nao_duplica_historico(engine, session):
    setor = make_setor(session, tipo="estoque_fl10")
    f = make_funcionario(session, setor_id=setor.id)

    definir_salario(f.id, Decimal("2200.00"), f.id)
    definir_salario(f.id, Decimal("2200.00"), f.id)

    assert salario_historico(f.id) == []


# ── isolamento de permissão (RH/admin) via rota HTTP ─────────────────────────

def test_fechar_folha_bloqueado_para_outro_setor(client, session):
    setor = make_setor(session, tipo="vendas_fl1")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    client.headers.update({"Authorization": f"Bearer {token}"})

    res = client.post("/folha/fechar", json={"mes": 1, "ano": 2026})
    assert res.status_code == 403


def test_definir_salario_bloqueado_para_outro_setor(client, session):
    setor = make_setor(session, tipo="vendas_fl2")
    func = make_funcionario(session, setor_id=setor.id)
    token = set_token(session, func)
    client.headers.update({"Authorization": f"Bearer {token}"})

    res = client.post("/funcionarios/definir-salario", json={"funcionario_id": func.id, "valor": 2000.0})
    assert res.status_code == 403


def test_meu_holerite_404_quando_nao_fechado(client, session):
    res = client.get("/folha/meu-holerite", params={"mes": 1, "ano": 2026})
    assert res.status_code == 404


# ── proteção de concorrência (achado do painel de revisão) ──────────────────

def test_holerite_unique_constraint_impede_duplicata(engine, session):
    """Prova que a UniqueConstraint(funcionario_id, mes, ano) está de
    verdade ativa no banco -- sem ela, duas chamadas concorrentes de
    fechar_folha duplicavam o holerite do mesmo funcionário/mês."""
    setor = make_setor(session, tipo="estoque_fl_uq")
    f = make_funcionario(session, setor_id=setor.id)
    fechar_folha(1, 2026, f.id)

    duplicata = Holerite(
        funcionario_id=f.id, mes=1, ano=2026, data_competencia=date(2026, 1, 1),
    )
    session.add(duplicata)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_fechar_folha_corrida_concorrente_nao_duplica(engine, session, monkeypatch):
    """Simula a janela de corrida real: a verificação 'já existe holerite
    deste mês?' dentro de fechar_folha não enxerga um Holerite que JÁ existe
    (pretende ser outra chamada concorrente que ainda não tinha commitado
    quando esta verificação rodou) -- ao tentar INSERIR, a UniqueConstraint
    rejeita; fechar_folha precisa pular esse funcionário (via SAVEPOINT) em
    vez de deixar o IntegrityError derrubar a chamada inteira ou duplicar
    o registro."""
    setor = make_setor(session, tipo="estoque_fl_race")
    f = make_funcionario(session, setor_id=setor.id)
    # "Outra chamada" que já fechou a folha deste funcionário/mês.
    fechar_folha(2, 2026, f.id)

    exec_original = Session.exec

    def exec_forcando_holerite_nao_encontrado(self, statement, *args, **kwargs):
        descricoes = getattr(statement, "column_descriptions", [])
        eh_consulta_de_holerite = any(col.get("entity") is Holerite for col in descricoes)
        if eh_consulta_de_holerite:
            class _ResultadoVazio:
                def first(self_inner):
                    return None
            return _ResultadoVazio()
        return exec_original(self, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "exec", exec_forcando_holerite_nao_encontrado)

    res = fechar_folha(2, 2026, f.id)
    assert "0 funcionário" in res["detail"]
    assert "outra solicitação simultânea" in res["detail"]

    monkeypatch.undo()  # consulta final precisa do Session.exec de verdade
    holerites = session.exec(
        select(Holerite).where(Holerite.funcionario_id == f.id, Holerite.mes == 2, Holerite.ano == 2026)
    ).all()
    assert len(holerites) == 1  # continua só um -- não duplicou
