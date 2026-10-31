import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from fastapi import HTTPException
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlmodel import Session

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY não configurada. Defina a variável de ambiente SECRET_KEY "
        "(veja .env.exemplo) antes de iniciar a aplicação."
    )
ALGORITHM = "HS256"
TOKEN_EXPIRA_HORAS = int(os.getenv("TOKEN_EXPIRA_HORAS", "8"))

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_senha(senha: str) -> str:
    return _pwd_context.hash(senha)


def verificar_senha(senha: str, hash: str) -> bool:
    return _pwd_context.verify(senha, hash)


def criar_token(funcionario_id: int, is_admin: bool) -> str:
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(funcionario_id),
        "is_admin": is_admin,
        "iat": agora.timestamp(),
        "exp": (agora + timedelta(hours=TOKEN_EXPIRA_HORAS)).timestamp(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verificar_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
