from fastapi import HTTPException, Header
from sqlmodel import Session

from utils.database import Funcionario, Setor, engine
from utils.security import validar_funcionario_por_token


def get_funcionario(authorization: str = Header(...)):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")
    token = authorization.split(" ")[1]
    return validar_funcionario_por_token(token)


def verificar_permissao(funcionario: Funcionario, rota: str):
    if funcionario.is_admin:
        return True
    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)
        if not setor or setor.tipo != rota:
            raise HTTPException(status_code=403, detail="Acesso negado")
    return True
