from sqlmodel import Session, select
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone, date
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext
import re
import os

# Importamos as constantes e modelos do database para manter a consistência
from database import Funcionario, FuncionarioCreate, Setor, engine, SECRET_KEY, ALGORITHM, SenhaHistorico

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def criar_token(funcionario_id: int, is_admin: bool, horas: int = 12):
    if is_admin:
        # Token vitalício (100 anos)
        expiracao = datetime.now(timezone.utc) + timedelta(days=365 * 100)
    else:
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

def validar_senha_forte(password: str):
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 8 caracteres")
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="A senha não pode ter mais de 72 caracteres (limite do sistema)")
    if not re.search("[a-z]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter letras minúsculas")
    if not re.search("[A-Z]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter letras maiúsculas")
    if not re.search("[0-9]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter números")
    if not re.search("[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter caracteres especiais")

def gerar_username(nome: str, sobrenome: str):
    return f"{nome.strip().lower()}.{sobrenome.strip().lower()}"

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

        return funcionario

def autenticar_funcionario(username: str, password: str = ""):
    with Session(engine) as session:
        # O username é nome.sobrenome
        partes = username.split(".")
        if len(partes) < 2:
             raise HTTPException(status_code=401, detail="Formato de usuário inválido (nome.sobrenome)")
        
        nome, sobrenome = partes[0], partes[1]
        funcionario = session.exec(
            select(Funcionario).where(
                Funcionario.nome.ilike(nome), 
                Funcionario.sobrenome.ilike(sobrenome)
            )
        ).first()

        if not funcionario:
            raise HTTPException(status_code=401, detail="Funcionário não encontrado")

        # Caso de Primeiro Acesso
        if funcionario.password_hash is None:
            return {"status": "primeiro_acesso", "funcionario_id": funcionario.id}

        # Verificar se a senha expirou (15 dias)
        if funcionario.last_password_change:
            dias_desde_troca = (datetime.now(timezone.utc) - funcionario.last_password_change.replace(tzinfo=timezone.utc)).days
            if dias_desde_troca >= 15:
                return {"status": "senha_expirada", "funcionario_id": funcionario.id}

        # Validar senha
        if not pwd_context.verify(password, funcionario.password_hash):
            raise HTTPException(status_code=401, detail="Senha incorreta")

        # Gerar Token de Sessão
        token, exp = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        funcionario.token_expiracao = exp
        session.add(funcionario)
        session.commit()
        
        return {"status": "sucesso", "token": token}

def definir_nova_senha(funcionario_id: int, nova_senha: str):
    validar_senha_forte(nova_senha)
    
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
             raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        # Verificar Histórico (não pode ser as 3 últimas)
        historico = session.exec(
            select(SenhaHistorico)
            .where(SenhaHistorico.funcionario_id == funcionario_id)
            .order_by(SenhaHistorico.data_criacao.desc())
            .limit(3)
        ).all()

        for registro in historico:
            if pwd_context.verify(nova_senha, registro.password_hash):
                raise HTTPException(status_code=400, detail="Você não pode usar as últimas 3 senhas")

        # Atualizar
        hash_novo = pwd_context.hash(nova_senha)
        funcionario.password_hash = hash_novo
        funcionario.last_password_change = datetime.now(timezone.utc)

        # Salvar no Histórico
        novo_historico = SenhaHistorico(funcionario_id=funcionario_id, password_hash=hash_novo)
        session.add(novo_historico)
        
        # Gerar novo token para o usuário entrar direto
        token, exp = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        funcionario.token_expiracao = exp
        
        session.add(funcionario)
        session.commit()
        
        return {"status": "sucesso", "token": token}

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