import pytest
from fastapi import HTTPException
from sqlmodel import Session

from repository.solicitacoes import criar_solicitacao, listar_solicitacoes, responder_solicitacao
from services.auth import pode_responder_solicitacao, exigir_responder_solicitacao
from schemas.schemas import SolicitacaoInput, SolicitacaoResposta
from utils.database import Solicitacao
from conftest import make_setor, make_funcionario


def _input(titulo="Material de limpeza", descricao="Precisamos repor o estoque de limpeza", itens="- Detergente\n- Papel toalha"):
    return SolicitacaoInput(titulo=titulo, descricao=descricao, itens=itens)


# ── pode_responder_solicitacao / exigir_responder_solicitacao ───────────────

def test_pode_responder_solicitacao_admin(engine, session):
    setor = make_setor(session, tipo="sol_perm1")
    admin = make_funcionario(session, setor_id=setor.id, is_admin=True)
    assert pode_responder_solicitacao(admin) is True


def test_pode_responder_solicitacao_diretoria(engine, session):
    setor = make_setor(session, tipo="sol_perm2")
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    assert pode_responder_solicitacao(diretor) is True


def test_pode_responder_solicitacao_gerente_compras(engine, session):
    setor = make_setor(session, tipo="compras")
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    assert pode_responder_solicitacao(gerente) is True


def test_pode_responder_solicitacao_operacional_compras_nao_pode(engine, session):
    setor = make_setor(session, tipo="compras")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    assert pode_responder_solicitacao(func) is False


def test_pode_responder_solicitacao_funcionario_qualquer_nao_pode(engine, session):
    setor = make_setor(session, tipo="sol_perm3")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    assert pode_responder_solicitacao(func) is False


def test_exigir_responder_solicitacao_nega_quem_nao_pode(engine, session):
    setor = make_setor(session, tipo="sol_perm4")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    with pytest.raises(HTTPException) as exc:
        exigir_responder_solicitacao(func)
    assert exc.value.status_code == 403


# ── criar_solicitacao ────────────────────────────────────────────────────────
# Qualquer funcionário pode abrir uma solicitação -- diferente de
# registrar_compra (restrito ao setor compras), não há checagem de
# setor/cargo nenhuma aqui (ver routes/solicitacoes.py::criar).

def test_criar_solicitacao_qualquer_funcionario(engine, session):
    setor = make_setor(session, tipo="sol_criar1")
    func = make_funcionario(session, setor_id=setor.id, cargo="operacional")
    resultado = criar_solicitacao(_input(), func.id)
    assert "id" in resultado
    assert "detail" in resultado


def test_criar_solicitacao_estado_inicial_pendente(engine, session):
    setor = make_setor(session, tipo="sol_criar2")
    func = make_funcionario(session, setor_id=setor.id)
    resultado = criar_solicitacao(_input(), func.id)
    with Session(engine) as s:
        solicitacao = s.get(Solicitacao, resultado["id"])
    assert solicitacao.status == "pendente"
    assert solicitacao.solicitante_id == func.id
    assert solicitacao.resposta is None


# ── listar_solicitacoes ──────────────────────────────────────────────────────

def test_listar_solicitacoes_escopo_proprio(engine, session):
    setor = make_setor(session, tipo="sol_list1")
    f1 = make_funcionario(session, setor_id=setor.id)
    f2 = make_funcionario(session, setor_id=setor.id)
    criar_solicitacao(_input(titulo="Pedido do f1"), f1.id)
    criar_solicitacao(_input(titulo="Pedido do f2"), f2.id)

    lista_f1 = listar_solicitacoes(f1.id, ver_todas=False)

    assert len(lista_f1) == 1
    assert lista_f1[0]["titulo"] == "Pedido do f1"


def test_listar_solicitacoes_ver_todas(engine, session):
    setor = make_setor(session, tipo="sol_list2")
    f1 = make_funcionario(session, setor_id=setor.id)
    f2 = make_funcionario(session, setor_id=setor.id)
    criar_solicitacao(_input(titulo="Pedido do f1"), f1.id)
    criar_solicitacao(_input(titulo="Pedido do f2"), f2.id)

    lista = listar_solicitacoes(f1.id, ver_todas=True)

    assert len(lista) == 2


def test_listar_solicitacoes_inclui_nome_solicitante(engine, session):
    setor = make_setor(session, tipo="sol_list3")
    func = make_funcionario(session, setor_id=setor.id, nome="Maria", sobrenome="Souza")
    criar_solicitacao(_input(), func.id)

    lista = listar_solicitacoes(func.id, ver_todas=True)

    assert lista[0]["solicitante"] == "Maria Souza"


def test_listar_solicitacoes_mais_recente_primeiro(engine, session):
    setor = make_setor(session, tipo="sol_list4")
    func = make_funcionario(session, setor_id=setor.id)
    r1 = criar_solicitacao(_input(titulo="Primeira"), func.id)
    r2 = criar_solicitacao(_input(titulo="Segunda"), func.id)

    lista = listar_solicitacoes(func.id, ver_todas=True)

    assert [s["id"] for s in lista] == [r2["id"], r1["id"]]


# ── responder_solicitacao ────────────────────────────────────────────────────

def test_responder_solicitacao_inexistente_404(engine, session):
    with pytest.raises(HTTPException) as exc:
        responder_solicitacao(999, SolicitacaoResposta(status="aprovada", resposta="ok"), 1)
    assert exc.value.status_code == 404


def test_responder_solicitacao_aprovada(engine, session):
    setor = make_setor(session, tipo="sol_resp1")
    func = make_funcionario(session, setor_id=setor.id)
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    r = criar_solicitacao(_input(), func.id)

    resultado = responder_solicitacao(
        r["id"], SolicitacaoResposta(status="aprovada", resposta="Pode comprar"), gerente.id,
    )

    assert "detail" in resultado
    with Session(engine) as s:
        solicitacao = s.get(Solicitacao, r["id"])
    assert solicitacao.status == "aprovada"
    assert solicitacao.resposta == "Pode comprar"
    assert solicitacao.respondido_por_id == gerente.id
    assert solicitacao.respondido_em is not None


def test_responder_solicitacao_recusada(engine, session):
    setor = make_setor(session, tipo="sol_resp2")
    func = make_funcionario(session, setor_id=setor.id)
    diretor = make_funcionario(session, setor_id=setor.id, cargo="diretoria")
    r = criar_solicitacao(_input(), func.id)

    responder_solicitacao(r["id"], SolicitacaoResposta(status="recusada", resposta="Sem verba"), diretor.id)

    with Session(engine) as s:
        solicitacao = s.get(Solicitacao, r["id"])
    assert solicitacao.status == "recusada"


def test_responder_solicitacao_ja_respondida_falha(engine, session):
    setor = make_setor(session, tipo="sol_resp3")
    func = make_funcionario(session, setor_id=setor.id)
    gerente = make_funcionario(session, setor_id=setor.id, cargo="gerente")
    r = criar_solicitacao(_input(), func.id)
    responder_solicitacao(r["id"], SolicitacaoResposta(status="aprovada", resposta="ok"), gerente.id)

    with pytest.raises(HTTPException) as exc:
        responder_solicitacao(r["id"], SolicitacaoResposta(status="recusada", resposta="mudei de ideia"), gerente.id)
    assert exc.value.status_code == 400


# ── validação de schema ──────────────────────────────────────────────────────

def test_solicitacao_input_rejeita_titulo_vazio():
    with pytest.raises(ValueError):
        SolicitacaoInput(titulo="   ", descricao="desc", itens="item")


def test_solicitacao_resposta_rejeita_comentario_vazio():
    with pytest.raises(ValueError):
        SolicitacaoResposta(status="aprovada", resposta="   ")


def test_solicitacao_resposta_rejeita_status_fora_do_literal():
    with pytest.raises(ValueError):
        SolicitacaoResposta(status="pendente", resposta="ok")
    with pytest.raises(ValueError):
        SolicitacaoResposta(status="qualquer_coisa", resposta="ok")


def test_solicitacao_input_rejeita_campos_acima_do_limite():
    with pytest.raises(ValueError):
        SolicitacaoInput(titulo="x" * 256, descricao="desc", itens="item")
    with pytest.raises(ValueError):
        SolicitacaoInput(titulo="titulo", descricao="x" * 2001, itens="item")
