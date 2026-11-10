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

# Lockout de login (fix/login-rate-limiting) -- ver
# repository/funcionarios.py::autenticar_funcionario. Quantas tentativas de
# senha errada seguidas uma conta aguenta antes de ser bloqueada
# temporariamente, e por quantos minutos o bloqueio dura.
LOGIN_MAX_TENTATIVAS = int(os.getenv("LOGIN_MAX_TENTATIVAS", "5"))
LOGIN_BLOQUEIO_MINUTOS = int(os.getenv("LOGIN_BLOQUEIO_MINUTOS", "15"))

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Hash bcrypt fixo, DUMMY -- não corresponde a nenhuma senha real de nenhum
# funcionário (gerado uma única vez com
# `_pwd_context.hash("dummy-tempo-constante-estoque-mercado-nao-e-senha-real")`
# e colado aqui como literal). Usado por autenticar_funcionario para rodar
# verificar_senha() mesmo quando o usuário não existe ou não tem senha
# definida, só para gastar um tempo de CPU parecido com o caso "usuário
# existe, senha errada".
#
# Por quê: bcrypt é propositalmente lento (dezenas a centenas de ms por
# verificação). Sem essa chamada "de mentira", os dois casos abaixo teriam
# tempo de resposta bem diferente, mesmo com a mensagem de erro já
# unificada -- e essa diferença de tempo, medida de fora, vazaria de volta
# a mesma informação (quais usernames existem) que a unificação da
# mensagem tenta esconder.
#
# Por que precisa ser um literal FIXO (hardcoded) em vez de gerado em
# runtime (ex.: `_pwd_context.hash(secrets.token_hex())` a cada chamada):
# gerar o hash na hora custaria exatamente o mesmo tempo de CPU do bcrypt
# que a própria verificação (hash e verify são a mesma operação de custo,
# bcrypt só compara reaplicando o hash) -- ou seja, pagaria o custo do
# bcrypt DUAS vezes (gerar + verificar) em vez de uma só, tornando a
# resposta de todo login mais lenta à toa, sem nenhum ganho de segurança:
# o valor em si não precisa ser secreto nem imprevisível (não protege
# nenhuma senha real), só precisa ser um hash bcrypt válido para
# verificar_senha() gastar o tempo de CPU equivalente.
HASH_DUMMY_LOGIN = "$2b$12$CsmM0OyPNva84/ltbP4ej.4eUGhqFfk2NP5G4iBUwkgudt23aShQO"


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
