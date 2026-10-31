from typing import List
from fastapi import APIRouter, Depends

from schemas.schemas import CompraInput, CompraOut, ItemCompraOut
from services.auth import (
    get_funcionario, exigir_registrar_compra, exigir_gerenciar_compra,
    exigir_aprovar_compra, exigir_ver_compras,
)
from repository.compras import (
    registrar_compra, listar_compras, buscar_itens_compra,
    encaminhar_compra, cancelar_compra, autorizar_compra, recusar_compra,
    compras_do_dia,
)

router = APIRouter(prefix="/compras", tags=["Compras"])


@router.post("/registrar")
def registrar(dados: CompraInput, funcionario=Depends(get_funcionario)):
    exigir_registrar_compra(funcionario)
    return registrar_compra(dados, funcionario.id)


@router.get("/listar", response_model=List[CompraOut])
def listar(funcionario=Depends(get_funcionario)):
    exigir_ver_compras(funcionario)
    return listar_compras()


@router.get("/comprasdodia")
def comprasdodia(funcionario=Depends(get_funcionario)):
    exigir_ver_compras(funcionario)
    return compras_do_dia()


@router.get("/{compra_id}/itens", response_model=List[ItemCompraOut])
def itens(compra_id: int, funcionario=Depends(get_funcionario)):
    exigir_ver_compras(funcionario)
    return buscar_itens_compra(compra_id)


@router.post("/encaminhar/{compra_id}")
def encaminhar(compra_id: int, funcionario=Depends(get_funcionario)):
    exigir_gerenciar_compra(funcionario)
    return encaminhar_compra(compra_id, funcionario.id)


@router.post("/cancelar/{compra_id}")
def cancelar(compra_id: int, funcionario=Depends(get_funcionario)):
    exigir_gerenciar_compra(funcionario)
    return cancelar_compra(compra_id, funcionario.id)


@router.post("/autorizar/{compra_id}")
def autorizar(compra_id: int, funcionario=Depends(get_funcionario)):
    exigir_aprovar_compra(funcionario)
    return autorizar_compra(compra_id, funcionario.id)


@router.post("/recusar/{compra_id}")
def recusar(compra_id: int, funcionario=Depends(get_funcionario)):
    exigir_aprovar_compra(funcionario)
    return recusar_compra(compra_id, funcionario.id)
