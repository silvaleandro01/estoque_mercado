import os
from typing import Optional
from datetime import datetime, timezone, date, timedelta
from sqlmodel import Field, SQLModel, create_engine, Session, select
from sqlalchemy import text
from jose import jwt
from dotenv import load_dotenv

load_dotenv()
MYSQL_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:SuaNovaSenhaAqui@localhost:3306/estoque_mercado")
SECRET_KEY = os.getenv("SECRET_KEY", "chave_padrao_temporaria")
ALGORITHM = "HS256"
def criar_token(funcionario_id: int, is_admin: bool, horas: int = 12):
    expiracao = datetime.now(timezone.utc) + (timedelta(days=36500) if is_admin else timedelta(hours=horas))
    payload = {"sub": str(funcionario_id), "exp": expiracao, "is_admin": is_admin}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM), expiracao
class SetorCreate(SQLModel):
    nome: str
    tipo: str


class FuncionarioCreate(SQLModel):
    nome: str
    sobrenome: str
    data_nascimento: str
    genero: str
    possui_filhos: bool
    setor_id: int
    cargo: str = "operacional"
    is_admin: bool = False
    valor_mensal: float = 0.0
    bate_ponto: bool = True
    cargo_confianca: bool = False
class FuncionarioHierarquiaUpdate(SQLModel):
    bate_ponto: bool
    cargo_confianca: bool
    cargo: str
class Setor(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    tipo: str = Field(index=True, unique=True, max_length=50)
class Funcionario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nome: str
    sobrenome: str
    data_nascimento: date
    genero: str
    cargo: str = Field(default="operacional", max_length=50)
    possui_filhos: bool
    setor_id: int = Field(foreign_key="setor.id", index=True)
    is_admin: bool = Field(default=False)
    bate_ponto: bool = Field(default=True)
    cargo_confianca: bool = Field(default=False)
    password_hash: Optional[str] = Field(default=None)
    last_password_change: Optional[datetime] = Field(default=None)
    token: Optional[str] = Field(default=None, index=True, max_length=255)
    token_expiracao: Optional[datetime] = Field(default=None)
class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    titulo: Optional[str] = None
    nomedoproduto: str
    quantidade: int
    preco: float
    codigodebarras: str = Field(unique=True, index=True, max_length=100)
    categoria: str

    funcionario_id: Optional[int] = Field(
        default=None,
        foreign_key="funcionario.id",
        index=True
    )


class Venda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    data: datetime = Field(
        default_factory=lambda: datetime.now(),
        index=True
    )

    valor_total: float = 0.0

    funcionario_id: int = Field(
        foreign_key="funcionario.id",
        index=True
    )


class ItemVenda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    venda_id: int = Field(foreign_key="venda.id", index=True)

    codigodebarras: str = Field(index=True)
    quantidade: int

    preco_unitario: float
    preco_total: float


class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    funcionario_id: int = Field(
        foreign_key="funcionario.id",
        index=True,
        nullable=False
    )

    tipo_movimentacao: str = Field(
        index=True,
        nullable=False,
        max_length=255
    )

    data_hora: datetime = Field(
        default_factory=lambda: datetime.now(),
        nullable=False
    )

class Ponto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    data: date = Field(default_factory=lambda: date.today(), index=True)
    
    entrada: Optional[datetime] = None
    saida_almoco: Optional[datetime] = None
    retorno_almoco: Optional[datetime] = None
    saida: Optional[datetime] = None
    
    horas_trabalhadas: float = Field(default=0.0)
    horas_extras: float = Field(default=0.0)
    horas_devidas: float = Field(default=0.0)
class Salario(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True, unique=True)
    valor_mensal: float = Field(default=0.0)
    valor_hora: float = Field(default=0.0)

class SalarioHistorico(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    valor_antigo: float
    valor_novo: float
    data_alteracao: datetime = Field(default_factory=lambda: datetime.now())

class Holerite(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    mes: int
    ano: int
    data_competencia: date = Field(index=True)
    valor_bruto: float
    valor_liquido: float
    salario_base: float
    inss: float
    irpf: float
    fgts: float
    vale_transporte: float
    vale_refeicao: float
    contribuicao_assistencial: float
    ajuda_custo: float
    adiantamento: float
    horas_extras_valor: float
    horas_trabalhadas: float
    dias_trabalhados: int = 30
    horas_extras: float
    horas_devidas: float
    assinado: bool = Field(default=False)
    data_assinatura: Optional[datetime] = None
    data_emissao: datetime = Field(default_factory=lambda: datetime.now())

class SenhaHistorico(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    password_hash: str
    data_criacao: datetime = Field(
        default_factory=lambda: datetime.now()
    )


engine = create_engine(
    MYSQL_URL,
    echo=True,
    pool_recycle=3600,
    pool_pre_ping=True
)
def get_session():
    with Session(engine) as session:
        yield session
def criar_admin_padrao():
    with Session(engine) as session:
        admin_existente = session.exec(
            select(Funcionario).where(Funcionario.is_admin == True)
        ).first()
        if admin_existente:
            return
        setor_admin = session.exec(
            select(Setor).where(Setor.tipo == "admin")
        ).first()
        if not setor_admin:
            setor_admin = Setor(nome="Administrador", tipo="admin")
            session.add(setor_admin)
            session.commit()
            session.refresh(setor_admin)
        admin = Funcionario(
            nome="admin",
            sobrenome="master",
            data_nascimento=date(2000, 1, 1),
            genero="outro",
            possui_filhos=False,
            cargo="diretor",
            bate_ponto=False,
            cargo_confianca=True,
            setor_id=setor_admin.id,
            is_admin=True
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        salario_admin = Salario(funcionario_id=admin.id, valor_mensal=0.0, valor_hora=0.0)
        session.add(salario_admin)
        token, exp = criar_token(admin.id, True)
        admin.token = token
        admin.token_expiracao = exp
        session.add(admin)
        session.commit()
def criar_banco():
    url_servidor = "mysql+pymysql://root:SuaNovaSenhaAqui@localhost:3306/"
    engine_servidor = create_engine(url_servidor)
    with engine_servidor.connect() as conn:
        conn.execute(text("CREATE DATABASE IF NOT EXISTS estoque_mercado"))
        conn.commit()
    engine_servidor.dispose()
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        colunas = conn.execute(text("SHOW COLUMNS FROM funcionario LIKE 'cargo'")).fetchone()
        if not colunas:
            conn.execute(text("ALTER TABLE funcionario ADD COLUMN cargo VARCHAR(50) NOT NULL DEFAULT 'operacional'"))
            conn.commit()
        coluna_ponto = conn.execute(text("SHOW COLUMNS FROM funcionario LIKE 'bate_ponto'")).fetchone()
        if not coluna_ponto:
            conn.execute(text("ALTER TABLE funcionario ADD COLUMN bate_ponto BOOLEAN NOT NULL DEFAULT TRUE"))
            conn.commit()
        coluna_confianca = conn.execute(text("SHOW COLUMNS FROM funcionario LIKE 'cargo_confianca'")).fetchone()
        if not coluna_confianca:
            conn.execute(text("ALTER TABLE funcionario ADD COLUMN cargo_confianca BOOLEAN NOT NULL DEFAULT FALSE"))
            conn.commit()
    criar_admin_padrao()