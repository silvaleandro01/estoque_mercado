from sqlmodel import Session, select
from fastapi import HTTPException
from database import Setor, SetorCreate, engine, Funcionario

def criar_setor(dados: SetorCreate):
    with Session(engine) as session:
        tipo_norm = dados.tipo.strip().lower()
        nome_norm = dados.nome.strip()
        
        existente = session.exec(
            select(Setor).where(Setor.tipo == tipo_norm)
        ).first()

        if existente:
            raise HTTPException(status_code=400, detail=f"O tipo '{tipo_norm}' já está cadastrado.")

        novo_setor = Setor(
            nome=nome_norm,
            tipo=tipo_norm
        )

        session.add(novo_setor)

        try:
            session.commit()
            session.refresh(novo_setor)
            return novo_setor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar setor")

def listar_setores():
    with Session(engine) as session:
        return session.exec(select(Setor)).all()

def buscar_setor(id: int):
    with Session(engine) as session:
        setor = session.get(Setor, id)

        if setor and setor.tipo == "admin":
            raise HTTPException(status_code=400, detail="O setor 'admin' é restrito.")
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")

        return setor
def atualizar_setor(id: int, dados: SetorCreate):
    with Session(engine) as session:
        setor = session.get(Setor, id)

        if setor and setor.tipo == "admin":
            raise HTTPException(status_code=400, detail="O setor 'admin' não pode ser editado.")
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")

        tipo_norm = dados.tipo.strip().lower()
        existente = session.exec(
            select(Setor).where(
                Setor.tipo == tipo_norm,
                Setor.id != id
            )
        ).first()

        if existente:
            raise HTTPException(status_code=400, detail="Tipo já está em uso")

        setor.nome = dados.nome.strip()
        setor.tipo = tipo_norm

        try:
            session.commit()
            session.refresh(setor)
            return setor
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar setor")

def deletar_setor(id: int):
    with Session(engine) as session:
        setor = session.get(Setor, id)

        if setor and setor.tipo == "admin":
            raise HTTPException(status_code=400, detail="O setor 'admin' não pode ser excluído.")
        if not setor:
            raise HTTPException(status_code=404, detail="Setor não encontrado")

        # Verifica se existem funcionários vinculados a este setor
        vinculados = session.exec(select(Funcionario).where(Funcionario.setor_id == id)).first()
        if vinculados:
            raise HTTPException(status_code=400, detail="Não é possível excluir um setor que possui funcionários vinculados. Mova todos os funcionários para outro setor antes de excluir.")

        try:
            session.delete(setor)
            session.commit()
            return {"msg": "Setor deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar setor")