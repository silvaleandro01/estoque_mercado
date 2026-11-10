from typing import List
from fastapi import APIRouter, Depends

from schemas.schemas import FornecedorInput, FornecedorOut
from services.auth import get_funcionario, verificar_permissao
from repository.fornecedores import (
    criar_fornecedor, mostrar_fornecedores, buscar_fornecedor,
    atualizar_fornecedor, deletar_fornecedor,
)

# Mesmo gate de permissão de routes/estoque.py ("estoque"): cadastro de
# fornecedor é parte do mesmo domínio de cadastro de produto, administrado
# pelo mesmo time.
router = APIRouter(prefix="/fornecedores", tags=["Fornecedores"])


@router.post("/inserir", response_model=FornecedorOut)
def inserir(dados: FornecedorInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return criar_fornecedor(dados, funcionario.id)


@router.get("/mostrar", response_model=List[FornecedorOut])
def mostrar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return mostrar_fornecedores()


@router.get("/buscar/{fornecedor_id}", response_model=FornecedorOut)
def buscar(fornecedor_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return buscar_fornecedor(fornecedor_id)


@router.put("/atualizar/{fornecedor_id}", response_model=FornecedorOut)
def atualizar(fornecedor_id: int, dados: FornecedorInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return atualizar_fornecedor(fornecedor_id, dados, funcionario.id)


@router.delete("/deletar/{fornecedor_id}")
def deletar(fornecedor_id: int, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "estoque")
    return deletar_fornecedor(fornecedor_id)
