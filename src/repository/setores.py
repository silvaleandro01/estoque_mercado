from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Setor, engine
from schemas.schemas import SetorCreate


def criar_setor(dados: SetorCreate):
    with Session(engine) as session:
        if session.exec(select(Setor).where(Setor.tipo == dados.tipo)).first():
            raise HTTPException(status_code=400, detail="Tipo de setor já existe")

        novo_setor = Setor(nome=dados.nome, tipo=dados.tipo)
        session.add(novo_setor)
        try:
            session.commit()
            session.refresh(novo_setor)
            return novo_setor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar setor")


def listar_setores():
    with Session(engine) as session:
        return session.exec(select(Setor)).all()


def buscar_setor(id: int):
    with Session(engine) as session:
        setor = session.get(Setor, id)
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")
        return setor


def atualizar_setor(id: int, dados: SetorCreate):
    with Session(engine) as session:
        setor = session.get(Setor, id)
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")

        existente = session.exec(
            select(Setor).where(Setor.tipo == dados.tipo, Setor.id != id)
        ).first()
        if existente:
            raise HTTPException(status_code=400, detail="Tipo já está em uso")

        setor.nome = dados.nome
        setor.tipo = dados.tipo
        try:
            session.commit()
            session.refresh(setor)
            return setor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar setor")


def deletar_setor(id: int):
    with Session(engine) as session:
        setor = session.get(Setor, id)
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")
        try:
            session.delete(setor)
            session.commit()
            return {"msg": "Setor deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar setor")
