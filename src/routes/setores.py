from fastapi import APIRouter, Depends

from schemas.schemas import SetorCreate
from services.auth import get_funcionario, verificar_permissao
from repository.setores import (
    criar_setor, listar_setores, buscar_setor,
    atualizar_setor, deletar_setor,
)

router = APIRouter(prefix="/setores", tags=["Setores"])


@router.post("/criar")
def criar(setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return criar_setor(setor)


@router.get("/listar")
def listar(funcionario=Depends(get_funcionario)):
    return listar_setores()


@router.get("/{id}")
def buscar(id: int, funcionario=Depends(get_funcionario)):
    return buscar_setor(id)


@router.put("/{id}")
def atualizar(id: int, setor: SetorCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return atualizar_setor(id, setor)


@router.delete("/{id}")
def deletar(id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return deletar_setor(id)
