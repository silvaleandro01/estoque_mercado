import pytest
from datetime import date
from pydantic import ValidationError

from schemas.schemas import (
    FuncionarioCreate, EstoqueCreate, EstoqueUpdate,
    ItemVendaSchema, VendaInput, TrocarSenhaRequest, RecuperarSenhaRequest,
)

DADOS_BASE = dict(
    nome="Joao", sobrenome="Silva",
    data_nascimento=date(1990, 1, 1),
    genero="M", possui_filhos=False, setor_id=1,
    senha="Test@123",
    cpf="52998224725",
    email="joao@test.com",
    cep="01310100",
    estado="SP", cidade="SP", bairro="Centro",
    rua="Paulista", numero="100",
)


# ── CPF ────────────────────────────────────────────────────────────────────────

def test_cpf_valido():
    m = FuncionarioCreate(**DADOS_BASE)
    assert m.cpf == "52998224725"


def test_cpf_valido_com_formatacao():
    m = FuncionarioCreate(**{**DADOS_BASE, "cpf": "529.982.247-25"})
    assert m.cpf == "52998224725"


def test_cpf_segundo_valido():
    m = FuncionarioCreate(**{**DADOS_BASE, "cpf": "11144477735"})
    assert m.cpf == "11144477735"


def test_cpf_digito_invalido():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cpf": "52998224700"})
    assert "CPF inválido" in str(exc.value)


def test_cpf_todos_iguais():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cpf": "11111111111"})
    assert "CPF inválido" in str(exc.value)


def test_cpf_curto():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cpf": "123456789"})
    assert "CPF inválido" in str(exc.value)


def test_cpf_longo():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cpf": "529982247251"})
    assert "CPF inválido" in str(exc.value)


def test_cpf_letras():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cpf": "abc.def.ghi-jk"})
    assert "CPF inválido" in str(exc.value)


def test_cpf_vazio():
    with pytest.raises(ValidationError):
        FuncionarioCreate(**{**DADOS_BASE, "cpf": ""})


# ── CEP ────────────────────────────────────────────────────────────────────────

def test_cep_valido_sem_hifen():
    m = FuncionarioCreate(**DADOS_BASE)
    assert m.cep == "01310100"


def test_cep_valido_com_hifen():
    m = FuncionarioCreate(**{**DADOS_BASE, "cep": "01310-100"})
    assert m.cep == "01310100"


def test_cep_curto():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cep": "0131010"})
    assert "8 dígitos" in str(exc.value)


def test_cep_longo():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cep": "013101001"})
    assert "8 dígitos" in str(exc.value)


def test_cep_letras():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "cep": "ABCDEFGH"})
    assert "8 dígitos" in str(exc.value)


# ── Email ──────────────────────────────────────────────────────────────────────

def test_email_valido():
    m = FuncionarioCreate(**DADOS_BASE)
    assert m.email == "joao@test.com"


def test_email_normalizado_lowercase():
    m = FuncionarioCreate(**{**DADOS_BASE, "email": "JOAO@TEST.COM"})
    assert m.email == "joao@test.com"


def test_email_sem_arroba():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "email": "joaotest.com"})
    assert "Email inválido" in str(exc.value)


def test_email_sem_dominio():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "email": "joao@"})
    assert "Email inválido" in str(exc.value)


def test_email_sem_ponto_no_dominio():
    with pytest.raises(ValidationError) as exc:
        FuncionarioCreate(**{**DADOS_BASE, "email": "joao@testcom"})
    assert "Email inválido" in str(exc.value)


def test_email_vazio():
    with pytest.raises(ValidationError):
        FuncionarioCreate(**{**DADOS_BASE, "email": ""})


# ── Estoque ────────────────────────────────────────────────────────────────────

def test_estoque_create_valido():
    m = EstoqueCreate(nomedoproduto="Pao", quantidade=10, preco=2.5, codigodebarras="123", categoria="Padaria")
    assert m.quantidade == 10
    assert m.preco == 2.5


def test_estoque_preco_zero_invalido():
    with pytest.raises(ValidationError):
        EstoqueCreate(nomedoproduto="X", quantidade=1, preco=0.0, codigodebarras="1", categoria="A")


def test_estoque_preco_negativo_invalido():
    with pytest.raises(ValidationError):
        EstoqueCreate(nomedoproduto="X", quantidade=1, preco=-1.0, codigodebarras="1", categoria="A")


def test_estoque_quantidade_negativa_invalida():
    with pytest.raises(ValidationError):
        EstoqueCreate(nomedoproduto="X", quantidade=-1, preco=1.0, codigodebarras="1", categoria="A")


def test_estoque_quantidade_zero_valida():
    m = EstoqueCreate(nomedoproduto="X", quantidade=0, preco=1.0, codigodebarras="1", categoria="A")
    assert m.quantidade == 0


def test_estoque_preco_custo_default_zero():
    m = EstoqueCreate(nomedoproduto="X", quantidade=1, preco=5.0, codigodebarras="1", categoria="A")
    assert m.preco_custo == 0.0


def test_estoque_preco_custo_negativo_invalido():
    with pytest.raises(ValidationError):
        EstoqueCreate(nomedoproduto="X", quantidade=1, preco=5.0, preco_custo=-1.0, codigodebarras="1", categoria="A")


# ── Venda ─────────────────────────────────────────────────────────────────────

def test_venda_input_lista_vazia_invalida():
    with pytest.raises(ValidationError):
        VendaInput(itens=[])


def test_venda_input_valida():
    m = VendaInput(itens=[{"codigodebarras": "123", "quantidade": 2}])
    assert len(m.itens) == 1


def test_item_venda_quantidade_zero_invalida():
    with pytest.raises(ValidationError):
        ItemVendaSchema(codigodebarras="123", quantidade=0)


def test_item_venda_quantidade_negativa_invalida():
    with pytest.raises(ValidationError):
        ItemVendaSchema(codigodebarras="123", quantidade=-5)


# ── Trocar / Recuperar senha ───────────────────────────────────────────────────

def test_trocar_senha_schema():
    m = TrocarSenhaRequest(senha_atual="abc", nova_senha="xyz")
    assert m.senha_atual == "abc"


def test_recuperar_senha_normaliza_cpf():
    m = RecuperarSenhaRequest(cpf="529.982.247-25")
    assert m.cpf == "52998224725"
