from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Compra, ItemCompra, Funcionario, Fornecedor, engine
from utils.money import arredondar
from utils.timezone import hoje_brasil, limites_do_dia_brasil
from logs.logs import criar_log
from schemas.schemas import CompraInput


def _nome_completo(session: Session, funcionario_id: int) -> str:
    funcionario = session.get(Funcionario, funcionario_id)
    return f"{funcionario.nome} {funcionario.sobrenome}" if funcionario else "-"


def registrar_compra(dados: CompraInput, funcionario_id: int):
    with Session(engine) as session:
        # Mesmo raciocínio de _validar_fornecedor em repository/estoque.py:
        # erro 404 claro em vez de um erro cru do banco/FK se o
        # fornecedor_id informado não existir. fornecedor_id é opcional
        # (compras sem fornecedor definido continuam funcionando).
        if dados.fornecedor_id is not None and not session.get(Fornecedor, dados.fornecedor_id):
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")

        # Arredonda cada preço unitário (entrada do cliente pode vir com mais
        # de 2 casas) antes de multiplicar, para que o total do item e o
        # total do pedido usem sempre o mesmo valor unitário "de verdade"
        # que será gravado no banco.
        itens_calculados = [
            (item, arredondar(item.preco_custo), arredondar(item.preco_venda) if item.preco_venda is not None else None)
            for item in dados.itens
        ]
        valor_total = arredondar(
            sum((arredondar(preco_custo * item.quantidade) for item, preco_custo, _ in itens_calculados), Decimal("0.00"))
        )
        compra = Compra(
            solicitante_id=funcionario_id, valor_total=valor_total, status="pendente",
            fornecedor_id=dados.fornecedor_id,
        )
        try:
            session.add(compra)
            session.flush()
            for item, preco_custo, preco_venda in itens_calculados:
                session.add(ItemCompra(
                    compra_id=compra.id,
                    codigodebarras=item.codigodebarras,
                    nomedoproduto=item.nomedoproduto,
                    categoria=item.categoria,
                    preco_venda=preco_venda,
                    quantidade=item.quantidade,
                    preco_custo_unitario=preco_custo,
                    preco_custo_total=arredondar(preco_custo * item.quantidade),
                ))
            session.commit()
            session.refresh(compra)
            criar_log(funcionario_id, f"Pedido de compra registrado: #{compra.id}")
            return {"id": compra.id, "status": compra.status, "valor_total": compra.valor_total}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao registrar pedido de compra")


def listar_compras():
    with Session(engine) as session:
        compras = session.exec(select(Compra).order_by(Compra.data.desc())).all()
        return [
            {
                "id": c.id,
                "data": c.data,
                "solicitante": _nome_completo(session, c.solicitante_id),
                "aprovador": _nome_completo(session, c.aprovador_id) if c.aprovador_id else None,
                "valor_total": c.valor_total,
                "status": c.status,
                "fornecedor": session.get(Fornecedor, c.fornecedor_id).nome if c.fornecedor_id else None,
            }
            for c in compras
        ]


def buscar_itens_compra(compra_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra:
            raise HTTPException(status_code=404, detail="Pedido de compra não encontrado")
        itens = session.exec(select(ItemCompra).where(ItemCompra.compra_id == compra_id)).all()
        return [
            {
                "nomedoproduto": i.nomedoproduto,
                "codigodebarras": i.codigodebarras,
                "quantidade": i.quantidade,
                "preco_custo": i.preco_custo_unitario,
                "total": i.preco_custo_total,
            }
            for i in itens
        ]


def _buscar_compra_ou_404(session: Session, compra_id: int) -> Compra:
    compra = session.get(Compra, compra_id)
    if not compra:
        raise HTTPException(status_code=404, detail="Pedido de compra não encontrado")
    return compra


def _transicionar(compra_id: int, funcionario_id: int, de: tuple, para: str, mensagem_log: str, aprovador: bool = False):
    with Session(engine) as session:
        compra = _buscar_compra_ou_404(session, compra_id)
        if compra.status not in de:
            raise HTTPException(
                status_code=400,
                detail=f"Pedido não pode sair do status '{compra.status}' para '{para}'",
            )
        compra.status = para
        if aprovador:
            compra.aprovador_id = funcionario_id
        try:
            session.add(compra)
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar pedido de compra")

        criar_log(funcionario_id, f"{mensagem_log}: #{compra.id}")
        return {"msg": f"Pedido #{compra.id} atualizado para {para}"}


def encaminhar_compra(compra_id: int, funcionario_id: int):
    return _transicionar(compra_id, funcionario_id, ("pendente",), "aguardando_diretor", "Pedido encaminhado ao diretor")


def cancelar_compra(compra_id: int, funcionario_id: int):
    return _transicionar(compra_id, funcionario_id, ("pendente", "aguardando_diretor"), "cancelada", "Pedido de compra cancelado")


def recusar_compra(compra_id: int, funcionario_id: int):
    return _transicionar(compra_id, funcionario_id, ("aguardando_diretor",), "recusada", "Pedido de compra recusado", aprovador=True)


def autorizar_compra(compra_id: int, funcionario_id: int):
    with Session(engine) as session:
        compra = _buscar_compra_ou_404(session, compra_id)
        if compra.status != "aguardando_diretor":
            raise HTTPException(
                status_code=400,
                detail=f"Pedido não pode sair do status '{compra.status}' para 'autorizada'",
            )

        compra.status = "autorizada"
        compra.aprovador_id = funcionario_id
        compra.data_autorizacao = datetime.now(timezone.utc)

        try:
            session.add(compra)
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao autorizar pedido de compra")

        criar_log(funcionario_id, f"Pedido de compra autorizado, aguardando lançamento no estoque: #{compra.id}")
        return {"msg": f"Pedido #{compra.id} autorizado, aguardando lançamento no estoque"}


def compras_do_dia():
    with Session(engine) as session:
        dia = hoje_brasil()
        inicio_utc, fim_utc = limites_do_dia_brasil(dia)
        compras = session.exec(
            select(Compra).where(
                Compra.status == "autorizada",
                Compra.data >= inicio_utc,
                Compra.data < fim_utc,
            )
        ).all()
        total = arredondar(sum((c.valor_total for c in compras), Decimal("0.00")))
        return {"data": dia, "total": total}
