from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Despesa, engine
from logs.logs import criar_log
from schemas.schemas import DespesaInput


def criar_despesa(dados: DespesaInput, funcionario_id: int):
    with Session(engine) as session:
        despesa = Despesa(
            descricao=dados.descricao,
            valor=dados.valor,
            categoria=dados.categoria,
            funcionario_id=funcionario_id,
        )
        try:
            session.add(despesa)
            session.commit()
            session.refresh(despesa)
            criar_log(funcionario_id, f"Despesa registrada: {despesa.descricao} (R$ {despesa.valor:.2f})")
            return despesa
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao registrar despesa")


def listar_despesas():
    with Session(engine) as session:
        return session.exec(select(Despesa)).all()
