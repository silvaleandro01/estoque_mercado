from decimal import Decimal
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import engine, Estoque, Venda, ItemVenda
from utils.money import arredondar
from utils.timezone import hoje_brasil, limites_do_dia_brasil
from schemas.schemas import VendaInput


def criar_venda(dados: VendaInput, funcionario_id: int):
    with Session(engine) as session:
        venda = Venda(funcionario_id=funcionario_id)
        session.add(venda)
        session.flush()

        total = Decimal("0.00")
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
            preco_total = arredondar(produto.preco * item.quantidade)
            total += preco_total

            session.add(ItemVenda(
                venda_id=venda.id,
                codigodebarras=item.codigodebarras,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                preco_total=preco_total,
            ))

        venda.valor_total = arredondar(total)
        session.add(venda)
        session.commit()
        session.refresh(venda)
        return venda


def vendas_do_dia():
    with Session(engine) as session:
        dia = hoje_brasil()
        inicio_utc, fim_utc = limites_do_dia_brasil(dia)
        vendas = session.exec(
            select(Venda).where(Venda.data >= inicio_utc, Venda.data < fim_utc)
        ).all()
        total = arredondar(sum((v.valor_total for v in vendas), Decimal("0.00")))
        return {"data": dia, "total_vendido": total}


def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()
