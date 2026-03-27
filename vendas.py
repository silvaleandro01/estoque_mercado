from fastapi import HTTPException
from sqlmodel import Session, select
from datetime import date
from database import engine, Estoque, Venda, ItemVenda

# Criar venda
def criar_venda(dados, funcionario_id: int):
    with Session(engine) as session:

        # cria venda (compra geral)
        venda = Venda(funcionario_id=funcionario_id)
        session.add(venda)
        session.commit()
        session.refresh(venda)
        total = 0

        # percorre os itens enviados
        for item in dados.itens:

            # busca produto pelo código de barras
            produto = session.exec(select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)).first() 

            # validações
            if not produto:
                raise HTTPException(status_code=404, detail=f"Produto {item.codigodebarras} não encontrado")
            
            if produto.quantidade < item.quantidade:
                raise HTTPException(status_code=400,detail=f"Estoque insuficiente para {produto.nomedoproduto}")
            
            # atualiza o estoque
            produto.quantidade -= item.quantidade

            # calculo de valores
            preco_total = produto.preco * item.quantidade
            total += preco_total

            # salva item da venda
            item_venda = ItemVenda(
                venda_id=venda.id,
                codigodebarras=item.codigodebarras,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                preco_total=preco_total
            )

            session.add(item_venda)

        # atualiza total de venda
        venda.valor_total = total
        session.add(venda)
        session.commit()
        session.refresh(venda)
        return venda
    
# Total vendido no dia
def vendas_do_dia():
    with Session(engine) as session:
        vendas = session.exec(select(Venda)).all()
        hoje = date.today()
        total = 0

        for venda in vendas:
            if venda.data.date() == hoje:
                total += venda.valor_total
        return {
            "dat": hoje,
            "total_vendido": total
        }

# Listar todas as vendas(opcional)    
def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()