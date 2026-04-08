from fastapi import HTTPException
from sqlmodel import Session, select
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

from database import Comunicado, ComunicadoDestinatario, Funcionario, engine


class ComunicadoCreate(BaseModel):
    titulo: str
    conteudo: str
    para_todos: bool = True
    destinatarios: List[int] = []


def criar_comunicado(dados: ComunicadoCreate, autor_id: int):
    with Session(engine) as session:
        comunicado = Comunicado(
            titulo=dados.titulo,
            conteudo=dados.conteudo,
            autor_id=autor_id,
            para_todos=dados.para_todos,
        )
        session.add(comunicado)
        session.flush()
        session.refresh(comunicado)

        if dados.para_todos:
            funcionarios = session.exec(select(Funcionario)).all()
            ids = [f.id for f in funcionarios]
        else:
            if not dados.destinatarios:
                raise HTTPException(status_code=400, detail="Informe ao menos um destinatário.")
            ids = dados.destinatarios

        for fid in ids:
            dest = ComunicadoDestinatario(
                comunicado_id=comunicado.id,
                funcionario_id=fid,
                lido=(fid == autor_id),
                data_leitura=datetime.now() if fid == autor_id else None,
            )
            session.add(dest)

        session.commit()
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
            com = session.get(Comunicado, dest.comunicado_id)
            if not com:
                continue
            autor = session.get(Funcionario, com.autor_id)
            resultado.append({
                "id": com.id,
                "titulo": com.titulo,
                "conteudo": com.conteudo,
                "autor": f"{autor.nome} {autor.sobrenome}" if autor else "Desconhecido",
                "data_criacao": com.data_criacao.isoformat(),
                "para_todos": com.para_todos,
                "lido": dest.lido,
                "destinatario_id": dest.id,
            })

        resultado.sort(key=lambda x: x["data_criacao"], reverse=True)
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
            dest.data_leitura = datetime.now()
            session.add(dest)
            session.commit()
        return {"detail": "Marcado como lido."}
