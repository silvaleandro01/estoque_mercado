from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Estoque, Compra, ItemCompra, Fornecedor, engine
from utils.money import arredondar
from utils.quantidade import arredondar_quantidade
from logs.logs import criar_log
from schemas.schemas import EstoqueCreate, EstoqueUpdate, ConfirmarPendenteInput


def _validar_fornecedor(session: Session, fornecedor_id):
    """Garante um erro 404 claro (em vez de um erro cru do banco/FK) quando
    o `fornecedor_id` informado no cadastro de produto não existe."""
    if fornecedor_id is not None and not session.get(Fornecedor, fornecedor_id):
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")


def criar_estoque(dados: EstoqueCreate, funcionario_id: int):
    with Session(engine) as session:
        _validar_fornecedor(session, dados.fornecedor_id)

        # with_for_update(): mesma trava usada em repository/vendas.py.
        # Sem ela, duas entradas de estoque simultâneas para o mesmo produto
        # (ex.: dois lançamentos manuais, ou um lançamento concorrendo com a
        # confirmação de um pendente de compra) podem ambas ler a mesma
        # `quantidade` "antiga", cada uma somar o próprio incremento em cima
        # dela e uma das duas sobrescrever o resultado da outra ao salvar --
        # um incremento inteiro perdido (lost update).
        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras).with_for_update()
        ).first()

        if produto_existente:
            produto_existente.quantidade = arredondar_quantidade(produto_existente.quantidade + dados.quantidade)
            produto_existente.funcionario_id = funcionario_id
            try:
                session.commit()
                session.refresh(produto_existente)
                criar_log(funcionario_id, f"Incremento de estoque: {produto_existente.nomedoproduto}")
                return produto_existente
            except Exception:
                session.rollback()
                raise HTTPException(status_code=500, detail="Erro ao atualizar estoque")

        estoque = Estoque(
            titulo=dados.titulo,
            nomedoproduto=dados.nomedoproduto,
            quantidade=arredondar_quantidade(dados.quantidade),
            unidade_medida=dados.unidade_medida,
            estoque_minimo=arredondar_quantidade(dados.estoque_minimo),
            preco=arredondar(dados.preco),
            preco_custo=arredondar(dados.preco_custo) if dados.preco_custo is not None else Decimal("0.00"),
            codigodebarras=dados.codigodebarras,
            categoria=dados.categoria,
            funcionario_id=funcionario_id,
            fornecedor_id=dados.fornecedor_id,
        )
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

        _validar_fornecedor(session, dados.fornecedor_id)

        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras)
        ).first()
        if produto_existente and produto_existente.id != estoque.id:
            raise HTTPException(status_code=400, detail="Código de barras já cadastrado em outro produto")

        estoque.titulo = dados.titulo
        estoque.nomedoproduto = dados.nomedoproduto
        estoque.quantidade = arredondar_quantidade(dados.quantidade)
        estoque.unidade_medida = dados.unidade_medida
        estoque.estoque_minimo = arredondar_quantidade(dados.estoque_minimo)
        estoque.preco = arredondar(dados.preco)
        estoque.codigodebarras = dados.codigodebarras
        estoque.categoria = dados.categoria
        estoque.funcionario_id = funcionario_id
        estoque.fornecedor_id = dados.fornecedor_id

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


def listar_pendentes():
    with Session(engine) as session:
        itens = session.exec(
            select(ItemCompra, Compra)
            .join(Compra, ItemCompra.compra_id == Compra.id)
            .where(Compra.status == "autorizada", ItemCompra.lancado_em.is_(None))
        ).all()
        return [
            {
                "id": item.id,
                "compra_id": compra.id,
                "data_entrada": compra.data_autorizacao,
                "nomedoproduto": item.nomedoproduto,
                "codigodebarras": item.codigodebarras,
                "quantidade": item.quantidade,
                "preco_custo": item.preco_custo_unitario,
                "preco_venda": item.preco_venda,
            }
            for item, compra in itens
        ]


def confirmar_pendente(item_id: int, dados: ConfirmarPendenteInput, funcionario_id: int):
    with Session(engine) as session:
        item = session.get(ItemCompra, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item pendente não encontrado")
        if item.lancado_em is not None:
            raise HTTPException(status_code=400, detail="Item já foi lançado no estoque")

        # Mesma trava de criar_estoque(): evita lost update quando a
        # confirmação de um pendente de compra concorre com outra entrada de
        # estoque para o mesmo produto.
        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras).with_for_update()
        ).first()

        if produto_existente:
            produto_existente.quantidade = arredondar_quantidade(produto_existente.quantidade + item.quantidade)
            produto_existente.preco_custo = arredondar(item.preco_custo_unitario)
            produto_existente.funcionario_id = funcionario_id
            session.add(produto_existente)
            nome_produto = produto_existente.nomedoproduto
        else:
            # Produto novo (não existia ainda com esse código de barras):
            # herda o fornecedor do próprio pedido de compra que o originou
            # (quando o pedido tem um fornecedor definido) -- afinal, foi
            # dele que este produto veio. unidade_medida/estoque_minimo não
            # dá pra deduzir da compra, então vêm do formulário de
            # confirmação (ConfirmarPendenteInput).
            compra = session.get(Compra, item.compra_id)
            novo = Estoque(
                nomedoproduto=dados.nomedoproduto,
                quantidade=item.quantidade,
                unidade_medida=dados.unidade_medida,
                estoque_minimo=arredondar_quantidade(dados.estoque_minimo),
                preco=arredondar(dados.preco_venda),
                preco_custo=arredondar(item.preco_custo_unitario),
                codigodebarras=dados.codigodebarras,
                categoria=dados.categoria,
                funcionario_id=funcionario_id,
                fornecedor_id=compra.fornecedor_id if compra else None,
            )
            session.add(novo)
            nome_produto = novo.nomedoproduto

        item.lancado_em = datetime.now(timezone.utc)
        session.add(item)

        try:
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao lançar produto no estoque")

        criar_log(funcionario_id, f"Lançamento de compra pendente: {nome_produto}")
        return {"detail": "Produto lançado no estoque com sucesso"}
