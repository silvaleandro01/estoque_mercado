import pytest
from decimal import Decimal
from fastapi import HTTPException
from sqlmodel import Session

from services.auth import (
    exigir_registrar_compra, exigir_gerenciar_compra,
    exigir_aprovar_compra, exigir_ver_compras,
)
from repository.compras import (
    registrar_compra, listar_compras, buscar_itens_compra,
    encaminhar_compra, cancelar_compra, autorizar_compra, recusar_compra,
    compras_do_dia,
)
from repository.estoque import mostrar_produtos
from schemas.schemas import CompraInput, ItemCompraInput
from utils.database import Compra
from conftest import make_setor, make_funcionario, make_produto, make_compra, set_token


def _item(codigo="BAR900", qtd=10, custo=5.0, nome="Produto Novo", venda=15.0, cat="Geral"):
    return ItemCompraInput(
        codigodebarras=codigo, quantidade=qtd, preco_custo=custo,
        nomedoproduto=nome, preco_venda=venda, categoria=cat,
    )


# ── permissões ───────────────────────────────────────────────────────────────

def test_exigir_registrar_compra_admin(engine, session):
    setor = make_setor(session, tipo="outro1")
    admin = make_funcionario(session, setor_id=setor.id, is_admin=True)
    assert exigir_registrar_compra(admin) is True


def test_exigir_registrar_compra_operacional_compras(engine, session):
    setor = make_setor(session, tipo="compras")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    assert exigir_registrar_compra(func) is True


def test_exigir_registrar_compra_gerente_compras(engine, session):
    setor = make_setor(session, tipo="compras")
    func = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    assert exigir_registrar_compra(func) is True


def test_exigir_registrar_compra_diretor_sem_setor_compras_nega(engine, session):
    setor = make_setor(session, tipo="vendas")
    func = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    with pytest.raises(HTTPException) as exc:
        exigir_registrar_compra(func)
    assert exc.value.status_code == 403


def test_exigir_registrar_compra_setor_errado_nega(engine, session):
    setor = make_setor(session, tipo="estoque")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    with pytest.raises(HTTPException) as exc:
        exigir_registrar_compra(func)
    assert exc.value.status_code == 403


def test_exigir_gerenciar_compra_apenas_gerente(engine, session):
    setor = make_setor(session, tipo="compras")
    operacional = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    with pytest.raises(HTTPException):
        exigir_gerenciar_compra(operacional)
    assert exigir_gerenciar_compra(gerente) is True


def test_exigir_aprovar_compra_apenas_diretoria_ou_admin(engine, session):
    setor = make_setor(session, tipo="rh_compra")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    with pytest.raises(HTTPException):
        exigir_aprovar_compra(gerente)
    assert exigir_aprovar_compra(diretor) is True


def test_exigir_ver_compras_diretor_qualquer_setor(engine, session):
    setor = make_setor(session, tipo="rh_compra2")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    assert exigir_ver_compras(diretor) is True


def test_exigir_ver_compras_funcionario_fora_do_setor_nega(engine, session):
    setor = make_setor(session, tipo="vendas2")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    with pytest.raises(HTTPException) as exc:
        exigir_ver_compras(func)
    assert exc.value.status_code == 403


# ── registrar_compra ─────────────────────────────────────────────────────────

def test_registrar_compra_cria_pendente(engine, session):
    setor = make_setor(session, tipo="compras3")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[_item(codigo="BAR901", qtd=10, custo=5.0)])
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"
    assert resultado["valor_total"] == 50.0


def test_registrar_compra_quantidade_decimal(engine, session):
    setor = make_setor(session, tipo="compras_peso1")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[_item(codigo="BARPESO001", qtd=Decimal("2.500"), custo=4.0)])
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"
    assert resultado["valor_total"] == Decimal("10.00")  # 4.00 * 2.5

    itens = buscar_itens_compra(resultado["id"])
    assert itens[0]["quantidade"] == Decimal("2.500")


def test_registrar_compra_un_existente_rejeita_quantidade_fracionaria(engine, session):
    """
    A validação "produto UN só aceita quantidade inteira" existia só no
    frontend -- confirmado (painel de revisão da Fase 2) que POST
    /compras/registrar aceitava fração direto contra a API quando o
    código de barras já correspondia a um produto UN cadastrado no estoque.
    """
    setor = make_setor(session, tipo="compras_un_frac1")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    make_produto(session, codigo="COMPRAUNFRAC001", unidade="UN")
    dados = CompraInput(itens=[_item(codigo="COMPRAUNFRAC001", qtd=Decimal("1.500"), custo=5.0)])
    with pytest.raises(HTTPException) as exc:
        registrar_compra(dados, func.id)
    assert exc.value.status_code == 400
    assert "unidade inteira" in exc.value.detail


def test_registrar_compra_kg_existente_continua_aceitando_quantidade_fracionaria(engine, session):
    setor = make_setor(session, tipo="compras_un_frac2")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    make_produto(session, codigo="COMPRAKGFRAC001", qtd=Decimal("10.000"), unidade="KG")
    dados = CompraInput(itens=[_item(codigo="COMPRAKGFRAC001", qtd=Decimal("1.500"), custo=4.0)])
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"


def test_registrar_compra_produto_inexistente_permite_quantidade_fracionaria(engine, session):
    """
    Quando o código de barras ainda não corresponde a nenhum produto no
    estoque (vai virar um pendente), a unidade de medida só é decidida na
    confirmação (estoque.py::confirmar_pendente) -- não há o que validar
    aqui, então fração passa normalmente nesta etapa (mesmo comportamento
    de antes desta correção para este caso específico).
    """
    setor = make_setor(session, tipo="compras_un_frac3")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[_item(codigo="COMPRANOVOFRAC001", qtd=Decimal("1.500"), custo=4.0)])
    resultado = registrar_compra(dados, func.id)
    assert resultado["status"] == "pendente"


def test_registrar_compra_soma_varios_itens(engine, session):
    setor = make_setor(session, tipo="compras4")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    dados = CompraInput(itens=[
        _item(codigo="BAR902", qtd=2, custo=10.0),
        _item(codigo="BAR903", qtd=3, custo=4.0),
    ])
    resultado = registrar_compra(dados, func.id)
    assert resultado["valor_total"] == 32.0


# ── listar_compras / buscar_itens_compra ────────────────────────────────────

def test_listar_compras_mostra_solicitante_e_aprovador(engine, session):
    setor = make_setor(session, tipo="compras5")
    solicitante = make_funcionario(session, "Ana", "Souza", setor_id=setor.id, cargo="gerente")
    diretor = make_funcionario(session, "Bruno", "Lima", setor_id=setor.id, cargo="diretoria")
    compra = make_compra(session, solicitante.id, status="autorizada", aprovador_id=diretor.id)

    lista = listar_compras()
    encontrada = next(c for c in lista if c["id"] == compra.id)
    assert encontrada["solicitante"] == "Ana Souza"
    assert encontrada["aprovador"] == "Bruno Lima"
    assert encontrada["status"] == "autorizada"


def test_listar_compras_sem_aprovador_retorna_none(engine, session):
    setor = make_setor(session, tipo="compras6")
    solicitante = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    compra = make_compra(session, solicitante.id, status="pendente")

    lista = listar_compras()
    encontrada = next(c for c in lista if c["id"] == compra.id)
    assert encontrada["aprovador"] is None


def test_buscar_itens_compra_retorna_itens(engine, session):
    setor = make_setor(session, tipo="compras7")
    solicitante = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    compra = make_compra(session, solicitante.id, itens=[
        {"codigodebarras": "ITEMX", "nomedoproduto": "Produto X", "categoria": "Geral",
         "preco_venda": 20.0, "quantidade": 4, "preco_custo": 8.0},
    ])
    itens = buscar_itens_compra(compra.id)
    assert len(itens) == 1
    assert itens[0]["nomedoproduto"] == "Produto X"
    assert itens[0]["preco_custo"] == 8.0
    assert itens[0]["total"] == 32.0


def test_buscar_itens_compra_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_itens_compra(99999)
    assert exc.value.status_code == 404


# ── transições de status ─────────────────────────────────────────────────────

def test_encaminhar_compra_pendente_para_aguardando_diretor(engine, session):
    setor = make_setor(session, tipo="compras8")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="pendente")
    resultado = encaminhar_compra(compra.id, gerente.id)
    assert "msg" in resultado

    lista = listar_compras()
    atualizada = next(c for c in lista if c["id"] == compra.id)
    assert atualizada["status"] == "aguardando_diretor"


def test_encaminhar_compra_status_invalido_falha(engine, session):
    setor = make_setor(session, tipo="compras9")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="autorizada")
    with pytest.raises(HTTPException) as exc:
        encaminhar_compra(compra.id, gerente.id)
    assert exc.value.status_code == 400


def test_cancelar_compra_a_partir_de_pendente(engine, session):
    setor = make_setor(session, tipo="compras10")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="pendente")
    cancelar_compra(compra.id, gerente.id)
    lista = listar_compras()
    assert next(c for c in lista if c["id"] == compra.id)["status"] == "cancelada"


def test_cancelar_compra_a_partir_de_aguardando_diretor(engine, session):
    setor = make_setor(session, tipo="compras11")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="aguardando_diretor")
    cancelar_compra(compra.id, gerente.id)
    lista = listar_compras()
    assert next(c for c in lista if c["id"] == compra.id)["status"] == "cancelada"


def test_cancelar_compra_ja_autorizada_falha(engine, session):
    setor = make_setor(session, tipo="compras12")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="autorizada")
    with pytest.raises(HTTPException) as exc:
        cancelar_compra(compra.id, gerente.id)
    assert exc.value.status_code == 400


def test_recusar_compra_define_aprovador(engine, session):
    setor = make_setor(session, tipo="compras13")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    compra = make_compra(session, gerente.id, status="aguardando_diretor")
    recusar_compra(compra.id, diretor.id)

    lista = listar_compras()
    atualizada = next(c for c in lista if c["id"] == compra.id)
    assert atualizada["status"] == "recusada"
    assert atualizada["aprovador"] == f"{diretor.nome} {diretor.sobrenome}"


def test_recusar_compra_status_invalido_falha(engine, session):
    setor = make_setor(session, tipo="compras14")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="pendente")
    with pytest.raises(HTTPException) as exc:
        recusar_compra(compra.id, gerente.id)
    assert exc.value.status_code == 400


# ── autorizar_compra (marca autorizada; quem abastece o estoque é o módulo ──
# ── de estoque pendente, não autorizar_compra) ──────────────────────────────

def test_autorizar_compra_nao_mexe_no_estoque(engine, session):
    setor = make_setor(session, tipo="compras15")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    compra = make_compra(session, gerente.id, status="aguardando_diretor", itens=[
        {"codigodebarras": "NOVO001", "nomedoproduto": "Produto Novo", "categoria": "Limpeza",
         "preco_venda": 12.5, "quantidade": 20, "preco_custo": 6.0},
    ])
    autorizar_compra(compra.id, diretor.id)

    produtos = mostrar_produtos()
    assert not any(p.codigodebarras == "NOVO001" for p in produtos)

    lista = listar_compras()
    atualizada = next(c for c in lista if c["id"] == compra.id)
    assert atualizada["status"] == "autorizada"
    assert atualizada["aprovador"] == f"{diretor.nome} {diretor.sobrenome}"


def test_autorizar_compra_marca_data_autorizacao(engine, session):
    setor = make_setor(session, tipo="compras16")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    compra = make_compra(session, gerente.id, status="aguardando_diretor")
    autorizar_compra(compra.id, diretor.id)

    with Session(engine) as s:
        atualizada = s.get(Compra, compra.id)
        assert atualizada.data_autorizacao is not None


def test_autorizar_compra_status_invalido_falha(engine, session):
    setor = make_setor(session, tipo="compras17")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="pendente")
    with pytest.raises(HTTPException) as exc:
        autorizar_compra(compra.id, gerente.id)
    assert exc.value.status_code == 400


# ── compras_do_dia ───────────────────────────────────────────────────────────

def test_compras_do_dia_soma_apenas_autorizadas(engine, session):
    setor = make_setor(session, tipo="compras18")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    make_compra(session, func.id, status="autorizada", itens=[
        {"codigodebarras": "DIA001", "nomedoproduto": "P1", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 2, "preco_custo": 3.0},
    ])
    make_compra(session, func.id, status="pendente", itens=[
        {"codigodebarras": "DIA002", "nomedoproduto": "P2", "categoria": "Geral",
         "preco_venda": 10.0, "quantidade": 100, "preco_custo": 50.0},
    ])
    resultado = compras_do_dia()
    assert resultado["total"] == 6.0


# ── rotas HTTP (fluxo completo) ──────────────────────────────────────────────

def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_fluxo_completo_via_rotas(client, session, engine):
    setor = make_setor(session, tipo="compras")
    operacional = make_funcionario(session, "Op", "Compras", setor.id, cargo="operacional")
    gerente = make_funcionario(session, "Ger", "Compras", setor.id, cargo="gerente")
    diretor = make_funcionario(session, "Dir", "Geral", setor.id, cargo="diretoria")
    token_op = set_token(session, operacional)
    token_ger = set_token(session, gerente)
    token_dir = set_token(session, diretor)

    payload = {"itens": [{
        "codigodebarras": "ROTA001", "quantidade": 5, "preco_custo": 2.0,
        "nomedoproduto": "Produto Rota", "preco_venda": 7.0, "categoria": "Geral",
    }]}
    r = client.post("/compras/registrar", json=payload, headers=_headers(token_op))
    assert r.status_code == 200
    compra_id = r.json()["id"]

    r = client.post(f"/compras/encaminhar/{compra_id}", headers=_headers(token_ger))
    assert r.status_code == 200

    r = client.post(f"/compras/autorizar/{compra_id}", headers=_headers(token_dir))
    assert r.status_code == 200

    r = client.get("/estoque/mostrar")
    assert not any(p["codigodebarras"] == "ROTA001" for p in r.json())

    setor_estoque = make_setor(session, tipo="estoque")
    estoque_func = make_funcionario(session, setor_id=setor_estoque.id)
    token_estoque = set_token(session, estoque_func)

    r = client.get("/estoque/pendentes", headers=_headers(token_estoque))
    assert r.status_code == 200
    pendente = next(p for p in r.json() if p["codigodebarras"] == "ROTA001")

    r = client.post(f"/estoque/pendentes/{pendente['id']}/confirmar", json={
        "nomedoproduto": "Produto Rota", "codigodebarras": "ROTA001",
        "preco_venda": 7.0, "categoria": "Geral", "codigo_lote": "LOTE-ROTA001",
    }, headers=_headers(token_estoque))
    assert r.status_code == 200

    r = client.get("/estoque/mostrar")
    produto = next(p for p in r.json() if p["codigodebarras"] == "ROTA001")
    assert produto["quantidade"] == 5


def test_rota_registrar_nega_funcionario_fora_do_setor(client, session, engine):
    setor = make_setor(session, tipo="vendas_compra")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    token = set_token(session, func)
    r = client.post("/compras/registrar", json={"itens": [_item().model_dump(mode="json")]}, headers=_headers(token))
    assert r.status_code == 403


def test_rota_autorizar_nega_gerente(client, session, engine):
    setor = make_setor(session, tipo="compras20")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    compra = make_compra(session, gerente.id, status="aguardando_diretor")
    token = set_token(session, gerente)
    r = client.post(f"/compras/autorizar/{compra.id}", headers=_headers(token))
    assert r.status_code == 403
