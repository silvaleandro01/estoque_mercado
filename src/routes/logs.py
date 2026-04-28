from fastapi import APIRouter, Depends

from services.auth import get_funcionario, verificar_permissao
from logs.logs import listar_logs

router = APIRouter(prefix="/logs", tags=["Logs"])


@router.get("")
def ver_logs(funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return listar_logs()
