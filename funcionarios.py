from sqlmodel import Session, select
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone, date
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
import os

# Importamos as constantes e modelos do database para manter a consistência
from database import Funcionario, FuncionarioCreate, Setor, engine, SECRET_KEY, ALGORITHM

def criar_token(funcionario_id: int, is_admin: bool, horas: int = 12):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=horas)

    payload = {
        "sub": str(funcionario_id),
        "exp": expiracao,
        "is_admin": is_admin
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expiracao

def verificar_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        sub = payload.get("sub")
        if sub is None:
            return None

        return int(sub)

    except (ExpiredSignatureError, JWTError):
        return None

def converter_data(data_str: str):
    try:
        return date.fromisoformat(data_str)
    except:
        raise HTTPException(status_code=400, detail="Data inválida, use YYYY-MM-DD")

def criar_funcionario(dados: FuncionarioCreate):
    with Session(engine) as session:

        dados_dict = dados.model_dump()

        if isinstance(dados_dict.get("data_nascimento"), str):
            dados_dict["data_nascimento"] = converter_data(dados_dict["data_nascimento"])

        funcionario = Funcionario(**dados_dict)

        try:
            session.add(funcionario)
            session.commit()
            session.refresh(funcionario)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar funcionário")

        token, exp = criar_token(funcionario.id, False)

        funcionario.token = token
        funcionario.token_expiracao = exp

        session.add(funcionario)
        session.commit()
        session.refresh(funcionario)

        return funcionario

def listar_funcionarios():
    with Session(engine) as session:
        return session.exec(select(Funcionario)).all()

def buscar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        return funcionario

def atualizar_funcionario(funcionario_id: int, dados: FuncionarioCreate):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        update_data = dados.model_dump()

        if "data_nascimento" in update_data:
            if isinstance(update_data["data_nascimento"], str):
                update_data["data_nascimento"] = converter_data(update_data["data_nascimento"])

        for key, value in update_data.items():
            setattr(funcionario, key, value)

        try:
            session.commit()
            session.refresh(funcionario)
            return funcionario
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar funcionário")

def deletar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        try:
            session.delete(funcionario)
            session.commit()
            return {"msg": "Funcionário deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar funcionário")

def validar_funcionario_por_token(token: str):
    funcionario_id = verificar_token(token)

    if funcionario_id is None:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        agora = datetime.now(timezone.utc)

        expiracao = funcionario.token_expiracao
        if expiracao and expiracao.tzinfo is None:
            expiracao = expiracao.replace(tzinfo=timezone.utc)

        if not expiracao or expiracao < agora:
            raise HTTPException(status_code=401, detail="Token expirado")

        return funcionario

def verificar_permissao(funcionario: Funcionario, setores_permitidos: str | list[str]):
    if funcionario.is_admin:
        return True

    if isinstance(setores_permitidos, str):
        setores_permitidos = [setores_permitidos]

    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)

        # Tornamos a comparação insensível a maiúsculas/minúsculas
        if not setor or setor.tipo.lower() not in [s.lower() for s in setores_permitidos]:
             raise HTTPException(status_code=403, detail="Acesso negado")

    return True


def renovar_token(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        token, exp = criar_token(funcionario_id, funcionario.is_admin)

        funcionario.token = token
        funcionario.token_expiracao = exp

        try:
            session.commit()
            session.refresh(funcionario)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao renovar token")

        return {
            "token": token,
            "expiracao": exp
        }