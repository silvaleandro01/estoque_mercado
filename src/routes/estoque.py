from fastapi import APIRouter, Depends

from schemas.schemas import EstoqueCreate, EstoqueUpdate
from services.auth import get_funcionario, verificar_permissao
from repository.estoque import (
    criar_estoque, mostrar_produtos, buscar_estoque,
    atualizar_estoque, deletar_estoque,
)

router = APIRouter(prefix="/estoque", tags=["Estoque"])


@router.post("/inserir")
def inserir(dados: EstoqueCreate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return criar_estoque(dados, funcionario.id)


@router.get("/mostrar")
def mostrar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return mostrar_produtos()


@router.get("/buscar/{estoque_id}")
def buscar(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return buscar_estoque(estoque_id)


@router.put("/atualizar/{estoque_id}")
def atualizar(estoque_id: int, dados: EstoqueUpdate, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return atualizar_estoque(estoque_id, dados, funcionario.id)


@router.delete("/deletar/{estoque_id}")
def deletar(estoque_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return deletar_estoque(estoque_id)
