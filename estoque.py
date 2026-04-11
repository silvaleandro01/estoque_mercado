from fastapi import HTTPException
from sqlmodel import Session, select, SQLModel
from datetime import datetime, date
from database import Estoque, engine, Compra, ItemCompra, Funcionario, Setor, ComunicadoDestinatario, Comunicado
from logs import criar_log

class EstoqueUpdate(SQLModel):
    titulo: str
    nomedoproduto: str
    quantidade: int
    preco: float
    codigodebarras: str
    categoria: str

def registrar_compra(dados, funcionario_id: int, is_gerente: bool = False):
    with Session(engine) as session:
        status_inicial = "pendente"
        compra = Compra(funcionario_id=funcionario_id, status=status_inicial)

        session.add(compra)
        session.flush()
        
        total_compra = 0.0
        for item in dados.itens:
            
            valor_item = item.quantidade * item.preco_custo
            total_compra += valor_item
            
            item_compra = ItemCompra(compra_id=compra.id, codigodebarras=item.codigodebarras, quantidade=item.quantidade, preco_custo=item.preco_custo)
            session.add(item_compra)

        compra.valor_total = round(total_compra, 2)
        session.commit()
        session.refresh(compra)
        criar_log(funcionario_id, f"Pedido de compra {compra.id} registrado (Pendente).")
        return compra

def listar_todas_compras():
    with Session(engine) as session:
        compras = session.exec(select(Compra).order_by(Compra.id.desc())).all()
        resultado = []
        for c in compras:
            func = session.get(Funcionario, c.funcionario_id)
            gerente = session.get(Funcionario, c.gerente_id) if c.gerente_id else None
            resultado.append({
                "id": c.id,
                "data": c.data.isoformat(),
                "valor_total": c.valor_total,
                "status": c.status,
                "solicitante": f"{func.nome} {func.sobrenome}" if func else f"ID {c.funcionario_id}",
                "aprovador": f"{gerente.nome} {gerente.sobrenome}" if gerente else None,
                "funcionario_id": c.funcionario_id,
            })
        return resultado

def listar_itens_compra(compra_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra:
            raise HTTPException(status_code=404, detail="Pedido não encontrado.")
        itens = session.exec(select(ItemCompra).where(ItemCompra.compra_id == compra_id)).all()
        resultado = []
        for item in itens:
            prod = session.exec(select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)).first()
            resultado.append({
                "codigodebarras": item.codigodebarras,
                "nomedoproduto": prod.nomedoproduto if prod else item.codigodebarras,
                "quantidade": item.quantidade,
                "preco_custo": item.preco_custo,
                "total": round(item.quantidade * item.preco_custo, 2)
            })
        return resultado

def encaminhar_compra(compra_id: int, gerente_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra or compra.status != "pendente":
            raise HTTPException(status_code=400, detail="Pedido não encontrado ou não está pendente.")
        compra.status = "aguardando_diretor"
        compra.gerente_id = gerente_id
        session.commit()
        criar_log(gerente_id, f"Pedido de compra {compra_id} encaminhado ao diretor para aprovação.")
        return {"msg": "Pedido encaminhado ao diretor para aprovação."}

def autorizar_compra(compra_id: int, diretor_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra or compra.status != "aguardando_diretor":
            raise HTTPException(status_code=400, detail="Pedido não encontrado ou não está aguardando aprovação.")
        itens = session.exec(select(ItemCompra).where(ItemCompra.compra_id == compra_id)).all()
        for item in itens:
            _proc_estoque_item(session, item, diretor_id)
        compra.status = "autorizada"
        compra.gerente_id = diretor_id
        session.commit()
        criar_log(diretor_id, f"Pedido de compra {compra_id} APROVADO pelo diretor.")
        _enviar_comunicado_compra(compra_id, diretor_id, aprovado=True)
        return {"msg": "Compra aprovada e estoque atualizado."}

def recusar_compra(compra_id: int, diretor_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra or compra.status != "aguardando_diretor":
            raise HTTPException(status_code=400, detail="Pedido não encontrado ou não está aguardando aprovação.")
        compra.status = "recusada"
        compra.gerente_id = diretor_id
        session.commit()
        criar_log(diretor_id, f"Pedido de compra {compra_id} RECUSADO pelo diretor.")
        _enviar_comunicado_compra(compra_id, diretor_id, aprovado=False)
        return {"msg": "Compra recusada."}

def cancelar_compra(compra_id: int, gerente_id: int):
    with Session(engine) as session:
        compra = session.get(Compra, compra_id)
        if not compra or compra.status not in ["pendente", "aguardando_diretor"]:
            raise HTTPException(status_code=400, detail="Pedido não pode ser cancelado neste status.")
        compra.status = "cancelada"
        compra.gerente_id = gerente_id
        session.commit()
        criar_log(gerente_id, f"Pedido de compra {compra_id} cancelado pelo gerente.")
        return {"msg": "Compra cancelada."}

def _enviar_comunicado_compra(compra_id: int, autor_id: int, aprovado: bool):
    with Session(engine) as session:
        setor_compras = session.exec(select(Setor).where(Setor.tipo == "compras")).first()
        if not setor_compras:
            return
        gerentes = session.exec(
            select(Funcionario).where(
                Funcionario.setor_id == setor_compras.id
            )
        ).all()
        gerentes_ids = [f.id for f in gerentes if "gerente" in f.cargo.lower()]
        if not gerentes_ids:
            gerentes_ids = [f.id for f in gerentes]
        if not gerentes_ids:
            return

        titulo = f"✅ Pedido #{compra_id} APROVADO" if aprovado else f"❌ Pedido #{compra_id} RECUSADO"
        conteudo = (
            f"O diretor APROVOU o pedido de compra #{compra_id}. Você pode prosseguir com a compra."
            if aprovado else
            f"O diretor RECUSOU o pedido de compra #{compra_id}. Entre em contato para mais informações."
        )
        comunicado = Comunicado(
            titulo=titulo,
            conteudo=conteudo,
            autor_id=autor_id,
            para_todos=False,
        )
        session.add(comunicado)
        session.flush()
        session.refresh(comunicado)
        for fid in gerentes_ids:
            dest = ComunicadoDestinatario(
                comunicado_id=comunicado.id,
                funcionario_id=fid,
                lido=False,
            )
            session.add(dest)
        session.commit()

def _proc_estoque_item(session, item, func_id):
    prod = session.exec(select(Estoque).where(Estoque.codigodebarras == item.codigodebarras)).first()
    if prod:
        prod.quantidade += item.quantidade
        prod.preco_custo = item.preco_custo
    else:
        nova_mercadoria = Estoque(nomedoproduto=getattr(item, 'nomedoproduto', 'Novo'), quantidade=item.quantidade, preco=getattr(item, 'preco_venda', 0.0), preco_custo=item.preco_custo, codigodebarras=item.codigodebarras, categoria="Geral", funcionario_id=func_id)
        session.add(nova_mercadoria)

def listar_compras_do_dia():
    with Session(engine) as session:
        hoje = date.today()
        compras = session.exec(select(Compra).where(Compra.status == "autorizada")).all()
        total = sum(c.valor_total for c in compras if c.data.date() == hoje)
        return {"data": hoje, "total": round(total, 2)}

def criar_estoque(estoque: Estoque, funcionario_id: int):
    with Session(engine) as session:

        produto_existente = session.exec(
            select(Estoque).where(
                Estoque.codigodebarras == estoque.codigodebarras
            )
        ).first()

        if produto_existente:
            produto_existente.quantidade += estoque.quantidade
            produto_existente.funcionario_id = funcionario_id

            try:
                session.commit()
                session.refresh(produto_existente)
                criar_log(funcionario_id, f"Incremento de estoque: {produto_existente.nomedoproduto}")
                return produto_existente
            except Exception:
                session.rollback()
                raise HTTPException(status_code=500, detail="Erro ao atualizar estoque")

        estoque.funcionario_id = funcionario_id

        try:
            session.add(estoque)
            session.commit()
            session.refresh(estoque)
            criar_log(funcionario_id, f"Inclusão de produto: {estoque.nomedoproduto}")
            return estoque
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar produto")


def mostrar_produtos():
    with Session(engine) as session:
        return session.exec(select(Estoque)).all()


def buscar_estoque(estoque_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)

        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")

        return estoque


def atualizar_estoque(estoque_id: int, dados: EstoqueUpdate, funcionario_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)

        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")

        produto_existente = session.exec(
            select(Estoque).where(
                Estoque.codigodebarras == dados.codigodebarras
            )
        ).first()

        if produto_existente and produto_existente.id != estoque.id:
            raise HTTPException(
                status_code=400,
                detail="Código de barras já cadastrado em outro produto"
            )

        estoque.titulo = dados.titulo
        estoque.nomedoproduto = dados.nomedoproduto
        estoque.quantidade = dados.quantidade
        estoque.preco = dados.preco
        estoque.codigodebarras = dados.codigodebarras
        estoque.categoria = dados.categoria

        estoque.funcionario_id = funcionario_id

        try:
            session.commit()
            session.refresh(estoque)
            criar_log(funcionario_id, f"Atualização de produto: {estoque.nomedoproduto}")
            return estoque
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar estoque")


def deletar_estoque(estoque_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)

        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")

        try:
            session.delete(estoque)
            session.commit()
            return {"msg": "Estoque deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar estoque")