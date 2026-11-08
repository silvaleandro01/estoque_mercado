"""Tratamento compartilhado de erros operacionais do MySQL que merecem
virar um erro HTTP claro em vez de deixar o SQLAlchemy/MySQL subir cru.

Extraído de repository/vendas.py (que já tratava deadlock do MySQL em
criar_venda desde a Fase 1/2) para repository/estoque.py reaproveitar a
mesma lógica em criar_estoque, atualizar_estoque e confirmar_pendente --
os pontos de escrita que a Fase 3 (lotes e validade) passou a levar
with_for_update(), e que antes deixavam o deadlock do MySQL
(OperationalError 1213) subir cru como um 500 em vez do 409 "tente
novamente" que o resto do sistema já usa.
"""
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

# Código de erro do MySQL/InnoDB para "Deadlock found when trying to get
# lock; try restarting transaction".
MYSQL_ERRO_DEADLOCK = 1213


def e_deadlock_mysql(exc: OperationalError) -> bool:
    """
    Identifica se um OperationalError do SQLAlchemy é o deadlock do MySQL
    (código 1213), e não outro erro operacional qualquer (perda de conexão,
    timeout, etc.) que não deveria virar um 409 "tente de novo".
    """
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return bool(args) and args[0] == MYSQL_ERRO_DEADLOCK


def tratar_operational_error(exc: OperationalError, mensagem: str) -> None:
    """
    Levanta HTTPException 409 (com `mensagem`) se `exc` for o deadlock do
    MySQL; caso contrário, relança `exc` sem modificação (erro operacional
    "de verdade" -- ex.: perda de conexão -- que não deve ser mascarado
    como "tente de novo", e precisa continuar propagando).

    Chamar dentro de um `except OperationalError as exc:`, já depois de
    `session.rollback()`.
    """
    if e_deadlock_mysql(exc):
        raise HTTPException(status_code=409, detail=mensagem) from exc
    raise exc
