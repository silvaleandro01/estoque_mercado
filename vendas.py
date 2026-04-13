from fastapi import HTTPException
from sqlmodel import Session, select
from datetime import date, datetime, timezone, timedelta
from database import engine, Estoque, Venda, ItemVenda, Despesa, Compra
from logs import criar_log

def criar_venda(dados, funcionario_id: int):
    with Session(engine) as session:

        venda = Venda(
            funcionario_id=funcionario_id,
            metodo_pagamento=dados.metodo_pagamento,
            parcelas=dados.parcelas
        )
        session.add(venda)
        session.flush()
        total = 0.0
        itens_processados = []
        for item in dados.itens:
            produto = session.exec(select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)).first()
            if not produto:
                raise HTTPException(status_code=404, detail=f"Produto {item.codigodebarras} não encontrado")

            if produto.quantidade < item.quantidade:
                raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {produto.nomedoproduto}")

            produto.quantidade -= item.quantidade

            preco_total = produto.preco * item.quantidade
            custo_total = produto.preco_custo * item.quantidade
            total += preco_total

            item_venda = ItemVenda(
                venda_id=venda.id,
                codigodebarras=item.codigodebarras,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                preco_total=preco_total,
                preco_custo_total=custo_total
            )

            session.add(item_venda)
            item_dict = item_venda.model_dump()
            item_dict["nomedoproduto"] = produto.nomedoproduto
            itens_processados.append(item_dict)

        venda.valor_total = round(total, 2)
        session.add(venda)
        session.commit()
        session.refresh(venda)

        return {
            "id": venda.id,
            "data": venda.data,
            "valor_total": venda.valor_total,
            "metodo_pagamento": venda.metodo_pagamento,
            "parcelas": venda.parcelas,
            "itens": itens_processados
        }

def vendas_do_dia():
    with Session(engine) as session:
        vendas = session.exec(select(Venda)).all()
        hoje = date.today()
        total = 0.0

        for venda in vendas:
            data_venda = venda.data.date() if isinstance(venda.data, datetime) else venda.data
            if data_venda == hoje:
                total += float(venda.valor_total)

        return {
            "dat": hoje,
            "total_vendido": round(total, 2)
        }

def listar_vendas_detalhado():
    with Session(engine) as session:
        hoje = date.today()
        vendas = session.exec(select(Venda).where(Venda.data >= hoje).order_by(Venda.id.desc())).all()
        return vendas

def cancelar_venda_logica(venda_id: int, funcionario_id: int):
    with Session(engine) as session:
        venda = session.get(Venda, venda_id)
        if not venda:
            raise HTTPException(status_code=404, detail="Venda não encontrada")
        
        itens = session.exec(select(ItemVenda).where(ItemVenda.venda_id == venda_id)).all()
        for item in itens:
            produto = session.exec(select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)).first()
            if produto:
                produto.quantidade += item.quantidade
            session.delete(item)

        session.flush()
        session.delete(venda)
        session.commit()
        criar_log(funcionario_id, f"Venda {venda_id} cancelada. Produtos retornaram ao estoque.")
        return {"msg": "Venda cancelada com sucesso"}

def criar_despesa(dados, funcionario_id: int):
    with Session(engine) as session:
        nova_despesa = Despesa(
            descricao=dados.descricao,
            valor=dados.valor,
            categoria=dados.categoria,
            funcionario_id=funcionario_id
        )
        session.add(nova_despesa)
        session.commit()
        session.refresh(nova_despesa)
        return nova_despesa

def obter_estatisticas_dashboard():
    with Session(engine) as session:
        hoje = datetime.now()
        
        def calcular_periodo(dias=None, mes_atual=False, ano_atual=False):
            query_vendas = select(Venda, ItemVenda).join(ItemVenda)
            query_despesas = select(Despesa)
            query_compras = select(Compra).where(Compra.status == "autorizada")
            
            if dias:
                inicio = hoje - timedelta(days=dias)
                query_vendas = query_vendas.where(Venda.data >= inicio)
                query_despesas = query_despesas.where(Despesa.data >= inicio)
                query_compras = query_compras.where(Compra.data >= inicio)
            elif mes_atual:
                inicio = hoje.replace(day=1, hour=0, minute=0, second=0)
                query_vendas = query_vendas.where(Venda.data >= inicio)
                query_despesas = query_despesas.where(Despesa.data >= inicio)
                query_compras = query_compras.where(Compra.data >= inicio)
            elif ano_atual:
                inicio = hoje.replace(month=1, day=1, hour=0, minute=0, second=0)
                query_vendas = query_vendas.where(Venda.data >= inicio)
                query_despesas = query_despesas.where(Despesa.data >= inicio)
                query_compras = query_compras.where(Compra.data >= inicio)
            
            res_vendas = session.exec(query_vendas).all()
            res_despesas = session.exec(query_despesas).all()
            res_compras = session.exec(query_compras).all()
            
            faturamento = sum(item.preco_total for venda, item in res_vendas)
            cogs = sum(item.preco_custo_total for venda, item in res_vendas)
            total_despesas = sum(d.valor for d in res_despesas)
            total_investimento = sum(c.valor_total for c in res_compras)
            
            total_saidas = total_despesas + total_investimento
            return {
                "faturamento": round(float(faturamento), 2),
                "lucro_bruto": round(float(faturamento - cogs), 2),
                "despesas": round(float(total_saidas), 2),
                "investimento": round(float(total_investimento), 2),
                "lucro_liquido": round(float(faturamento - cogs - total_saidas), 2),
                "vendas_count": len(set(venda.id for venda, item in res_vendas))
            }

        return {
            "diario": calcular_periodo(dias=1),
            "semanal": calcular_periodo(dias=7),
            "mensal": calcular_periodo(mes_atual=True),
            "bimestral": calcular_periodo(dias=60),
            "trimestral": calcular_periodo(dias=90),
            "semestral": calcular_periodo(dias=180),
            "anual": calcular_periodo(ano_atual=True)
        }

def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()