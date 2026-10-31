import re
from typing import List, Literal, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel

Cargo = Literal["operacional", "gerente", "diretoria"]


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
    quantidade: int = Field(..., ge=0)
    preco: float = Field(..., gt=0)
    preco_custo: Optional[float] = Field(default=0.0, ge=0)
    codigodebarras: str
    categoria: str


class EstoqueUpdate(BaseModel):
    titulo: Optional[str] = None
    nomedoproduto: str
    quantidade: int = Field(..., ge=0)
    preco: float = Field(..., gt=0)
    codigodebarras: str
    categoria: str


class ItemVendaSchema(BaseModel):
    codigodebarras: str
    quantidade: int = Field(..., gt=0)


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
    quantidade: int = Field(..., gt=0)
    preco_custo: float = Field(..., gt=0)
    nomedoproduto: str
    preco_venda: float = Field(..., gt=0)
    categoria: str


class CompraInput(BaseModel):
    itens: List[ItemCompraInput] = Field(..., min_length=1)


class ItemCompraOut(BaseModel):
    nomedoproduto: str
    codigodebarras: str
    quantidade: int
    preco_custo: float
    total: float

    model_config = {"from_attributes": True}


class CompraOut(BaseModel):
    id: int
    data: datetime
    solicitante: str
    aprovador: Optional[str] = None
    valor_total: float
    status: str

    model_config = {"from_attributes": True}


class EstoquePendenteOut(BaseModel):
    id: int
    compra_id: int
    data_entrada: Optional[datetime] = None
    nomedoproduto: str
    codigodebarras: str
    quantidade: int
    preco_custo: float
    preco_venda: Optional[float] = None

    model_config = {"from_attributes": True}


class ConfirmarPendenteInput(BaseModel):
    nomedoproduto: str
    codigodebarras: str
    preco_venda: float = Field(..., gt=0)
    categoria: str


class DespesaInput(BaseModel):
    descricao: str
    valor: float = Field(..., gt=0)
    categoria: Literal["Fixo", "Variavel", "Manutencao", "Outros"]


class ComunicadoInput(BaseModel):
    titulo: str
    conteudo: str
    para_todos: bool = True
    destinatarios: List[int] = []
