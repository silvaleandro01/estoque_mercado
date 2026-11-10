"""Tratamento compartilhado de erros operacionais do MySQL que merecem
virar um erro HTTP claro em vez de deixar o SQLAlchemy/MySQL subir cru.

Extraído de repository/vendas.py (que já tratava deadlock do MySQL em
criar_venda desde a Fase 1/2) para repository/estoque.py reaproveitar a
mesma lógica em criar_estoque, atualizar_estoque e confirmar_pendente --
os pontos de escrita que a Fase 3 (lotes e validade) passou a levar
with_for_update(), e que antes deixavam o deadlock do MySQL
(OperationalError 1213) subir cru como um 500 em vez do 409 "tente
novamente" que o resto do sistema já usa.

ESTENDIDO (CRÍTICO 2 da revisão de fix/login-rate-limiting): além do
deadlock (1213), passa a tratar também o lock-wait-timeout (1205) da mesma
forma -- reproduzido ao vivo contra MySQL real (innodb_lock_wait_timeout
reduzido só para o teste) que esse erro escapava cru como 500 em
repository/funcionarios.py::autenticar_funcionario, já que o
SELECT ... FOR UPDATE do login (e só ele, até esta correção) não tinha
nenhum tratamento de OperationalError. Do ponto de vista do cliente, 1213
e 1205 são o mesmo tipo de falha transitória de concorrência -- "outra
transação está disputando a mesma linha/lock agora, tente de novo" --
então os dois merecem a mesma resposta 409.
"""
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError

# Código de erro do MySQL/InnoDB para "Deadlock found when trying to get
# lock; try restarting transaction".
MYSQL_ERRO_DEADLOCK = 1213

# Código de erro do MySQL/InnoDB para "Lock wait timeout exceeded; try
# restarting transaction" -- acontece quando uma transação espera mais que
# `innodb_lock_wait_timeout` por um lock que outra transação está segurando,
# em vez de uma disputa circular (deadlock) detectada na hora. Mesma
# natureza transitória do 1213 do ponto de vista do cliente.
MYSQL_ERRO_LOCK_WAIT_TIMEOUT = 1205

# Códigos de erro do MySQL/InnoDB que representam uma disputa transitória de
# lock entre transações concorrentes -- não um erro operacional "de
# verdade" (perda de conexão, etc.) -- e por isso merecem virar um 409
# "tente novamente" em vez de um 500 cru.
_ERROS_TRANSITORIOS_DE_LOCK = (MYSQL_ERRO_DEADLOCK, MYSQL_ERRO_LOCK_WAIT_TIMEOUT)


def e_deadlock_mysql(exc: OperationalError) -> bool:
    """
    Identifica se um OperationalError do SQLAlchemy é uma disputa
    transitória de lock do MySQL (deadlock, código 1213, ou lock-wait-
    timeout, código 1205), e não outro erro operacional qualquer (perda de
    conexão, timeout de rede, etc.) que não deveria virar um 409 "tente de
    novo".

    Nome mantido (não é só deadlock desde a extensão para 1205) para não
    quebrar quem já importa esta função -- ver `tratar_operational_error`,
    única chamadora hoje.
    """
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return bool(args) and args[0] in _ERROS_TRANSITORIOS_DE_LOCK


def tratar_operational_error(exc: OperationalError, mensagem: str) -> None:
    """
    Levanta HTTPException 409 (com `mensagem`) se `exc` for uma disputa
    transitória de lock do MySQL (deadlock 1213 ou lock-wait-timeout 1205);
    caso contrário, relança `exc` sem modificação (erro operacional "de
    verdade" -- ex.: perda de conexão -- que não deve ser mascarado como
    "tente de novo", e precisa continuar propagando).

    Chamar dentro de um `except OperationalError as exc:`, já depois de
    `session.rollback()`.
    """
    if e_deadlock_mysql(exc):
        raise HTTPException(status_code=409, detail=mensagem) from exc
    raise exc
