import pytest
from fastapi import HTTPException

from repository.comunicados import (
    criar_comunicado, listar_comunicados, contar_nao_lidos, marcar_como_lido,
)
from services.auth import exigir_escrever_comunicado
from schemas.schemas import ComunicadoInput
from conftest import make_setor, make_funcionario, set_token


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


# ── exigir_escrever_comunicado ───────────────────────────────────────────────

def test_exigir_escrever_comunicado_admin(engine, session):
    setor = make_setor(session, tipo="vendas_com1")
    admin = make_funcionario(session, setor_id=setor.id, is_admin=True)
    assert exigir_escrever_comunicado(admin) is True


def test_exigir_escrever_comunicado_gerente_qualquer_setor(engine, session):
    setor = make_setor(session, tipo="vendas_com2")
    func = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    assert exigir_escrever_comunicado(func) is True


def test_exigir_escrever_comunicado_diretoria_qualquer_setor(engine, session):
    setor = make_setor(session, tipo="vendas_com3")
    func = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    assert exigir_escrever_comunicado(func) is True


def test_exigir_escrever_comunicado_setor_rh_qualquer_cargo(engine, session):
    setor = make_setor(session, tipo="rh")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    assert exigir_escrever_comunicado(func) is True


def test_exigir_escrever_comunicado_operacional_fora_do_rh_nega(engine, session):
    setor = make_setor(session, tipo="vendas_com4")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    with pytest.raises(HTTPException) as exc:
        exigir_escrever_comunicado(func)
    assert exc.value.status_code == 403


# ── criar_comunicado ─────────────────────────────────────────────────────────

def test_criar_comunicado_para_todos_autor_ja_nasce_lido(engine, session):
    setor = make_setor(session, tipo="vendas_com5")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    outro = make_funcionario(session, setor_id=setor.id)

    criar_comunicado(ComunicadoInput(titulo="Aviso", conteudo="Texto", para_todos=True), autor.id)

    lista_autor = listar_comunicados(autor.id)
    assert lista_autor[0]["lido"] is True

    lista_outro = listar_comunicados(outro.id)
    assert lista_outro[0]["lido"] is False
    assert lista_outro[0]["titulo"] == "Aviso"
    assert lista_outro[0]["autor"] == f"{autor.nome} {autor.sobrenome}"


def test_criar_comunicado_destinatarios_especificos(engine, session):
    setor = make_setor(session, tipo="vendas_com6")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)
    nao_destinatario = make_funcionario(session, setor_id=setor.id)

    criar_comunicado(
        ComunicadoInput(titulo="Só pra você", conteudo="X", para_todos=False,
                        destinatarios=[destinatario.id]),
        autor.id,
    )

    assert len(listar_comunicados(destinatario.id)) == 1
    assert len(listar_comunicados(nao_destinatario.id)) == 0


def test_criar_comunicado_especifico_sem_destinatarios_falha(engine, session):
    setor = make_setor(session, tipo="vendas_com7")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    with pytest.raises(HTTPException) as exc:
        criar_comunicado(
            ComunicadoInput(titulo="X", conteudo="Y", para_todos=False, destinatarios=[]),
            autor.id,
        )
    assert exc.value.status_code == 400


# ── listar_comunicados / contar_nao_lidos ───────────────────────────────────

def test_listar_comunicados_ordem_mais_recente_primeiro(engine, session):
    setor = make_setor(session, tipo="vendas_com8")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)

    criar_comunicado(ComunicadoInput(titulo="Primeiro", conteudo="A", para_todos=True), autor.id)
    criar_comunicado(ComunicadoInput(titulo="Segundo", conteudo="B", para_todos=True), autor.id)

    lista = listar_comunicados(destinatario.id)
    assert lista[0]["titulo"] == "Segundo"
    assert lista[1]["titulo"] == "Primeiro"


def test_contar_nao_lidos(engine, session):
    setor = make_setor(session, tipo="vendas_com9")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)

    criar_comunicado(ComunicadoInput(titulo="A", conteudo="A", para_todos=True), autor.id)
    criar_comunicado(ComunicadoInput(titulo="B", conteudo="B", para_todos=True), autor.id)

    assert contar_nao_lidos(destinatario.id) == {"nao_lidos": 2}
    assert contar_nao_lidos(autor.id) == {"nao_lidos": 0}


# ── marcar_como_lido ─────────────────────────────────────────────────────────

def test_marcar_como_lido_sucesso(engine, session):
    setor = make_setor(session, tipo="vendas_com10")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)
    criar_comunicado(ComunicadoInput(titulo="A", conteudo="A", para_todos=True), autor.id)

    destinatario_id = listar_comunicados(destinatario.id)[0]["destinatario_id"]
    marcar_como_lido(destinatario_id, destinatario.id)

    assert contar_nao_lidos(destinatario.id) == {"nao_lidos": 0}


def test_marcar_como_lido_idempotente(engine, session):
    setor = make_setor(session, tipo="vendas_com11")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)
    criar_comunicado(ComunicadoInput(titulo="A", conteudo="A", para_todos=True), autor.id)
    destinatario_id = listar_comunicados(destinatario.id)[0]["destinatario_id"]

    marcar_como_lido(destinatario_id, destinatario.id)
    resultado = marcar_como_lido(destinatario_id, destinatario.id)
    assert resultado["detail"] == "Marcado como lido."


def test_marcar_como_lido_de_outro_funcionario_404(engine, session):
    setor = make_setor(session, tipo="vendas_com12")
    autor = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    destinatario = make_funcionario(session, setor_id=setor.id)
    intruso = make_funcionario(session, setor_id=setor.id)
    criar_comunicado(ComunicadoInput(titulo="A", conteudo="A", para_todos=True), autor.id)
    destinatario_id = listar_comunicados(destinatario.id)[0]["destinatario_id"]

    with pytest.raises(HTTPException) as exc:
        marcar_como_lido(destinatario_id, intruso.id)
    assert exc.value.status_code == 404


def test_marcar_como_lido_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        marcar_como_lido(99999, 1)
    assert exc.value.status_code == 404


# ── rotas HTTP ───────────────────────────────────────────────────────────────

def test_rota_criar_comunicado_nega_funcionario_sem_permissao(client, session, engine):
    setor = make_setor(session, tipo="vendas_com13")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    token = set_token(session, func)
    r = client.post("/comunicados/criar", json={
        "titulo": "X", "conteudo": "Y", "para_todos": True, "destinatarios": [],
    }, headers=_headers(token))
    assert r.status_code == 403


def test_rota_fluxo_completo(client, session, engine):
    setor = make_setor(session, tipo="vendas_com14")
    rh = make_funcionario(session, setor_id=client._test_setor_rh.id)
    destinatario = make_funcionario(session, setor_id=setor.id)
    token_rh = set_token(session, rh)
    token_dest = set_token(session, destinatario)

    r = client.post("/comunicados/criar", json={
        "titulo": "Comunicado Geral", "conteudo": "Texto do aviso",
        "para_todos": True, "destinatarios": [],
    }, headers=_headers(token_rh))
    assert r.status_code == 200

    r = client.get("/comunicados/nao-lidos", headers=_headers(token_dest))
    assert r.json()["nao_lidos"] == 1

    r = client.get("/comunicados/listar", headers=_headers(token_dest))
    assert r.status_code == 200
    item = next(c for c in r.json() if c["titulo"] == "Comunicado Geral")
    assert item["lido"] is False

    r = client.post(f"/comunicados/marcar-lido/{item['destinatario_id']}", headers=_headers(token_dest))
    assert r.status_code == 200

    r = client.get("/comunicados/nao-lidos", headers=_headers(token_dest))
    assert r.json()["nao_lidos"] == 0
