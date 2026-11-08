"""Utilidades para quantidades em estoque, vendas e compras.

A Fase 2 do projeto ("cadastro de produto completo") introduziu venda por
peso: produtos com unidade de medida KG ou L podem ser vendidos em frações
de unidade (ex.: 0.350 kg), então `quantidade` deixou de ser sempre um
número inteiro de peças. O banco guarda essas colunas como DECIMAL(10, 3)
-- 3 casas decimais, suficiente para precisão de grama/mililitro --,
diferente do DECIMAL(10, 2) já usado para dinheiro em `utils/money.py`.

Este módulo espelha o padrão de `money.py` (Decimal seguro + arredondamento
ROUND_HALF_UP + serialização JSON como float, preservando o contrato que o
frontend já consome), mas com a casa decimal correta para quantidade.
Reaproveita `para_decimal` de `money.py` em vez de duplicar a conversão seg-
ura de float/str para Decimal -- a técnica de conversão é a mesma, só muda
a quantidade de casas no arredondamento final.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Annotated

from pydantic import PlainSerializer

from utils.money import Numero, para_decimal

TRES_CASAS = Decimal("0.001")

# Tipo para usar nos campos de quantidade dos modelos (SQLModel) e schemas
# (Pydantic): guarda e calcula tudo como Decimal (sem erro de ponto
# flutuante), mas ao serializar para JSON (respostas da API) converte para
# float, preservando o contrato que o frontend já consome (número, não
# string) -- mesmo raciocínio de `DecimalMoeda`, só que com 3 casas.
DecimalQuantidade = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


def arredondar_quantidade(valor: Numero) -> Decimal:
    """Arredonda uma quantidade para 3 casas decimais (ROUND_HALF_UP)."""
    return para_decimal(valor).quantize(TRES_CASAS, rounding=ROUND_HALF_UP)
