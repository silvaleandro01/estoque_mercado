from fastapi import HTTPException
from sqlmodel import Session, select
from datetime import datetime
from typing import List
from pydantic import BaseModel

from database import engine, Funcionario, Setor, Comunicado, ComunicadoDestinatario


class SolicitacaoCompraCreate(BaseModel):
    titulo: str
    descricao: str
    itens: str


class SolicitacaoCompraUpdate(BaseModel):
    status: str
    resposta: str = ""


def _notificar(session, autor_id: int, destinatarios_ids: List[int], titulo: str, conteudo: str):
    comunicado = Comunicado(
        titulo=titulo,
        conteudo=conteudo,
        autor_id=autor_id,
        para_todos=False,
    )
    session.add(comunicado)
    session.flush()
    session.refresh(comunicado)
    for fid in destinatarios_ids:
        session.add(ComunicadoDestinatario(
            comunicado_id=comunicado.id,
            funcionario_id=fid,
            lido=False,
        ))


def criar_solicitacao(dados: SolicitacaoCompraCreate, diretor_id: int):
    from database import SolicitacaoVendas
    sol_id = None
    with Session(engine) as session:
        sol = SolicitacaoVendas(
            titulo=dados.titulo,
            descricao=dados.descricao,
            itens=dados.itens,
            diretor_id=diretor_id,
            status="pendente",
        )
        session.add(sol)
        session.commit()
        session.refresh(sol)
        sol_id = sol.id

    try:
        with Session(engine) as session:
            setor_compras = session.exec(
                select(Setor).where(Setor.tipo.ilike("compras"))
            ).first()
            gerentes_ids = []
            if setor_compras:
                funcionarios = session.exec(
                    select(Funcionario).where(Funcionario.setor_id == setor_compras.id)
                ).all()
                gerentes_ids = [f.id for f in funcionarios if "gerente" in f.cargo.lower()]

            if gerentes_ids:
                diretor = session.get(Funcionario, diretor_id)
                nome_diretor = f"{diretor.nome} {diretor.sobrenome}" if diretor else "Diretor"
                titulo_curto = dados.titulo[:140] + "..." if len(dados.titulo) > 140 else dados.titulo
                _notificar(
                    session, diretor_id, gerentes_ids,
                    f"Nova solicitação #{sol_id}: {titulo_curto}",
                    f"O(a) {nome_diretor} enviou uma solicitação de compra para o setor de compras.\n\n"
                    f"Título: {dados.titulo}\n"
                    f"Descrição: {dados.descricao}\n"
                    f"Itens solicitados:\n{dados.itens}"
                )
                session.commit()
    except Exception:
        pass

    return {"detail": "Solicitação enviada ao gerente de compras.", "id": sol_id}


def listar_solicitacoes(funcionario: Funcionario):
    from database import SolicitacaoVendas
    with Session(engine) as session:
        solicitacoes = session.exec(
            select(SolicitacaoVendas).order_by(SolicitacaoVendas.id.desc())
        ).all()

        resultado = []
        for sol in solicitacoes:
            diretor = session.get(Funcionario, sol.diretor_id)
            resultado.append({
                "id": sol.id,
                "titulo": sol.titulo,
                "descricao": sol.descricao,
                "itens": sol.itens,
                "status": sol.status,
                "resposta": sol.resposta or "",
                "diretor": f"{diretor.nome} {diretor.sobrenome}" if diretor else "Desconhecido",
                "data_criacao": sol.data_criacao.isoformat(),
                "data_atualizacao": sol.data_atualizacao.isoformat() if sol.data_atualizacao else None,
            })
        return resultado


def responder_solicitacao(sol_id: int, dados: SolicitacaoCompraUpdate, gerente_id: int):
    from database import SolicitacaoVendas
    status_validos = ["em_andamento", "concluida", "recusada"]
    if dados.status not in status_validos:
        raise HTTPException(status_code=400, detail=f"Status inválido. Use: {status_validos}")

    with Session(engine) as session:
        sol = session.get(SolicitacaoVendas, sol_id)
        if not sol:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
        if sol.status == "concluida":
            raise HTTPException(status_code=400, detail="Solicitação já concluída.")

        sol.status = dados.status
        sol.resposta = dados.resposta
        sol.data_atualizacao = datetime.now()
        session.add(sol)
        session.flush()

        label = {"em_andamento": "EM ANDAMENTO", "concluida": "CONCLUÍDA", "recusada": "RECUSADA"}
        gerente = session.get(Funcionario, gerente_id)
        nome_gerente = f"{gerente.nome} {gerente.sobrenome}" if gerente else "Gerente de Compras"

        _notificar(
            session, gerente_id, [sol.diretor_id],
            f"Solicitação de compra #{sol_id} atualizada: {label[dados.status]}",
            f"O(a) {nome_gerente} atualizou o status da sua solicitação \"{sol.titulo}\" para: {label[dados.status]}.\n\n"
            + (f"Resposta: {dados.resposta}" if dados.resposta else "Nenhuma observação adicionada.")
        )

        session.commit()
        return {"detail": "Solicitação atualizada e diretor notificado."}
