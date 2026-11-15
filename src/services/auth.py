from typing import Sequence, Union
from fastapi import HTTPException, Header
from sqlmodel import Session

from utils.database import Funcionario, Setor, engine
from utils.security import validar_funcionario_por_token


def get_funcionario(authorization: str = Header(...)):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token inválido")
    token = authorization.split(" ")[1]
    return validar_funcionario_por_token(token)


def verificar_permissao(funcionario: Funcionario, rota: Union[str, Sequence[str]]):
    if funcionario.is_admin:
        return True
    setores_permitidos = (rota,) if isinstance(rota, str) else tuple(rota)
    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)
        if not setor or setor.tipo not in setores_permitidos:
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


def exigir_escrever_comunicado(funcionario: Funcionario) -> bool:
    if funcionario.is_admin or funcionario.cargo in ("gerente", "diretoria"):
        return True
    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)
        if setor and setor.tipo == "rh":
            return True
    raise HTTPException(status_code=403, detail="Acesso negado")


def exigir_ver_dashboard(funcionario: Funcionario) -> bool:
    # Mesmo gate usado pelo frontend para exibir o item "Dashboard" no menu
    # (ver checkAuth em frontend/app.js) -- só admin ou diretoria.
    if funcionario.is_admin or funcionario.cargo == "diretoria":
        return True
    raise HTTPException(status_code=403, detail="Acesso negado")


def exigir_gerenciar_venda(funcionario: Funcionario) -> bool:
    # Mesmo gate usado pelo frontend para exibir "Cancelar Venda" na tela de
    # Vendas do Dia (ver checkAuth em frontend/app.js, item 'vendas-dia'):
    # admin, diretoria, ou gerente do setor de vendas.
    if funcionario.is_admin or funcionario.cargo == "diretoria":
        return True
    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)
        if setor and setor.tipo == "vendas" and funcionario.cargo == "gerente":
            return True
    raise HTTPException(status_code=403, detail="Acesso negado")


def pode_responder_solicitacao(funcionario: Funcionario) -> bool:
    # Quem decide uma Solicitação de compra: admin, diretoria, ou gerente do
    # setor de compras (mesmo público de exigir_gerenciar_compra -- faz
    # sentido, já que a solicitação costuma virar insumo pra um pedido de
    # compra formal). Diferente de criar_solicitacao (qualquer funcionário
    # pode abrir uma), por isso não é só um "exigir_" -- GET /solicitacoes/
    # listar usa este retorno bool pra decidir o ESCOPO da listagem (todas
    # vs. só as próprias), não pra bloquear a rota inteira.
    return funcionario.is_admin or funcionario.cargo == "diretoria" or (
        _setor_compras(funcionario) and funcionario.cargo == "gerente"
    )


def exigir_responder_solicitacao(funcionario: Funcionario) -> bool:
    if pode_responder_solicitacao(funcionario):
        return True
    raise HTTPException(status_code=403, detail="Acesso negado")
