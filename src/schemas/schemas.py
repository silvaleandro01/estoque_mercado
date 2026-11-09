import re
from decimal import Decimal
from typing import List, Literal, Optional
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator
from sqlmodel import SQLModel

from utils.money import DecimalMoeda
from utils.quantidade import DecimalQuantidade
from utils.documentos import validar_cpf as _validar_cpf, validar_cpf_ou_cnpj

Cargo = Literal["operacional", "gerente", "diretoria"]

# Unidade de medida do produto: UN (unidade, vendido em peças inteiras),
# KG (quilo, venda por peso) ou L (litro, venda por volume). Seguindo o
# mesmo padrão já usado para `Cargo` neste projeto, a validação do valor
# fixo fica na camada Pydantic (Literal), e a coluna no banco é um simples
# VARCHAR -- não um ENUM do MySQL -- para não duplicar a regra em dois
# lugares (ver também `Funcionario.cargo`, que segue a mesma convenção).
UnidadeMedida = Literal["UN", "KG", "L"]

# Tipos de movimentação de estoque (Fase 4 -- "histórico de movimentações").
# Mesmo padrão de `Cargo`/`UnidadeMedida`: valor fixo validado aqui na camada
# Pydantic, coluna no banco (MovimentacaoEstoque.tipo) um VARCHAR simples,
# sem ENUM do MySQL. Só ENTRADA_COMPRA, VENDA e AJUSTE_INVENTARIO têm código
# que realmente os gera nesta fase -- os demais (CANCELAMENTO_VENDA, PERDA,
# QUEBRA, VENCIMENTO) já ficam disponíveis no tipo para quando as fases
# futuras que os disparam chegarem (ver docstring de
# utils.database.MovimentacaoEstoque).
TipoMovimentacao = Literal[
    "ENTRADA_COMPRA", "VENDA", "CANCELAMENTO_VENDA",
    "PERDA", "QUEBRA", "VENCIMENTO", "AJUSTE_INVENTARIO",
]

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
        return _validar_cpf(v)

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
    estoque_minimo: Decimal = Field(default=Decimal("0.000"), ge=0, **DECIMAL_10_3)
    preco: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    preco_custo: Optional[Decimal] = Field(default=Decimal("0.00"), ge=0, **DECIMAL_10_2)
    codigodebarras: str
    categoria: str
    fornecedor_id: Optional[int] = None


class EstoqueUpdate(BaseModel):
    """
    DECISÃO DE ARQUITETURA (Fase 4 -- "histórico de movimentações"): até a
    Fase 3, este schema também incluía `quantidade`, e PUT /estoque/atualizar
    era o único ponto de alteração de saldo que não vinha de um evento de
    negócio claro (venda, compra) -- permitia mudar a quantidade livremente,
    sem pedir motivo nenhum. A partir desta fase, alteração manual de saldo
    (correção de inventário) tem um endpoint PRÓPRIO e dedicado
    (POST /estoque/{id}/ajustar-inventario, ver schemas.AjusteInventarioInput
    e repository.estoque.ajustar_inventario), que exige `motivo` e gera uma
    movimentação AJUSTE_INVENTARIO -- um fluxo de inventário é conceitualmente
    diferente de "editar o cadastro do produto". Por isso `quantidade` saiu
    deste schema: PUT /estoque/atualizar agora só edita METADADO do produto
    (nome, preço, categoria, etc.), nunca mais o saldo.
    """
    titulo: Optional[str] = None
    nomedoproduto: str
    # Diferente de EstoqueCreate (onde faz sentido ter default, já que é um
    # cadastro novo), aqui os dois campos são obrigatórios -- sem default --
    # igual aos outros campos deste schema (nomedoproduto, preco, etc.). Um
    # PUT que esqueça de enviar unidade_medida/estoque_minimo não pode
    # resetar silenciosamente esses valores do produto para "UN"/0 --
    # precisa falhar com 422 e deixar claro que o payload está incompleto.
    unidade_medida: UnidadeMedida
    estoque_minimo: Decimal = Field(..., ge=0, **DECIMAL_10_3)
    preco: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    codigodebarras: str
    categoria: str
    fornecedor_id: Optional[int] = None


class AjusteInventarioInput(BaseModel):
    """Entrada do novo endpoint POST /estoque/{id}/ajustar-inventario (Fase
    4), a única forma de corrigir manualmente o saldo de um produto a partir
    desta fase (ver docstring de EstoqueUpdate). `nova_quantidade` é o saldo
    ABSOLUTO final do produto após a contagem/correção (não um delta) --
    mesmo contrato que PUT /estoque/atualizar já usava para `quantidade`
    antes desta fase, só que agora isolado num endpoint que exige motivo.
    `motivo` é SEMPRE obrigatório, diferente de ENTRADA_COMPRA/VENDA (onde o
    próprio tipo + referência à compra/venda já explica a origem) -- um
    ajuste de inventário só existe porque algo precisa ser explicado (perda
    não contabilizada, erro de contagem anterior, etc.).
    """
    nova_quantidade: Decimal = Field(..., ge=0, **DECIMAL_10_3)
    motivo: str = Field(..., min_length=1)

    @field_validator("motivo")
    @classmethod
    def validar_motivo(cls, v: str) -> str:
        """Mesma razão de ConfirmarPendenteInput.validar_codigo_lote:
        `min_length=1` sozinho aceita uma string só de espaços em branco."""
        v = v.strip()
        if not v:
            raise ValueError("motivo não pode ser vazio")
        return v


class MovimentacaoEstoqueOut(BaseModel):
    id: int
    estoque_id: int
    lote_id: Optional[int] = None
    tipo: TipoMovimentacao
    quantidade: DecimalQuantidade
    motivo: Optional[str] = None
    # Optional (não mais int obrigatório): CRÍTICO 1 da revisão da Fase 4 --
    # ON DELETE SET NULL na FK (ver utils.database.MovimentacaoEstoque) faz
    # este campo virar NULL quando o funcionário autor é excluído depois,
    # preservando o histórico de movimentação (auditoria) em vez de apagá-lo
    # ou bloquear a exclusão do funcionário.
    funcionario_id: Optional[int] = None
    data: datetime

    model_config = {"from_attributes": True}


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
    fornecedor_id: Optional[int] = None


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
    fornecedor: Optional[str] = None

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
    # Só usados quando o item pendente vira um PRODUTO NOVO no estoque (não
    # existia produto com esse código de barras ainda) -- se o produto já
    # existir, o lançamento só incrementa a quantidade dele, mantendo a
    # unidade de medida e o estoque mínimo já cadastrados (mesma regra já
    # aplicada em criar_estoque() para incremento de produto existente).
    unidade_medida: UnidadeMedida = "UN"
    estoque_minimo: Decimal = Field(default=Decimal("0.000"), ge=0, **DECIMAL_10_3)
    # Lote e validade (Fase 3): toda confirmação de pendente agora cria um
    # registro em `Lote` correspondente a esta entrada -- codigo_lote é
    # obrigatório (identifica fisicamente o lote recebido), validade é
    # opcional (nem todo produto de mercado é perecível de verdade -- ex.:
    # utensílio, produto de limpeza -- mas quando o produto vence, o
    # formulário deve sempre informar a data real).
    codigo_lote: str = Field(..., min_length=1)
    validade: Optional[date] = None

    @field_validator("codigo_lote")
    @classmethod
    def validar_codigo_lote(cls, v: str) -> str:
        """`min_length=1` sozinho aceita uma string composta só de espaços
        em branco (ex.: "   ") -- espaço conta como caractere para o
        Pydantic. Normaliza removendo espaços nas pontas e rejeita se
        sobrar vazio, consistente com o restante do lote/validade
        exigindo um código de lote de verdade."""
        v = v.strip()
        if not v:
            raise ValueError("codigo_lote não pode ser vazio")
        return v


class LoteAlertaOut(BaseModel):
    lote_id: int
    estoque_id: int
    nomedoproduto: str
    codigodebarras: str
    codigo_lote: str
    quantidade: DecimalQuantidade
    validade: date
    # Negativo = já vencido há N dias; positivo = vence em N dias.
    dias_restantes: int

    model_config = {"from_attributes": True}


class AlertaVencimentoOut(BaseModel):
    dias: int
    vencendo: List[LoteAlertaOut]
    vencidos: List[LoteAlertaOut]


class FornecedorInput(BaseModel):
    nome: str
    documento: str  # CPF ou CNPJ
    telefone: Optional[str] = None
    email: Optional[str] = None
    prazo_medio_entrega_dias: Optional[int] = Field(default=None, ge=0)

    @field_validator("documento")
    @classmethod
    def validar_documento(cls, v: str) -> str:
        return validar_cpf_ou_cnpj(v)

    @field_validator("email")
    @classmethod
    def validar_email(cls, v):
        if v is None:
            return v
        v = v.strip().lower()
        partes = v.split("@")
        if len(partes) != 2 or not partes[0] or "." not in partes[1]:
            raise ValueError("Email inválido")
        return v


class FornecedorOut(BaseModel):
    id: int
    nome: str
    documento: str
    telefone: Optional[str] = None
    email: Optional[str] = None
    prazo_medio_entrega_dias: Optional[int] = None

    model_config = {"from_attributes": True}


class DespesaInput(BaseModel):
    descricao: str
    valor: Decimal = Field(..., gt=0, **DECIMAL_10_2)
    categoria: Literal["Fixo", "Variavel", "Manutencao", "Outros"]


class ComunicadoInput(BaseModel):
    titulo: str
    conteudo: str
    para_todos: bool = True
    destinatarios: List[int] = []
