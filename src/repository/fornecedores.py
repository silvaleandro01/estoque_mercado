from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from utils.database import Fornecedor, engine
from logs.logs import criar_log
from schemas.schemas import FornecedorInput


def criar_fornecedor(dados: FornecedorInput, funcionario_id: int):
    with Session(engine) as session:
        existente = session.exec(select(Fornecedor).where(Fornecedor.documento == dados.documento)).first()
        if existente:
            raise HTTPException(status_code=400, detail="Já existe fornecedor com este CPF/CNPJ")

        fornecedor = Fornecedor(
            nome=dados.nome,
            documento=dados.documento,
            telefone=dados.telefone,
            email=dados.email,
            prazo_medio_entrega_dias=dados.prazo_medio_entrega_dias,
        )
        try:
            session.add(fornecedor)
            session.commit()
            session.refresh(fornecedor)
            criar_log(funcionario_id, f"Cadastro de fornecedor: {fornecedor.nome}")
            return fornecedor
        except IntegrityError:
            # TOCTOU (time-of-check to time-of-use): o SELECT acima e este
            # INSERT não são atômicos -- sob concorrência real, duas
            # requisições podem passar pelo SELECT (nenhuma encontra
            # duplicado ainda, porque nenhuma comitou) antes de qualquer uma
            # fazer o INSERT. A segunda bate na UNIQUE KEY do banco
            # (documento), e sem isto virava um 500 cru em vez do 400
            # esperado (~22% das colisões em teste de carga real). Mesmo
            # padrão de repository/vendas.py::criar_venda para distinguir um
            # erro de banco específico e esperável de qualquer outra falha.
            session.rollback()
            raise HTTPException(status_code=400, detail="Já existe fornecedor com este CPF/CNPJ")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar fornecedor")


def mostrar_fornecedores():
    with Session(engine) as session:
        return session.exec(select(Fornecedor)).all()


def buscar_fornecedor(fornecedor_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
        return fornecedor


def atualizar_fornecedor(fornecedor_id: int, dados: FornecedorInput, funcionario_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")

        duplicado = session.exec(
            select(Fornecedor).where(Fornecedor.documento == dados.documento)
        ).first()
        if duplicado and duplicado.id != fornecedor.id:
            raise HTTPException(status_code=400, detail="CPF/CNPJ já cadastrado em outro fornecedor")

        fornecedor.nome = dados.nome
        fornecedor.documento = dados.documento
        fornecedor.telefone = dados.telefone
        fornecedor.email = dados.email
        fornecedor.prazo_medio_entrega_dias = dados.prazo_medio_entrega_dias

        try:
            session.commit()
            session.refresh(fornecedor)
            criar_log(funcionario_id, f"Atualização de fornecedor: {fornecedor.nome}")
            return fornecedor
        except IntegrityError:
            # Mesmo TOCTOU de criar_fornecedor, agora entre o SELECT de
            # duplicado acima e este UPDATE.
            session.rollback()
            raise HTTPException(status_code=400, detail="CPF/CNPJ já cadastrado em outro fornecedor")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar fornecedor")


def deletar_fornecedor(fornecedor_id: int):
    with Session(engine) as session:
        fornecedor = session.get(Fornecedor, fornecedor_id)
        if not fornecedor:
            raise HTTPException(status_code=404, detail="Fornecedor não encontrado")
        try:
            session.delete(fornecedor)
            session.commit()
            return {"msg": "Fornecedor deletado com sucesso"}
        except IntegrityError:
            # Em MySQL real, fornecedor_id em `estoque`/`compra` tem FK sem
            # ON DELETE (fk_estoque_fornecedor/fk_compra_fornecedor, ver
            # migration.sql) -- deletar um fornecedor ainda vinculado a
            # produto ou compra bate nessa constraint. Antes, o `except
            # Exception` genérico abaixo capturava isso também e devolvia um
            # 500 cru; agora é um 409 claro e específico desse cenário.
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Fornecedor possui produtos ou compras vinculados, não pode ser excluído",
            )
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar fornecedor")
