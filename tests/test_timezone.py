"""
Testes do utilitário de fuso horário (utils/timezone.py).

O mercado fica em Teresina-PI (America/Sao_Paulo, UTC-3, sem horário de
verão desde 2019). O banco grava tudo em UTC, mas "qual é o dia" para fins
de negócio (vendas do dia, relatórios, fechamento de caixa) precisa ser
calculado no horário local. Sem isso, a partir das ~21h em Brasília (quando
em UTC já é o dia seguinte) o sistema passaria a considerar "hoje" como
sendo amanhã.
"""
from datetime import date, datetime, timezone

from utils.timezone import FUSO_BRASIL, agora_brasil, hoje_brasil, limites_do_dia_brasil


def _fixar_agora(monkeypatch, instante_utc):
    """Congela utils.timezone.datetime.now() no instante UTC informado."""
    import utils.timezone as tz_mod

    class DataHoraFixa(datetime):
        @classmethod
        def now(cls, tz=None):
            return instante_utc if tz is None else instante_utc.astimezone(tz)

    monkeypatch.setattr(tz_mod, "datetime", DataHoraFixa)


def test_hoje_brasil_durante_a_manha_mesmo_dia_em_utc(monkeypatch):
    # 09h00 em Brasília == 12h00 UTC do mesmo dia civil.
    _fixar_agora(monkeypatch, datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc))
    assert hoje_brasil() == date(2026, 6, 15)


def test_hoje_brasil_as_21h_brt_ainda_e_o_mesmo_dia(monkeypatch):
    # 21h00 em Brasília (UTC-3) == 00h00 UTC do dia SEGUINTE.
    # Esse é exatamente o horário em que o cálculo baseado em UTC quebrava.
    _fixar_agora(monkeypatch, datetime(2026, 6, 16, 0, 0, tzinfo=timezone.utc))
    assert hoje_brasil() == date(2026, 6, 15)


def test_hoje_brasil_as_23h59_brt_ainda_e_o_mesmo_dia(monkeypatch):
    # 23h59 em Brasília == 02h59 UTC do dia seguinte.
    _fixar_agora(monkeypatch, datetime(2026, 6, 16, 2, 59, tzinfo=timezone.utc))
    assert hoje_brasil() == date(2026, 6, 15)


def test_hoje_brasil_a_meia_noite_brt_vira_o_novo_dia(monkeypatch):
    # 00h00 em Brasília == 03h00 UTC do mesmo dia civil brasileiro.
    _fixar_agora(monkeypatch, datetime(2026, 6, 16, 3, 0, tzinfo=timezone.utc))
    assert hoje_brasil() == date(2026, 6, 16)


def test_agora_brasil_fica_3_horas_atras_de_utc(monkeypatch):
    _fixar_agora(monkeypatch, datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc))
    agora = agora_brasil()
    assert agora.tzinfo is not None
    assert agora.hour == 12
    assert agora.date() == date(2026, 6, 15)


def test_limites_do_dia_brasil_intervalo_correto_em_utc():
    inicio_utc, fim_utc = limites_do_dia_brasil(date(2026, 6, 15))

    # 00h00 de 15/06 em Brasília == 03h00 UTC do mesmo dia.
    assert inicio_utc == datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc)
    # 00h00 de 16/06 em Brasília (início do dia seguinte) == 03h00 UTC do dia 16.
    assert fim_utc == datetime(2026, 6, 16, 3, 0, tzinfo=timezone.utc)


def test_limites_do_dia_brasil_sao_exclusivos_no_limite_superior():
    _, fim_utc = limites_do_dia_brasil(date(2026, 6, 15))
    # Uma venda feita exatamente no instante de virada do dia (00h00 BRT do
    # dia 16) não pode contar como "dia 15".
    assert fim_utc == datetime(2026, 6, 16, 3, 0, tzinfo=timezone.utc)


def test_limites_do_dia_brasil_usa_hoje_quando_omitido(monkeypatch):
    _fixar_agora(monkeypatch, datetime(2026, 6, 16, 0, 30, tzinfo=timezone.utc))
    inicio_utc, fim_utc = limites_do_dia_brasil()
    assert inicio_utc == datetime(2026, 6, 15, 3, 0, tzinfo=timezone.utc)
    assert fim_utc == datetime(2026, 6, 16, 3, 0, tzinfo=timezone.utc)
