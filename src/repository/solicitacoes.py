from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Solicitacao, Funcionario, engine
from logs.logs import criar_log
from schemas.schemas import SolicitacaoInput, SolicitacaoResposta


def _nome_completo(session: Session, funcionario_id: int) -> str:
    funcionario = session.get(Funcionario, funcionario_id)
    return f"{funcionario.nome} {funcionario.sobrenome}" if funcionario else "-"


def criar_solicitacao(dados: SolicitacaoInput, funcionario_id: int):
    with Session(engine) as session:
        solicitacao = Solicitacao(
            titulo=dados.titulo, descricao=dados.descricao, itens=dados.itens,
            solicitante_id=funcionario_id,
        )
        session.add(solicitacao)
        session.commit()
        session.refresh(solicitacao)

    criar_log(funcionario_id, f"Solicitação de compra criada: #{solicitacao.id}")
    return {"detail": f"Solicitação #{solicitacao.id} enviada com sucesso", "id": solicitacao.id}


def listar_solicitacoes(funcionario_id: int, ver_todas: bool) -> List[dict]:
    with Session(engine) as session:
        query = select(Solicitacao).order_by(Solicitacao.data.desc())
        if not ver_todas:
            # Quem não pode responder só vê as próprias solicitações -- ver
            # services/auth.py::pode_responder_solicitacao, que decide este
            # escopo na rota.
            query = query.where(Solicitacao.solicitante_id == funcionario_id)
        solicitacoes = session.exec(query).all()
        return [
            {
                "id": s.id,
                "titulo": s.titulo,
                "descricao": s.descricao,
                "itens": s.itens,
                "solicitante": _nome_completo(session, s.solicitante_id),
                "status": s.status,
                "resposta": s.resposta,
                "respondido_por": _nome_completo(session, s.respondido_por_id) if s.respondido_por_id else None,
                "data": s.data,
            }
            for s in solicitacoes
        ]


def responder_solicitacao(solicitacao_id: int, dados: SolicitacaoResposta, funcionario_id: int):
    with Session(engine) as session:
        solicitacao = session.exec(
            select(Solicitacao).where(Solicitacao.id == solicitacao_id).with_for_update()
        ).first()
        if not solicitacao:
            raise HTTPException(status_code=404, detail="Solicitação não encontrada")
        if solicitacao.status != "pendente":
            raise HTTPException(status_code=400, detail="Solicitação já foi respondida")

        solicitacao.status = dados.status
        solicitacao.resposta = dados.resposta
        solicitacao.respondido_por_id = funcionario_id
        solicitacao.respondido_em = datetime.now(timezone.utc)
        session.add(solicitacao)
        session.commit()

    criar_log(funcionario_id, f"Solicitação de compra respondida: #{solicitacao_id} ({dados.status})")
    return {"detail": f"Solicitação #{solicitacao_id} marcada como {dados.status}"}
