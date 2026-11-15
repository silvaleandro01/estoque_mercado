from fastapi import APIRouter, Depends

from schemas.schemas import VendaInput
from services.auth import get_funcionario, verificar_permissao, exigir_ver_dashboard, exigir_gerenciar_venda
from repository.vendas import criar_venda, vendas_do_dia, dashboard_stats, cancelar_venda

router = APIRouter(prefix="/vendas", tags=["Vendas"])


@router.post("/inserir")
def inserir(dados: VendaInput, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return criar_venda(dados, funcionario.id)


@router.get("/vendasdodia")
def vendas_dia(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "vendas")
    return vendas_do_dia()


@router.get("/dashboard-stats")
def dashboard_stats_route(funcionario=Depends(get_funcionario)):
    exigir_ver_dashboard(funcionario)
    return dashboard_stats()


@router.delete("/cancelar/{venda_id}")
def cancelar(venda_id: int, funcionario=Depends(get_funcionario)):
    exigir_gerenciar_venda(funcionario)
    return cancelar_venda(venda_id, funcionario.id)
