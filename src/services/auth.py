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


def _setor_compras(funcionario: Funcionario) -> bool:
    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)
        return bool(setor and setor.tipo == "compras")


def exigir_registrar_compra(funcionario: Funcionario) -> bool:
    if funcionario.is_admin:
        return True
    if not _setor_compras(funcionario) or funcionario.cargo not in ("operacional", "gerente"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    return True


def exigir_gerenciar_compra(funcionario: Funcionario) -> bool:
    if funcionario.is_admin:
        return True
    if not _setor_compras(funcionario) or funcionario.cargo != "gerente":
        raise HTTPException(status_code=403, detail="Acesso negado")
    return True


def exigir_aprovar_compra(funcionario: Funcionario) -> bool:
    if funcionario.is_admin or funcionario.cargo == "diretoria":
        return True
    raise HTTPException(status_code=403, detail="Acesso negado")


def exigir_ver_compras(funcionario: Funcionario) -> bool:
    if funcionario.is_admin or funcionario.cargo == "diretoria" or _setor_compras(funcionario):
        return True
    raise HTTPException(status_code=403, detail="Acesso negado")
