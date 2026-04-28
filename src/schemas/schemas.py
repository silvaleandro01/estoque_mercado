import re
from typing import List, Optional
from datetime import date
from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel


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
