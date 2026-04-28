from typing import Optional
from datetime import datetime, timezone, date, timedelta
from sqlmodel import Field, SQLModel, create_engine, Session, select
from jose import jwt
import os


SECRET_KEY = os.getenv("SECRET_KEY", "chave_padrao_temporaria")
ALGORITHM = "HS256"


def criar_token(funcionario_id: int, is_admin: bool, horas: int = 12):
    expiracao = datetime.now(timezone.utc) + timedelta(hours=horas)

    payload = {
        "sub": str(funcionario_id),
        "exp": expiracao,
        "is_admin": is_admin
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expiracao


class SetorCreate(SQLModel):
    nome: str
    tipo: str


class FuncionarioCreate(SQLModel):
    nome: str
    sobrenome: str
    data_nascimento: date
    genero: str
    possui_filhos: bool
    setor_id: int


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

    token: Optional[str] = Field(default=None, index=True)
    token_expiracao: Optional[datetime] = Field(default=None)


class Estoque(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    titulo: Optional[str] = None
    nomedoproduto: str
    quantidade: int
    preco: float
    codigodebarras: str = Field(unique=True, index=True)
    categoria: str

    funcionario_id: Optional[int] = Field(
        default=None,
        foreign_key="funcionario.id",
        index=True
    )


class Venda(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    data: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
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
        nullable=False
    )

    data_hora: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        nullable=False
    )


engine = create_engine(
    "sqlite:///./database.db",
    echo=True,
    connect_args={"check_same_thread": False}
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
            setor_id=setor_admin.id,
            is_admin=True
        )

        session.add(admin)
        session.commit()
        session.refresh(admin)

        token, exp = criar_token(admin.id, True)

        admin.token = token
        admin.token_expiracao = exp

        session.add(admin)
        session.commit()


def criar_banco():
    SQLModel.metadata.create_all(engine)
    criar_admin_padrao()