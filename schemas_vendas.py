from typing import List
from pydantic import BaseModel, Field

# Representa um item da venda
class ItemVenda(BaseModel):
    codigodebarras: str = Field(..., description="Código de barras do produto")
    quantidade: int = Field(..., gt=0, description="Quantidade deve ser maior que 0")

# Representa a venda completa 
class VendaInput(BaseModel):
    itens: List[ItemVenda] = Field(..., min_length=1, description="Lista de itens da venda (não pode ser vazia)")  
    