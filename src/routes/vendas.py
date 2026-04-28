from fastapi import APIRouter, Depends

from schemas.schemas import VendaInput
from services.auth import get_funcionario, verificar_permissao
from repository.vendas import criar_venda, vendas_do_dia

router = APIRouter(prefix="/vendas", tags=["Vendas"])


@router.post("/inserir")
def inserir(dados: VendaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return criar_venda(dados, funcionario.id)


@router.get("/vendasdodia")
def vendas_dia(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return vendas_do_dia()
