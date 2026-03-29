from fastapi import HTTPException
from sqlmodel import Session, select, SQLModel
from database import Estoque, engine
from logs import criar_log

class EstoqueUpdate(SQLModel):
    titulo: str
    nomedoproduto: str
    quantidade: int
    preco: float
    codigodebarras: str
    categoria: str

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