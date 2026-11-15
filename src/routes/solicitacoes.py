from typing import List

from fastapi import APIRouter, Depends

from schemas.schemas import SolicitacaoInput, SolicitacaoResposta
from services.auth import get_funcionario, exigir_responder_solicitacao, pode_responder_solicitacao
from repository.solicitacoes import criar_solicitacao, listar_solicitacoes, responder_solicitacao

router = APIRouter(prefix="/solicitacoes", tags=["Solicitações de Compra"])


@router.post("/criar")
def criar(dados: SolicitacaoInput, funcionario=Depends(get_funcionario)):
    # Qualquer funcionário autenticado pode abrir uma solicitação -- ver
    # docstring de utils.database.Solicitacao.
    return criar_solicitacao(dados, funcionario.id)


@router.get("/listar")
def listar(funcionario=Depends(get_funcionario)) -> List[dict]:
    return listar_solicitacoes(funcionario.id, pode_responder_solicitacao(funcionario))


@router.post("/responder/{solicitacao_id}")
def responder(solicitacao_id: int, dados: SolicitacaoResposta, funcionario=Depends(get_funcionario)):
    exigir_responder_solicitacao(funcionario)
    return responder_solicitacao(solicitacao_id, dados, funcionario.id)
