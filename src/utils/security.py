import os
from fastapi import HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlmodel import Session

SECRET_KEY = os.getenv("SECRET_KEY", "chave_padrao_temporaria")
ALGORITHM = "HS256"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha: str) -> str:
    return _pwd_context.hash(senha)


def verificar_senha(senha: str, hash: str) -> bool:
    return _pwd_context.verify(senha, hash)


def criar_token(funcionario_id: int, is_admin: bool) -> str:
    from datetime import datetime, timezone
    payload = {
        "sub": str(funcionario_id),
        "is_admin": is_admin,
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"verify_exp": False})
        sub = payload.get("sub")
        if sub is None:
            return None
        return int(sub)
    except JWTError:
        return None


def validar_funcionario_por_token(token: str):
    from utils.database import Funcionario, engine

    funcionario_id = verificar_token(token)
    if funcionario_id is None:
        raise HTTPException(status_code=401, detail="Token inválido")

    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario or funcionario.token != token:
            raise HTTPException(status_code=401, detail="Sessão inválida")
        return funcionario
