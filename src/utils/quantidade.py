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

from fastapi import HTTPException
from pydantic import PlainSerializer

from utils.money import Numero, para_decimal

TRES_CASAS = Decimal("0.001")

# Tipo para usar nos campos de quantidade dos modelos (SQLModel) e schemas
# (Pydantic): guarda e calcula tudo como Decimal (sem erro de ponto
# flutuante), mas ao serializar para JSON (respostas da API) converte para
# float, preservando o contrato que o frontend já consome (número, não
# string) -- mesmo raciocínio de `DecimalMoeda`, só que com 3 casas.
#
# ATENÇÃO: `DecimalQuantidade` e `DecimalMoeda` (utils/money.py) são
# estruturalmente idênticos (mesmo Decimal + mesmo PlainSerializer) -- nada
# no Pydantic impede declarar um campo de dinheiro como `DecimalQuantidade`
# ou um campo de quantidade como `DecimalMoeda` por engano, os dois aceitam
# e serializam o mesmo jeito. A diferença que importa (2 casas vs. 3 casas)
# só existe no arredondamento manual (`arredondar()` vs.
# `arredondar_quantidade()`), nunca é imposta pelo tipo em si. Sempre
# confira que a função de arredondamento certa foi chamada antes de
# persistir -- usar a errada não dá erro nenhum, só corrompe silenciosamente
# a precisão do valor gravado.
DecimalQuantidade = Annotated[Decimal, PlainSerializer(lambda v: float(v), return_type=float, when_used="json")]


def arredondar_quantidade(valor: Numero) -> Decimal:
    """Arredonda uma quantidade para 3 casas decimais (ROUND_HALF_UP)."""
    return para_decimal(valor).quantize(TRES_CASAS, rounding=ROUND_HALF_UP)


def validar_quantidade_inteira_se_unidade(quantidade: Numero, unidade_medida: str, nome_produto: str) -> None:
    """Rejeita quantidade fracionária para produto vendido por unidade (UN).

    A regra "produto UN só aceita quantidade inteira" vivia só no frontend
    (`Number.isInteger` em frontend/app.js), então batia direto na API --
    POST /vendas/inserir, POST /estoque/inserir e POST /compras/registrar
    aceitavam `1.5` como quantidade de um produto UN sem nenhum erro (achado
    confirmado de forma independente por 4 agentes do painel de revisão da
    Fase 2, com request real contra a API). Produto KG/L continua aceitando
    fração normalmente -- só UN é restrito.
    """
    if unidade_medida == "UN" and para_decimal(quantidade) % 1 != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Produto {nome_produto} é vendido por unidade inteira, quantidade fracionária não é permitida",
        )
