from fastapi import APIRouter, Depends

from schemas.schemas import DespesaInput
from services.auth import get_funcionario, verificar_permissao
from repository.despesas import criar_despesa, listar_despesas

router = APIRouter(prefix="/despesas", tags=["Despesas"])

SETORES_PERMITIDOS = ("rh", "gerencia")


@router.post("/inserir")
def inserir(dados: DespesaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, SETORES_PERMITIDOS)
    return criar_despesa(dados, funcionario.id)


@router.get("/listar")
def listar(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, SETORES_PERMITIDOS)
    return listar_despesas()
