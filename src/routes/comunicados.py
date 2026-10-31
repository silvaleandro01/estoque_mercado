from fastapi import APIRouter, Depends

from schemas.schemas import ComunicadoInput
from services.auth import get_funcionario, exigir_escrever_comunicado
from repository.comunicados import (
    criar_comunicado, listar_comunicados, contar_nao_lidos, marcar_como_lido,
)

router = APIRouter(prefix="/comunicados", tags=["Comunicados"])


@router.post("/criar")
def criar(dados: ComunicadoInput, funcionario=Depends(get_funcionario)):
    exigir_escrever_comunicado(funcionario)
    return criar_comunicado(dados, funcionario.id)


@router.get("/listar")
def listar(funcionario=Depends(get_funcionario)):
    return listar_comunicados(funcionario.id)


@router.get("/nao-lidos")
def nao_lidos(funcionario=Depends(get_funcionario)):
    return contar_nao_lidos(funcionario.id)


@router.post("/marcar-lido/{destinatario_id}")
def marcar_lido(destinatario_id: int, funcionario=Depends(get_funcionario)):
    return marcar_como_lido(destinatario_id, funcionario.id)
