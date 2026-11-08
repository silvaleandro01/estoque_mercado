"""Utilidades de fuso horário.

O banco de dados continua gravando tudo em UTC (como já era feito). O que
muda aqui é a definição de "dia" para fins de negócio (vendas do dia,
relatórios, fechamento de caixa, etc.): o mercado fica em Teresina-PI, então
o dia civil precisa ser calculado no fuso de Brasília (America/Sao_Paulo),
não em UTC. Sem isso, a partir de ~21h/22h no horário local (quando já é
00h/01h em UTC) as vendas feitas "hoje" passam a ser contadas como "ontem"
ou simplesmente não entram no corte do dia.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def agora_brasil() -> datetime:
    """Instante atual (aware) convertido para o fuso horário de Brasília."""
    return datetime.now(timezone.utc).astimezone(FUSO_BRASIL)


def hoje_brasil() -> date:
    """Data civil atual considerando o fuso horário de Brasília."""
    return agora_brasil().date()


def limites_do_dia_brasil(dia: Optional[date] = None) -> Tuple[datetime, datetime]:
    """
    Retorna o intervalo [inicio, fim) em UTC que corresponde ao dia civil
    informado (ou ao dia atual, se omitido) no fuso horário de Brasília.

    O limite superior é exclusivo (início do dia seguinte), para que
    comparações no banco sejam sempre `inicio <= data < fim`.
    """
    if dia is None:
        dia = hoje_brasil()
    inicio_local = datetime.combine(dia, time.min, tzinfo=FUSO_BRASIL)
    fim_local = inicio_local + timedelta(days=1)
    return inicio_local.astimezone(timezone.utc), fim_local.astimezone(timezone.utc)
