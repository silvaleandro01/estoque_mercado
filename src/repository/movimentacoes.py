"""Histórico de movimentações de estoque (Fase 4).

Ver docstring de `utils.database.MovimentacaoEstoque` para a decisão de
arquitetura completa (convenção de sinal, quando `lote_id` é usado, quais
tipos já têm código que os gera nesta fase).

`registrar_movimentacao` nunca abre sua própria sessão nem commita sozinha --
sempre roda dentro da MESMA sessão/transação de quem chama (repository/
estoque.py e repository/vendas.py), exatamente como `criar_lote` e
`reconciliar_lote_sem_validade` em repository/lotes.py. Isso garante que a
alteração de `Estoque.quantidade`/`Lote.quantidade` e o registro da
movimentação correspondente nunca ficam dessincronizados por uma falha
parcial (um commitando e o outro não).
"""

from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Estoque, MovimentacaoEstoque, engine
from utils.quantidade import arredondar_quantidade


def registrar_movimentacao(
    session: Session,
    estoque_id: int,
    tipo: str,
    quantidade: Decimal,
    funcionario_id: int,
    lote_id: Optional[int] = None,
    motivo: Optional[str] = None,
) -> MovimentacaoEstoque:
    """Registra uma linha de movimentação. `quantidade` já deve vir SIGNED
    (positiva = entrada, negativa = saída -- ver convenção de sinal na
    docstring de MovimentacaoEstoque) -- aqui só arredonda para 3 casas,
    mesmo padrão de `criar_lote`."""
    movimentacao = MovimentacaoEstoque(
        estoque_id=estoque_id,
        lote_id=lote_id,
        tipo=tipo,
        quantidade=arredondar_quantidade(quantidade),
        motivo=motivo,
        funcionario_id=funcionario_id,
    )
    session.add(movimentacao)
    session.flush()
    return movimentacao


# IMPORTANTE 4 (revisão da Fase 4): sem paginação, o endpoint devolvia o
# histórico INTEIRO de uma vez -- num produto com uso pesado de longo prazo
# isso cresce sem parar (medido pelo painel de revisão: ~600ms com 20 mil
# linhas, payload JSON enorme). LIMIT_PADRAO é usado quando o chamador não
# informa `limit`; LIMIT_MAXIMO é um teto absoluto (mesmo que alguém peça
# mais) -- protege o endpoint mesmo que o parâmetro venha de uma origem que
# não respeite o `le=` já validado na camada Pydantic/FastAPI (rota
# chamada diretamente como função, por exemplo).
LIMIT_PADRAO = 50
LIMIT_MAXIMO = 200


def listar_movimentacoes(estoque_id: int, limit: int = LIMIT_PADRAO, offset: int = 0):
    """Lista o histórico de movimentações de um produto, mais recente
    primeiro, paginado. Abre sua própria sessão -- diferente de
    `registrar_movimentacao`, é só leitura, sempre chamada isoladamente
    (rota GET), nunca dentro da transação de outra escrita."""
    limit = max(1, min(limit, LIMIT_MAXIMO))
    offset = max(0, offset)
    with Session(engine) as session:
        if not session.get(Estoque, estoque_id):
            raise HTTPException(status_code=404, detail="Estoque não localizado")
        return session.exec(
            select(MovimentacaoEstoque)
            .where(MovimentacaoEstoque.estoque_id == estoque_id)
            .order_by(MovimentacaoEstoque.data.desc(), MovimentacaoEstoque.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
