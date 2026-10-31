from datetime import datetime, timezone
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Comunicado, ComunicadoDestinatario, Funcionario, engine
from schemas.schemas import ComunicadoInput


def criar_comunicado(dados: ComunicadoInput, autor_id: int):
    with Session(engine) as session:
        comunicado = Comunicado(
            titulo=dados.titulo,
            conteudo=dados.conteudo,
            autor_id=autor_id,
            para_todos=dados.para_todos,
        )
        session.add(comunicado)
        session.flush()

        if dados.para_todos:
            ids = [f.id for f in session.exec(select(Funcionario)).all()]
        else:
            if not dados.destinatarios:
                raise HTTPException(status_code=400, detail="Informe ao menos um destinatário.")
            ids = dados.destinatarios

        agora = datetime.now(timezone.utc)
        for fid in ids:
            session.add(ComunicadoDestinatario(
                comunicado_id=comunicado.id,
                funcionario_id=fid,
                lido=(fid == autor_id),
                data_leitura=agora if fid == autor_id else None,
            ))

        try:
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao enviar comunicado")

        return {"detail": "Comunicado enviado com sucesso.", "id": comunicado.id}


def listar_comunicados(funcionario_id: int):
    with Session(engine) as session:
        destinatarios = session.exec(
            select(ComunicadoDestinatario).where(
                ComunicadoDestinatario.funcionario_id == funcionario_id
            )
        ).all()

        resultado = []
        for dest in destinatarios:
            comunicado = session.get(Comunicado, dest.comunicado_id)
            if not comunicado:
                continue
            autor = session.get(Funcionario, comunicado.autor_id)
            resultado.append({
                "id": comunicado.id,
                "titulo": comunicado.titulo,
                "conteudo": comunicado.conteudo,
                "autor": f"{autor.nome} {autor.sobrenome}" if autor else "Desconhecido",
                "data_criacao": comunicado.data_criacao,
                "para_todos": comunicado.para_todos,
                "lido": dest.lido,
                "destinatario_id": dest.id,
            })

        resultado.sort(key=lambda c: c["data_criacao"], reverse=True)
        return resultado


def contar_nao_lidos(funcionario_id: int):
    with Session(engine) as session:
        total = len(session.exec(
            select(ComunicadoDestinatario).where(
                ComunicadoDestinatario.funcionario_id == funcionario_id,
                ComunicadoDestinatario.lido == False,
            )
        ).all())
        return {"nao_lidos": total}


def marcar_como_lido(destinatario_id: int, funcionario_id: int):
    with Session(engine) as session:
        dest = session.get(ComunicadoDestinatario, destinatario_id)
        if not dest or dest.funcionario_id != funcionario_id:
            raise HTTPException(status_code=404, detail="Registro não encontrado.")
        if not dest.lido:
            dest.lido = True
            dest.data_leitura = datetime.now(timezone.utc)
            session.add(dest)
            try:
                session.commit()
            except Exception:
                session.rollback()
                raise HTTPException(status_code=500, detail="Erro ao marcar como lido")
        return {"detail": "Marcado como lido."}
