from fastapi import APIRouter, Depends, HTTPException, Query

from schemas.schemas import FecharFolhaRequest, HoleriteOut
from services.auth import get_funcionario, verificar_permissao
from repository.folha import fechar_folha, meu_holerite, buscar_holerite, assinar_holerite

router = APIRouter(prefix="/folha", tags=["Folha de Pagamento"])

# Mesmo range aceito em schemas.FecharFolhaRequest -- achado do painel de
# revisão (ver também routes/pontos.py).
_MES = Query(..., ge=1, le=12)
_ANO = Query(..., ge=2000, le=2100)


@router.post("/fechar")
def fechar(dados: FecharFolhaRequest, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    return fechar_folha(dados.mes, dados.ano, funcionario.id)


@router.get("/meu-holerite", response_model=HoleriteOut)
def meu(mes: int = _MES, ano: int = _ANO, funcionario=Depends(get_funcionario)):
    holerite = meu_holerite(funcionario.id, mes, ano)
    if not holerite:
        raise HTTPException(status_code=404, detail="Holerite não encontrado para este período")
    return holerite


@router.get("/buscar-funcionario", response_model=HoleriteOut)
def buscar(funcionario_id: int, mes: int = _MES, ano: int = _ANO, funcionario=Depends(get_funcionario)):
    verificar_permissao(funcionario, "rh")
    holerite = buscar_holerite(funcionario_id, mes, ano)
    if not holerite:
        raise HTTPException(status_code=404, detail="Holerite não encontrado para este período")
    return holerite


@router.post("/assinar/{holerite_id}", response_model=HoleriteOut)
def assinar(holerite_id: int, funcionario=Depends(get_funcionario)):
    return assinar_holerite(holerite_id, funcionario.id)
