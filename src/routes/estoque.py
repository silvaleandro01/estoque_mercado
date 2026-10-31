from typing import List
from fastapi import APIRouter, Depends

from schemas.schemas import EstoqueCreate, EstoqueUpdate, EstoquePendenteOut, ConfirmarPendenteInput
from services.auth import get_funcionario, verificar_permissao
from repository.estoque import (
    criar_estoque, mostrar_produtos, buscar_estoque,
    atualizar_estoque, deletar_estoque,
    listar_pendentes, confirmar_pendente,
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


@router.get("/pendentes", response_model=List[EstoquePendenteOut])
def pendentes(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return listar_pendentes()


@router.post("/pendentes/{item_id}/confirmar")
def confirmar(item_id: int, dados: ConfirmarPendenteInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return confirmar_pendente(item_id, dados, funcionario.id)
