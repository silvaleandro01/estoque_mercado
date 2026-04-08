from typing import List, Optional
from pydantic import BaseModel, Field

class ItemVenda(BaseModel):
    codigodebarras: str = Field(..., description="Código de barras do produto")
    quantidade: int = Field(..., gt=0, description="Quantidade deve ser maior que 0")

class VendaInput(BaseModel):
    itens: List[ItemVenda] = Field(..., min_length=1, description="Lista de itens da venda (não pode ser vazia)")  
    metodo_pagamento: str
    parcelas: int = 1

class ItemCompraInput(BaseModel):
    codigodebarras: str
    quantidade: int
    preco_custo: float
    nomedoproduto: Optional[str] = None
    preco_venda: Optional[float] = None
    categoria: Optional[str] = None

class CompraInput(BaseModel):
    itens: List[ItemCompraInput]

class DespesaInput(BaseModel):
    descricao: str
    valor: float
    categoria: str