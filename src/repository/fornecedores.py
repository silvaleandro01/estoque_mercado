from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Fornecedor, engine
from logs.logs import criar_log
from schemas.schemas import FornecedorInput


def criar_fornecedor(dados: FornecedorInput, funcionario_id: int):
    with Session(engine) as session:
        existente = session.exec(select(Fornecedor).where(Fornecedor.documento == dados.documento)).first()
        if existente:
            raise HTTPException(status_code=400, detail="Já existe fornecedor com este CPF/CNPJ")

        fornecedor = Fornecedor(
            nome=dados.nome,
            documento=dados.documento,
            telefone=dados.telefone,
            email=dados.email,
            prazo_medio_entrega_dias=dados.prazo_medio_entrega_dias,
        )
        try:
            session.add(fornecedor)
            session.commit()
            session.refresh(fornecedor)
            criar_log(funcionario_id, f"Cadastro de fornecedor: {fornecedor.nome}")
            return fornecedor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar fornecedor")


def mostrar_fornecedores():
    with Session(engine) as session:
        return session.exec(select(Fornecedor)).all()


def buscar_fornecedor(fornecedor_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
        return fornecedor


def atualizar_fornecedor(fornecedor_id: int, dados: FornecedorInput, funcionario_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")

        duplicado = session.exec(
            select(Fornecedor).where(Fornecedor.documento == dados.documento)
        ).first()
        if duplicado and duplicado.id != fornecedor.id:
            raise HTTPException(status_code=400, detail="CPF/CNPJ já cadastrado em outro fornecedor")

        fornecedor.nome = dados.nome
        fornecedor.documento = dados.documento
        fornecedor.telefone = dados.telefone
        fornecedor.email = dados.email
        fornecedor.prazo_medio_entrega_dias = dados.prazo_medio_entrega_dias

        try:
            session.commit()
            session.refresh(fornecedor)
            criar_log(funcionario_id, f"Atualização de fornecedor: {fornecedor.nome}")
            return fornecedor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar fornecedor")


def deletar_fornecedor(fornecedor_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
        try:
            session.delete(fornecedor)
            session.commit()
            return {"msg": "Fornecedor deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar fornecedor")
