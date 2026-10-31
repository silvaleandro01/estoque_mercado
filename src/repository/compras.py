from datetime import datetime, timezone
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Compra, ItemCompra, Estoque, Funcionario, engine
from logs.logs import criar_log
from schemas.schemas import CompraInput


def _nome_completo(session: Session, funcionario_id: int) -> str:
    funcionario = session.get(Funcionario, funcionario_id)
    return f"{funcionario.nome} {funcionario.sobrenome}" if funcionario else "-"


def registrar_compra(dados: CompraInput, funcionario_id: int):
    with Session(engine) as session:
        valor_total = sum(item.preco_custo * item.quantidade for item in dados.itens)
        compra = Compra(solicitante_id=funcionario_id, valor_total=round(valor_total, 2), status="pendente")
        try:
            session.add(compra)
            session.flush()
            for item in dados.itens:
                session.add(ItemCompra(
                    compra_id=compra.id,
                    codigodebarras=item.codigodebarras,
                    nomedoproduto=item.nomedoproduto,
                    categoria=item.categoria,
                    preco_venda=item.preco_venda,
                    quantidade=item.quantidade,
                    preco_custo_unitario=item.preco_custo,
                    preco_custo_total=round(item.preco_custo * item.quantidade, 2),
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

        itens = session.exec(select(ItemCompra).where(ItemCompra.compra_id == compra_id)).all()
        for item in itens:
            produto = session.exec(
                select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)
            ).first()
            if produto:
                produto.quantidade += item.quantidade
                produto.preco_custo = item.preco_custo_unitario
                session.add(produto)
            else:
                session.add(Estoque(
                    nomedoproduto=item.nomedoproduto,
                    quantidade=item.quantidade,
                    preco=item.preco_venda or 0.0,
                    preco_custo=item.preco_custo_unitario,
                    codigodebarras=item.codigodebarras,
                    categoria=item.categoria or "Geral",
                    funcionario_id=funcionario_id,
                ))

        compra.status = "autorizada"
        compra.aprovador_id = funcionario_id

        try:
            session.add(compra)
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao autorizar pedido de compra")

        criar_log(funcionario_id, f"Pedido de compra autorizado e estoque abastecido: #{compra.id}")
        return {"msg": f"Pedido #{compra.id} autorizado e estoque abastecido"}


def compras_do_dia():
    with Session(engine) as session:
        hoje = datetime.now(timezone.utc).date()
        compras = session.exec(
            select(Compra).where(
                Compra.status == "autorizada",
                Compra.data >= datetime(hoje.year, hoje.month, hoje.day, tzinfo=timezone.utc),
            )
        ).all()
        total = round(sum(c.valor_total for c in compras), 2)
        return {"data": hoje, "total": total}
