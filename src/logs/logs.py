from sqlmodel import Session, select
from utils.database import Log, engine


def criar_log(funcionario_id: int, tipo: str):
    with Session(engine) as session:
        log = Log(funcionario_id=funcionario_id, tipo_movimentacao=tipo)
        session.add(log)
        session.commit()


def listar_logs():
    with Session(engine) as session:
        return session.exec(select(Log)).all()
