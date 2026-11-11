import os
import secrets
import string
from decimal import Decimal
from typing import Optional
from datetime import datetime, timezone, date
from sqlmodel import Field, SQLModel, UniqueConstraint, create_engine, Session, select
from dotenv import load_dotenv

from utils.money import DecimalMoeda
from utils.quantidade import DecimalQuantidade

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./database.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}


class Setor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    tipo: str = Field(index=True, unique=True)


class Funcionario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    sobrenome: str
    data_nascimento: date
    genero: str
    possui_filhos: bool
    setor_id: int = Field(foreign_key="setor.id", index=True)
    cargo: str = Field(default="operacional")
    is_admin: bool = Field(default=False)
    cpf: Optional[str] = Field(default=None, unique=True, index=True)
    email: Optional[str] = Field(default=None, unique=True, index=True)
    cep: Optional[str] = Field(default=None)
    estado: Optional[str] = Field(default=None)
    cidade: Optional[str] = Field(default=None)
    bairro: Optional[str] = Field(default=None)
    rua: Optional[str] = Field(default=None)
    numero: Optional[str] = Field(default=None)
    password_hash: Optional[str] = Field(default=None)
    senha_atualizada_em: Optional[datetime] = Field(default=None)
    senha_temporaria: bool = Field(default=False)
    token: Optional[str] = Field(default=None, index=True)
    # Lockout de login (fix/login-rate-limiting) -- ver
    # repository/funcionarios.py::autenticar_funcionario. Contagem de
    # tentativas de senha errada consecutivas e, se o limite configurável for
    # atingido, até quando a conta fica temporariamente bloqueada.
    tentativas_login_falhas: int = Field(default=0)
    bloqueado_ate: Optional[datetime] = Field(default=None)
    # Ponto eletrônico/folha de pagamento: `bate_ponto` decide se o
    # funcionário usa o relógio de ponto (ver repository/pontos.py) e entra
    # na consolidação automática de fechar_folha -- cargo de confiança
    # (diretoria) tipicamente não bate ponto (CLT art. 62, II), mas fica
    # configurável por funcionário, não travado só no cargo. `cargo_confianca`
    # é só um rótulo informativo, sempre derivado de `cargo == "diretoria"`
    # no backend (nunca aceito como input do cliente -- ver
    # criar_funcionario/atualizar_funcionario) para não divergir do cargo
    # real do funcionário.
    bate_ponto: bool = Field(default=True)
    cargo_confianca: bool = Field(default=False)


class HistoricoSenha(SQLModel, table=True):
    __tablename__ = "historico_senha"
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    password_hash: str
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Fornecedor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    # CPF (11 dígitos) ou CNPJ (14 dígitos) -- validado por dígito
    # verificador na camada Pydantic (schemas.FornecedorInput), guardado
    # aqui só com os dígitos (sem máscara).
    documento: str = Field(unique=True, index=True)
    telefone: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    prazo_medio_entrega_dias: Optional[int] = Field(default=None)


class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: Optional[str] = Field(default=None)
    nomedoproduto: str
    # Decimal(10,3): produtos vendidos por peso/volume (unidade_medida KG/L)
    # podem ter quantidade fracionária (ex.: 0.350 kg). Produtos por unidade
    # (UN) continuam usando quantidade inteira normalmente, só que
    # representada como Decimal("5.000") em vez de `int`.
    quantidade: DecimalQuantidade = Field(max_digits=10, decimal_places=3)
    # UN (unidade), KG (quilo) ou L (litro) -- validado na camada Pydantic
    # (schemas.UnidadeMedida), guardado aqui como texto simples, mesmo
    # padrão já usado para `Funcionario.cargo`.
    unidade_medida: str = Field(default="UN")
    # Quantidade mínima desejada em estoque (mesmo tipo/precisão de
    # `quantidade`). Hoje só um campo informativo -- o endpoint de
    # reposição automática que consome esse valor é de uma fase futura
    # (fora do escopo desta mudança).
    estoque_minimo: DecimalQuantidade = Field(default=Decimal("0.000"), max_digits=10, decimal_places=3)
    preco: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    preco_custo: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    codigodebarras: str = Field(unique=True, index=True)
    categoria: str
    funcionario_id: Optional[int] = Field(default=None, foreign_key="funcionario.id", index=True)
    # Fornecedor principal do produto -- opcional (nem todo produto tem um
    # fornecedor cadastrado ainda).
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id", index=True)


class Lote(SQLModel, table=True):
    """Detalhamento de como o saldo de um produto (Estoque.quantidade) está
    dividido por validade (Fase 3 -- "lotes e validade").

    DECISÃO DE ARQUITETURA: `Estoque.quantidade` continua sendo a fonte da
    verdade do saldo total, travada e decrementada exatamente como já era
    feito antes desta fase (with_for_update(), testado sob concorrência nas
    Fases 1/2). `Lote` nunca é uma segunda fonte da verdade -- é só um
    detalhamento de COMO esse saldo está repartido por data de validade. A
    invariante mantida em todo ponto de escrita (ver repository/lotes.py) é
    soma(Lote.quantidade de um produto) == Estoque.quantidade desse produto.
    Optamos por essa abordagem (em vez de mover a trava de concorrência para
    a própria tabela Lote) porque reaproveita 100% da trava já validada sob
    carga real, sem reconstruir do zero uma peça crítica que já funciona.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    # FK para o PRODUTO (estoque.id), não para codigodebarras: diferente de
    # ItemVenda/ItemCompra (que guardam codigodebarras como string solta --
    # um snapshot histórico de uma venda/compra que não deve mudar mesmo que
    # o produto seja editado depois), um Lote é um detalhamento VIVO do
    # saldo atual de um produto específico, e precisa continuar apontando
    # para a MESMA linha mesmo que o codigodebarras do produto seja editado
    # (PUT /estoque/atualizar permite isso). Por isso a FK aqui é para o id
    # -- primeira FK do projeto apontando para `estoque`, seguindo o mesmo
    # padrão já usado para as demais (funcionario_id -> funcionario.id,
    # fornecedor_id -> fornecedor.id).
    estoque_id: int = Field(foreign_key="estoque.id", index=True)
    # Identificador do lote dado pelo fornecedor -- texto livre, não há
    # formato padrão entre fornecedores.
    codigo_lote: str
    # Decimal(10,3): mesma precisão de Estoque.quantidade.
    quantidade: DecimalQuantidade = Field(max_digits=10, decimal_places=3)
    # NULL = validade desconhecida ("lote legado" -- ver repository/lotes.py,
    # criado sob demanda para produtos que existiam antes desta fase, ou
    # para ajustes manuais de quantidade que não informam lote/validade).
    # Produto realmente perecível sempre deve vir com validade preenchida;
    # o campo é opcional só para não forçar data em produto que não vence
    # (ex.: utensílio, produto de limpeza).
    validade: Optional[date] = Field(default=None, index=True)
    data_entrada: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MovimentacaoEstoque(SQLModel, table=True):
    """Histórico de movimentações de estoque (Fase 4 -- "histórico de
    movimentações"). Toda alteração de `Estoque.quantidade` e/ou
    `Lote.quantidade` feita pelos pontos de escrita que o produto já tinha
    antes desta fase (criar_estoque, confirmar_pendente, criar_venda) e pelo
    novo ponto de escrita desta fase (ajustar_inventario) grava uma linha
    aqui, na MESMA transação da alteração -- nunca commita sozinha (mesmo
    padrão de `Lote`/repository/lotes.py: quem chama é responsável por
    commitar tudo junto).

    __tablename__ = "movimentacaoestoque" (nome default do SQLModel a partir
    do nome da classe) -- ver migration.sql, que usa o nome
    `movimentacao_estoque` só na migração manual (snake_case por legibilidade
    do SQL), reconciliado via `__tablename__` explícito logo abaixo.

    CONVENÇÃO DE SINAL: `quantidade` é sempre SIGNED -- positiva para
    entrada (ENTRADA_COMPRA), negativa para saída (VENDA, e
    AJUSTE_INVENTARIO quando reduz o saldo; positiva quando o ajuste
    aumenta). A soma de `quantidade` de todas as movimentações de um
    produto, desde sempre, deve bater com `Estoque.quantidade` atual desse
    produto -- a mesma invariante central já estabelecida para `Lote` na
    Fase 3, agora também para o histórico de movimentações (ver
    tests/test_movimentacoes.py).

    `lote_id` é OPCIONAL: nem toda movimentação está ligada a um lote
    específico -- só quando a origem da movimentação não tem nenhum lote
    por trás (ex.: `VENDA`/`AJUSTE_INVENTARIO` reconstruídos manualmente
    fora do fluxo normal da aplicação, ou um teste de unidade que registra
    direto). Entrada manual (POST /estoque/inserir, cadastro novo ou
    incremento) e ajuste de inventário mexem no saldo TOTAL do produto sem
    informar lote/validade -- mas SEMPRE acabam refletidos em algum lote: o
    "lote sem validade" (legado), reconciliado por
    `reconciliar_lote_sem_validade` (ver docstring de `Lote`). Entrada
    rastreada via confirmação de compra pendente (`criar_lote`) ou consumo
    FEFO numa venda (`consumir_fefo`) usam, em vez disso, um lote datado de
    verdade.

    CORRIGIDO (CRÍTICO 2 da revisão da Fase 4): até então, toda movimentação
    que caía no "lote sem validade" era gravada com `lote_id=None` -- o lote
    "sem validade" nunca tinha uma movimentação própria ligada a ele,
    contradizendo a promessa acima ("toda alteração de Lote.quantidade grava
    uma linha aqui"). `reconciliar_lote_sem_validade` agora retorna o delta
    que efetivamente aplicou a esse lote, e os pontos que a chamam
    (`criar_estoque`, `ajustar_inventario`, `confirmar_pendente`) registram a
    movimentação com `lote_id` apontando pra ele (não mais `None`) sempre
    que esse delta for diferente de zero. Resultado: a invariante
    soma(MovimentacaoEstoque.quantidade de um lote_id) == Lote.quantidade
    desse lote agora vale TAMBÉM para o "lote sem validade" (ver
    tests/test_movimentacoes.py), igual já valia só para lotes datados --
    com uma única ressalva, documentada na nuance do docstring de
    `reconciliar_lote_sem_validade`: um produto genuinamente legado (saldo
    pré-existente nunca antes rastreado em nenhum lote/movimentação) tem seu
    gap histórico absorvido de uma vez na primeira reconciliação, em vez de
    reconstruído retroativamente linha a linha (consistente com a regra geral
    de não reconstruir histórico retroativo, ver migration.sql).

    Só `ENTRADA_COMPRA`, `VENDA` e `AJUSTE_INVENTARIO` têm código que
    realmente os gera nesta fase (ver repository/estoque.py,
    repository/vendas.py). `CANCELAMENTO_VENDA`, `PERDA`, `QUEBRA` e
    `VENCIMENTO` já existem no enum (schemas.TipoMovimentacao) só para
    quando as fases futuras que os disparam (cancelamento de venda --
    Fase 8; baixa por perda/quebra/vencimento -- fase futura) chegarem --
    nenhum fluxo que os gere está implementado ainda.

    Produtos/lotes cadastrados ANTES desta fase não têm histórico de
    movimentação retroativo -- não é reconstruído, o histórico só começa a
    partir de agora (mesma regra já aplicada ao "lote legado" na Fase 3,
    ver migration.sql).
    """
    __tablename__ = "movimentacao_estoque"

    id: Optional[int] = Field(default=None, primary_key=True)
    estoque_id: int = Field(foreign_key="estoque.id", index=True)
    lote_id: Optional[int] = Field(default=None, foreign_key="lote.id", index=True)
    # Valor fixo validado na camada Pydantic (schemas.TipoMovimentacao),
    # guardado aqui como texto simples -- mesmo padrão já usado para
    # `Funcionario.cargo`/`Estoque.unidade_medida`.
    tipo: str = Field(index=True)
    # Decimal(10,3): mesma precisão de Estoque.quantidade/Lote.quantidade.
    # SIGNED -- ver convenção de sinal na docstring da classe.
    quantidade: DecimalQuantidade = Field(max_digits=10, decimal_places=3)
    # IMPORTANTE 3 (revisão da Fase 4): SNAPSHOT da unidade de medida do
    # produto no momento desta movimentação (texto livre, mesmo valor de
    # Estoque.unidade_medida -- "UN"/"KG"/"L" -- mas copiado, não uma FK/
    # referência viva). Sem isso, o frontend formatava TODAS as linhas do
    # histórico com a unidade ATUAL do produto -- se a unidade de medida
    # mudasse depois (ex.: de KG pra UN), reabrir o histórico distorcia
    # movimentações antigas (arredondando valores que antes eram
    # fracionários). Preenchido em registrar_movimentacao a partir do
    # produto (Estoque.unidade_medida) naquele instante; o frontend passa a
    # formatar cada linha usando este valor salvo, não o atual do produto.
    unidade_medida: str = Field(default="UN")
    # Só obrigatório na camada Pydantic para o endpoint de ajuste de
    # inventário (schemas.AjusteInventarioInput) -- as demais movimentações
    # (ENTRADA_COMPRA, VENDA) não exigem motivo, já que o próprio tipo +
    # referência (compra/venda) já explica a origem.
    motivo: Optional[str] = Field(default=None)
    # Quem realizou/disparou a ação (funcionário autenticado na rota que
    # originou a movimentação). OPCIONAL (ondelete="SET NULL") -- CORREÇÃO
    # do painel de revisão da Fase 4 (CRÍTICO 1): a FK original era NOT NULL
    # sem ON DELETE nenhum, então excluir um funcionário que já tivesse
    # QUALQUER movimentação registrada (o caso normal de uso real) quebrava
    # com IntegrityError/500 -- reproduzido ao vivo contra MySQL real. DECISÃO:
    # ON DELETE SET NULL (não apagar as movimentações do funcionário
    # excluído) -- um histórico de auditoria de estoque não deveria sumir só
    # porque o funcionário saiu da empresa; a movimentação em si (o quê, de
    # qual produto/lote, quando) continua intacta, só perde a referência de
    # "quem fez" quando essa pessoa não existe mais. Mesmo padrão já usado
    # neste projeto para `Estoque.funcionario_id` (também opcional).
    funcionario_id: Optional[int] = Field(default=None, foreign_key="funcionario.id", ondelete="SET NULL", index=True)
    data: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)


class Venda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    data: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    valor_total: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)


class ItemVenda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    venda_id: int = Field(foreign_key="venda.id", index=True)
    codigodebarras: str = Field(index=True)
    # Decimal(10,3): mesma razão de Estoque.quantidade -- venda por peso/
    # volume precisa de fração de unidade.
    quantidade: DecimalQuantidade = Field(max_digits=10, decimal_places=3)
    preco_unitario: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    preco_total: DecimalMoeda = Field(max_digits=10, decimal_places=2)


class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    tipo_movimentacao: str = Field(index=True)
    data_hora: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Despesa(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    data: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    descricao: str
    valor: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    categoria: str
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)


class Comunicado(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: str
    conteudo: str
    autor_id: int = Field(foreign_key="funcionario.id", index=True)
    data_criacao: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    para_todos: bool = Field(default=True)


class ComunicadoDestinatario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    comunicado_id: int = Field(foreign_key="comunicado.id", index=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    lido: bool = Field(default=False)
    data_leitura: Optional[datetime] = Field(default=None)


class Compra(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    data: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    solicitante_id: int = Field(foreign_key="funcionario.id", index=True)
    aprovador_id: Optional[int] = Field(default=None, foreign_key="funcionario.id")
    valor_total: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    status: str = Field(default="pendente", index=True)
    data_autorizacao: Optional[datetime] = Field(default=None)
    # Fornecedor do pedido -- opcional, para não quebrar compras já
    # existentes sem fornecedor definido.
    fornecedor_id: Optional[int] = Field(default=None, foreign_key="fornecedor.id", index=True)


class ItemCompra(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    compra_id: int = Field(foreign_key="compra.id", index=True)
    codigodebarras: str = Field(index=True)
    nomedoproduto: str
    categoria: Optional[str] = Field(default=None)
    preco_venda: Optional[DecimalMoeda] = Field(default=None, max_digits=10, decimal_places=2)
    # Decimal(10,3): mesma razão de Estoque.quantidade -- compra de produto
    # vendido por peso/volume pode vir em fração de unidade.
    quantidade: DecimalQuantidade = Field(max_digits=10, decimal_places=3)
    preco_custo_unitario: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    preco_custo_total: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    lancado_em: Optional[datetime] = Field(default=None)


class Ponto(SQLModel, table=True):
    """Registro diário de ponto eletrônico (um funcionário, um dia).

    `entrada`/`saida_almoco`/`retorno_almoco`/`saida` são batidos em
    sequência, nessa ordem (ver repository/pontos.py::bater_ponto) --
    `horas_trabalhadas`/`horas_extras`/`horas_devidas` só são calculadas e
    persistidas quando `saida` já foi batida; um dia ainda em aberto fica
    com esses três zerados.

    UniqueConstraint(funcionario_id, data) -- achado do painel de revisão:
    bater_ponto() lê "existe Ponto hoje?" sem lock antes de decidir se cria
    uma linha nova; duas requisições quase simultâneas (duplo clique no
    botão de bater ponto) passavam as duas pelo "não existe" e criavam DUAS
    linhas para o mesmo funcionário/dia, inflando horas somadas em
    relatório/folha. with_for_update() não fecha essa brecha sozinho (a
    corrida é sobre CRIAR uma linha nova, não sobre ler uma já existente) --
    a constraint é a proteção real; repository/pontos.py::bater_ponto trata
    o IntegrityError resultante como 409.
    """
    __table_args__ = (UniqueConstraint("funcionario_id", "data"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    data: date = Field(index=True)
    entrada: Optional[datetime] = Field(default=None)
    saida_almoco: Optional[datetime] = Field(default=None)
    retorno_almoco: Optional[datetime] = Field(default=None)
    saida: Optional[datetime] = Field(default=None)
    # DECIMAL(5,2) -- mesma estrutura de DecimalMoeda (2 casas), reaproveitada
    # aqui para horas em vez de dinheiro (ver nota em utils/quantidade.py
    # sobre DecimalQuantidade/DecimalMoeda serem estruturalmente idênticos).
    horas_trabalhadas: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=5, decimal_places=2)
    horas_extras: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=5, decimal_places=2)
    horas_devidas: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=5, decimal_places=2)


class Salario(SQLModel, table=True):
    """Salário atual do funcionário. `valor_hora` é sempre derivado de
    `valor_mensal` (ver repository/funcionarios.py::definir_salario) --
    nunca editado direto, só recalculado quando `valor_mensal` muda.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", unique=True, index=True)
    valor_mensal: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    valor_hora: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)


class SalarioHistorico(SQLModel, table=True):
    __tablename__ = "salariohistorico"
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    valor_antigo: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    valor_novo: DecimalMoeda = Field(max_digits=10, decimal_places=2)
    data_alteracao: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Holerite(SQLModel, table=True):
    """Folha de pagamento consolidada de um funcionário num mês/ano (ver
    repository/folha.py::fechar_folha). `ajuda_custo`, `adiantamento`,
    `contribuicao_assistencial` e `vale_refeicao` existem no schema mas,
    nesta primeira versão, não têm regra de cálculo definida -- sempre
    gravados como 0.00 (decisão explícita, não um bug: ver plano da mudança
    que introduziu este arquivo). `valor_liquido` já soma os quatro na
    fórmula, então ficam prontos para quando ganharem uma regra real.

    UniqueConstraint(funcionario_id, mes, ano) -- achado do painel de
    revisão: fechar_folha() verifica "já existe holerite deste mês?" sem
    lock antes de inserir; duas chamadas concorrentes (RH clicando duas
    vezes, ou dois gerentes fechando ao mesmo tempo) passavam as duas pelo
    "não existe" e geravam holerite duplicado pro mesmo funcionário/mês.
    Mesma proteção que Ponto (ver docstring de Ponto) -- a constraint é
    quem fecha a brecha, não um lock de leitura.
    """
    __table_args__ = (UniqueConstraint("funcionario_id", "mes", "ano"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    mes: int
    ano: int
    data_competencia: date
    valor_bruto: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    valor_liquido: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    salario_base: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    inss: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    irpf: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    fgts: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    vale_transporte: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    vale_refeicao: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    contribuicao_assistencial: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    ajuda_custo: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    adiantamento: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    horas_extras_valor: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    horas_trabalhadas: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    dias_trabalhados: int = Field(default=30)
    horas_extras: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    horas_devidas: DecimalMoeda = Field(default=Decimal("0.00"), max_digits=10, decimal_places=2)
    assinado: bool = Field(default=False)
    data_assinatura: Optional[datetime] = Field(default=None)
    data_emissao: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


engine = create_engine(DATABASE_URL, connect_args=_connect_args)


def get_session():
    with Session(engine) as session:
        yield session


def criar_admin_padrao():
    from utils.security import hash_senha
    with Session(engine) as session:
        if session.exec(select(Funcionario).where(Funcionario.is_admin == True)).first():
            return

        setor_admin = session.exec(select(Setor).where(Setor.tipo == "admin")).first()
        if not setor_admin:
            setor_admin = Setor(nome="Administrador", tipo="admin")
            session.add(setor_admin)
            session.flush()

        chars = string.ascii_letters + string.digits
        senha_inicial = "".join(secrets.choice(chars) for _ in range(14))
        password_hash = hash_senha(senha_inicial)
        admin = Funcionario(
            nome="admin", sobrenome="master",
            data_nascimento=date(2000, 1, 1),
            genero="outro", possui_filhos=False,
            setor_id=setor_admin.id, cargo="diretoria", is_admin=True,
            password_hash=password_hash,
            senha_atualizada_em=datetime.now(timezone.utc),
            senha_temporaria=True,
        )
        session.add(admin)
        session.flush()
        session.add(HistoricoSenha(funcionario_id=admin.id, password_hash=password_hash))
        session.commit()

        print("=" * 60)  # noqa: T201
        print("Admin padrão criado — usuário: admin.master")
        print(f"Senha inicial (temporária, só exibida agora): {senha_inicial}")
        print("Troque essa senha no primeiro login.")
        print("=" * 60)


def criar_banco():  # pragma: no cover
    SQLModel.metadata.create_all(engine)
    criar_admin_padrao()
