"""Utilidades para valores monetários.

O banco usa DECIMAL(10,2) em todas as colunas de dinheiro, mas o código em
Python vinha usando `float` para representar os mesmos valores. Isso é uma
fonte clássica de erro de arredondamento (ex.: 0.1 + 0.2 != 0.3 em binário).
Este módulo centraliza a conversão segura para `Decimal` e o arredondamento
para 2 casas usando ROUND_HALF_UP (o mesmo comportamento esperado em
dinheiro: 0.005 arredonda para 0.01, nunca para 0.00).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated, Union

from pydantic import PlainSerializer

Numero = Union[int, float, str, Decimal]

DUAS_CASAS = Decimal("0.01")

# Tipo para usar nos campos monetários dos modelos (SQLModel) e schemas
# (Pydantic): guarda e calcula tudo como Decimal (sem erro de ponto
# flutuante), mas ao serializar para JSON (respostas da API) converte para
# float, preservando o contrato que o frontend já consome (número, não
# string) -- por padrão, o Pydantic v2 serializa Decimal como string em
# modo JSON, o que quebraria o frontend sem necessidade.
DecimalMoeda = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


def to_decimal(valor: Numero) -> Decimal:
    """Converte int/float/str/Decimal para Decimal de forma segura.

    Floats são convertidos via `str()` (não diretamente), porque
    `Decimal(0.1)` carrega o erro de representação binária do float
    (0.1000000000000000055511151231257827021181583404541015625), enquanto
    `Decimal(str(0.1))` resulta em `Decimal('0.1')`, que é o que o usuário
    de fato digitou/esperava.
    """
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def arredondar(valor: Numero) -> Decimal:
    """Arredonda um valor monetário para 2 casas decimais (ROUND_HALF_UP)."""
    return to_decimal(valor).quantize(DUAS_CASAS, rounding=ROUND_HALF_UP)
