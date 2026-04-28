import os
from typing import Optional
from datetime import datetime, timezone, date
from sqlmodel import Field, SQLModel, create_engine, Session, select
from dotenv import load_dotenv

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


class HistoricoSenha(SQLModel, table=True):
    __tablename__ = "historico_senha"
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    password_hash: str
    criado_em: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    titulo: Optional[str] = Field(default=None)
    nomedoproduto: str
    quantidade: int
    preco: float
    preco_custo: float = Field(default=0.0)
    codigodebarras: str = Field(unique=True, index=True)
    categoria: str
    funcionario_id: Optional[int] = Field(default=None, foreign_key="funcionario.id", index=True)


class Venda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    data: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    valor_total: float = 0.0
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)


class ItemVenda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    venda_id: int = Field(foreign_key="venda.id", index=True)
    codigodebarras: str = Field(index=True)
    quantidade: int
    preco_unitario: float
    preco_total: float


class Log(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    funcionario_id: int = Field(foreign_key="funcionario.id", index=True)
    tipo_movimentacao: str = Field(index=True)
    data_hora: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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

        password_hash = hash_senha("Admin@123")
        admin = Funcionario(
            nome="admin", sobrenome="master",
            data_nascimento=date(2000, 1, 1),
            genero="outro", possui_filhos=False,
            setor_id=setor_admin.id, is_admin=True,
            password_hash=password_hash,
            senha_atualizada_em=datetime.now(timezone.utc),
        )
        session.add(admin)
        session.flush()
        session.add(HistoricoSenha(funcionario_id=admin.id, password_hash=password_hash))
        session.commit()


def criar_banco():  # pragma: no cover
    SQLModel.metadata.create_all(engine)
    criar_admin_padrao()
