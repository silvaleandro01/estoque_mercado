from typing import List
from fastapi import APIRouter, Depends, Query

from schemas.schemas import PontoStatusOut, PontoRelatorioOut, PontoGeralItemOut
from services.auth import get_funcionario, verificar_permissao
from repository.pontos import bater_ponto, status_hoje, relatorio_funcionario, relatorio_geral

router = APIRouter(prefix="/pontos", tags=["Ponto Eletrônico"])

# Mesmo range aceito em schemas.FecharFolhaRequest -- achado do painel de
# revisão: sem isso, mes/ano inválidos (ex. mes=99) chegavam sem tratamento
# em _intervalo_mes (date(ano, mes, 1) levanta ValueError) e escapavam como
# 500 cru em vez do 422 limpo que o FastAPI já dá de graça com Query(...).
_MES = Query(..., ge=1, le=12)
_ANO = Query(..., ge=2000, le=2100)


@router.post("/bater")
def bater(funcionario=Depends(get_funcionario)):
    return bater_ponto(funcionario.id)


@router.get("/status", response_model=PontoStatusOut)
def status(funcionario=Depends(get_funcionario)):
    return status_hoje(funcionario.id)


@router.get("/meu-relatorio", response_model=PontoRelatorioOut)
def meu_relatorio(mes: int = _MES, ano: int = _ANO, funcionario=Depends(get_funcionario)):
    return relatorio_funcionario(funcionario.id, mes, ano)


@router.get("/rh/geral", response_model=List[PontoGeralItemOut])
def rh_geral(mes: int = _MES, ano: int = _ANO, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return relatorio_geral(mes, ano)


@router.get("/rh/funcionario/{funcionario_id}", response_model=PontoRelatorioOut)
def rh_funcionario(funcionario_id: int, mes: int = _MES, ano: int = _ANO, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return relatorio_funcionario(funcionario_id, mes, ano)
