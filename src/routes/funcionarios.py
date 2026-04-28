from fastapi import APIRouter, Depends

from schemas.schemas import FuncionarioCreate, LoginRequest, TrocarSenhaRequest, RecuperarSenhaRequest
from services.auth import get_funcionario, verificar_permissao
from repository.funcionarios import (
    autenticar_funcionario, criar_funcionario, listar_funcionarios, buscar_funcionario,
    atualizar_funcionario, deletar_funcionario, renovar_token, trocar_senha, recuperar_senha,
)

router = APIRouter(prefix="/funcionarios", tags=["Funcionários"])


@router.post("/login")
def login(dados: LoginRequest):
    return autenticar_funcionario(dados)


@router.post("/recuperar-senha")
def recuperar(dados: RecuperarSenhaRequest):
    return recuperar_senha(dados)


@router.post("/criar")
def criar(dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return criar_funcionario(dados)


@router.get("/listar")
def listar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_funcionarios()


@router.get("/buscar/{id}")
def buscar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return buscar_funcionario(id)


@router.put("/atualizar/{id}")
def atualizar(id: int, dados: FuncionarioCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_funcionario(id, dados)


@router.delete("/deletar/{id}")
def deletar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_funcionario(id)


@router.patch("/trocar-senha")
def trocar(dados: TrocarSenhaRequest, funcionario=Depends(get_funcionario)):
    return trocar_senha(funcionario.id, dados)


rh_router = APIRouter(prefix="/rh", tags=["RH"])


@rh_router.post("/renovar-token/{id}")
def renovar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return renovar_token(id)
