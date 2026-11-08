import re
from decimal import Decimal
from typing import List, Literal, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel

from utils.money import DecimalMoeda
from utils.quantidade import DecimalQuantidade

Cargo = Literal["operacional", "gerente", "diretoria"]

# Unidade de medida do produto: UN (unidade, vendido em peças inteiras),
# KG (quilo, venda por peso) ou L (litro, venda por volume). Seguindo o
# mesmo padrão já usado para `Cargo` neste projeto, a validação do valor
# fixo fica na camada Pydantic (Literal), e a coluna no banco é um simples
# VARCHAR -- não um ENUM do MySQL -- para não duplicar a regra em dois
# lugares (ver também `Funcionario.cargo`, que segue a mesma convenção).
UnidadeMedida = Literal["UN", "KG", "L"]

# Todas as colunas monetárias do banco são DECIMAL(10, 2): no máximo 8
# dígitos inteiros + 2 decimais (até 99999999.99). Sem essa validação aqui,
# um valor absurdamente grande (ex.: 999999999999.99) passa pelo Pydantic
# sem erro e só quebra lá na frente, contra o banco, com um erro feio em vez
# de um 422 claro. `max_digits`/`decimal_places` do Pydantic mapeiam 1:1
# para essa mesma restrição do DECIMAL(10, 2).
DECIMAL_10_2 = {"max_digits": 10, "decimal_places": 2}

# Mesma ideia de DECIMAL_10_2, mas para as colunas de quantidade (DECIMAL(10,
# 3)): produtos vendidos por peso/volume (KG/L) podem ter até 3 casas
# decimais (precisão de grama/mililitro), diferente de dinheiro (2 casas).
DECIMAL_10_3 = {"max_digits": 10, "decimal_places": 3}


class LoginRequest(BaseModel):
    username: str
    senha: str


class FuncionarioCreate(BaseModel):
    nome: str
    sobrenome: str
    data_nascimento: date
    genero: str
    possui_filhos: bool
    setor_id: int
    cargo: Cargo = "operacional"
    senha: Optional[str] = None
    cpf: str
    email: str
    cep: str
    estado: str
    cidade: str
    bairro: str
    rua: str
    numero: str

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, v: str) -> str:
        cpf = re.sub(r"\D", "", v)
        if len(cpf) != 11 or len(set(cpf)) == 1:
            raise ValueError("CPF inválido")
        for i in range(9, 11):
            soma = sum(int(cpf[j]) * (i + 1 - j) for j in range(i))
            if (soma * 10 % 11) % 10 != int(cpf[i]):
                raise ValueError("CPF inválido")
        return cpf

    @field_validator("cep")
    @classmethod
    def validar_cep(cls, v: str) -> str:
        cep = re.sub(r"\D", "", v)
        if len(cep) != 8:
            raise ValueError("CEP deve ter 8 dígitos")
        return cep

    @field_validator("email")
    @classmethod
    def validar_email(cls, v: str) -> str:
        v = v.strip().lower()
        partes = v.split("@")
        if len(partes) != 2 or not partes[0] or "." not in partes[1]:
            raise ValueError("Email inválido")
        return v


class FuncionarioOut(BaseModel):
    id: int
    nome: str
    sobrenome: str
    data_nascimento: date
    genero: str
    possui_filhos: bool
    setor_id: int
    cargo: Cargo
    is_admin: bool
    cpf: Optional[str] = None
    email: Optional[str] = None
    cep: Optional[str] = None
    estado: Optional[str] = None
    cidade: Optional[str] = None
    bairro: Optional[str] = None
    rua: Optional[str] = None
    numero: Optional[str] = None
    senha_temporaria: bool

    model_config = {"from_attributes": True}


class SetorCreate(SQLModel):
    nome: str
    tipo: str


class EstoqueCreate(BaseModel):
    titulo: Optional[str] = None
    nomedoproduto: str
    quantidade: Decimal = Field(..., ge=0, **DECIMAL_10_3)
    unidade_medida: UnidadeMedida = "UN"
    preco: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    preco_custo: Optional[Decimal] = Field(default=Decimal("0.00"), ge=0, **DECIMAL_10_2)
    codigodebarras: str
    categoria: str


class EstoqueUpdate(BaseModel):
    titulo: Optional[str] = None
    nomedoproduto: str
    quantidade: Decimal = Field(..., ge=0, **DECIMAL_10_3)
    unidade_medida: UnidadeMedida = "UN"
    preco: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    codigodebarras: str
    categoria: str


class ItemVendaSchema(BaseModel):
    codigodebarras: str
    quantidade: Decimal = Field(..., gt=0, **DECIMAL_10_3)


class VendaInput(BaseModel):
    itens: List[ItemVendaSchema] = Field(..., min_length=1)


class TrocarSenhaRequest(BaseModel):
    senha_atual: str
    nova_senha: str


class RecuperarSenhaRequest(BaseModel):
    cpf: str

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, v: str) -> str:
        return re.sub(r"\D", "", v)


class ItemCompraInput(BaseModel):
    codigodebarras: str
    quantidade: Decimal = Field(..., gt=0, **DECIMAL_10_3)
    preco_custo: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    nomedoproduto: str
    preco_venda: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    categoria: str


class CompraInput(BaseModel):
    itens: List[ItemCompraInput] = Field(..., min_length=1)


class ItemCompraOut(BaseModel):
    nomedoproduto: str
    codigodebarras: str
    quantidade: DecimalQuantidade
    preco_custo: DecimalMoeda
    total: DecimalMoeda

    model_config = {"from_attributes": True}


class CompraOut(BaseModel):
    id: int
    data: datetime
    solicitante: str
    aprovador: Optional[str] = None
    valor_total: DecimalMoeda
    status: str

    model_config = {"from_attributes": True}


class EstoquePendenteOut(BaseModel):
    id: int
    compra_id: int
    data_entrada: Optional[datetime] = None
    nomedoproduto: str
    codigodebarras: str
    quantidade: DecimalQuantidade
    preco_custo: DecimalMoeda
    preco_venda: Optional[DecimalMoeda] = None

    model_config = {"from_attributes": True}


class ConfirmarPendenteInput(BaseModel):
    nomedoproduto: str
    codigodebarras: str
    preco_venda: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    categoria: str


class DespesaInput(BaseModel):
    descricao: str
    valor: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    categoria: Literal["Fixo", "Variavel", "Manutencao", "Outros"]


class ComunicadoInput(BaseModel):
    titulo: str
    conteudo: str
    para_todos: bool = True
    destinatarios: List[int] = []
