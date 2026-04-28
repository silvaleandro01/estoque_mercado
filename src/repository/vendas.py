from datetime import date, datetime, timezone
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import engine, Estoque, Venda, ItemVenda
from schemas.schemas import VendaInput


def criar_venda(dados: VendaInput, funcionario_id: int):
    with Session(engine) as session:
        venda = Venda(funcionario_id=funcionario_id)
        session.add(venda)
        session.flush()

        total = 0.0
        for item in dados.itens:
            produto = session.exec(
                select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)
            ).first()

            if not produto:
                session.rollback()
                raise HTTPException(status_code=404, detail=f"Produto {item.codigodebarras} não encontrado")

            if produto.quantidade < item.quantidade:
                session.rollback()
                raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {produto.nomedoproduto}")

            produto.quantidade -= item.quantidade
            preco_total = produto.preco * item.quantidade
            total += preco_total

            session.add(ItemVenda(
                venda_id=venda.id,
                codigodebarras=item.codigodebarras,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                preco_total=preco_total,
            ))

        venda.valor_total = round(total, 2)
        session.add(venda)
        session.commit()
        session.refresh(venda)
        return venda


def vendas_do_dia():
    with Session(engine) as session:
        hoje = datetime.now(timezone.utc).date()
        vendas = session.exec(
            select(Venda).where(Venda.data >= datetime(hoje.year, hoje.month, hoje.day, tzinfo=timezone.utc))
        ).all()
        total = round(sum(v.valor_total for v in vendas), 2)
        return {"data": hoje, "total_vendido": total}


def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()
