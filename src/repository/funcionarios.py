import secrets
import string
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Funcionario, HistoricoSenha, Setor, engine
from utils.security import criar_token, hash_senha, verificar_senha
from utils.email import enviar_email
from schemas.schemas import FuncionarioCreate, LoginRequest, TrocarSenhaRequest, RecuperarSenhaRequest


def _registrar_historico(session: Session, funcionario_id: int, password_hash: str):
    session.add(HistoricoSenha(funcionario_id=funcionario_id, password_hash=password_hash))


def _senha_ja_usada(session: Session, funcionario_id: int, nova_senha: str) -> bool:
    historico = session.exec(
        select(HistoricoSenha)
        .where(HistoricoSenha.funcionario_id == funcionario_id)
        .order_by(HistoricoSenha.criado_em.desc())
        .limit(3)
    ).all()
    return any(verificar_senha(nova_senha, h.password_hash) for h in historico)


def autenticar_funcionario(dados: LoginRequest):
    with Session(engine) as session:
        partes = dados.username.strip().split(".", 1)
        if len(partes) < 2:
            raise HTTPException(status_code=401, detail="Formato inválido. Use nome.sobrenome")

        nome, sobrenome = partes[0].strip(), partes[1].strip()
        funcionario = session.exec(
            select(Funcionario).where(
                Funcionario.nome.ilike(nome),
                Funcionario.sobrenome.ilike(sobrenome),
            )
        ).first()

        if not funcionario:
            raise HTTPException(status_code=401, detail="Usuário não encontrado")

        if not funcionario.password_hash:
            raise HTTPException(status_code=401, detail="Senha não definida. Contate o administrador.")

        if not verificar_senha(dados.senha, funcionario.password_hash):
            raise HTTPException(status_code=401, detail="Senha incorreta")

        token = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        session.add(funcionario)
        session.commit()

        setor = session.get(Setor, funcionario.setor_id)

        agora = datetime.now(timezone.utc)
        ultima = funcionario.senha_atualizada_em
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        lembrete_senha = bool(ultima and (agora - ultima) >= timedelta(days=365))

        return {
            "token": token,
            "is_admin": funcionario.is_admin,
            "setor": setor.tipo if setor else None,
            "nome_completo": f"{funcionario.nome} {funcionario.sobrenome}",
            "lembrete_senha": lembrete_senha,
            "senha_temporaria": funcionario.senha_temporaria,
        }


def criar_funcionario(dados: FuncionarioCreate):
    if not dados.senha:
        raise HTTPException(status_code=400, detail="Senha é obrigatória para novo funcionário")

    with Session(engine) as session:
        if session.exec(select(Funcionario).where(Funcionario.cpf == dados.cpf)).first():
            raise HTTPException(status_code=400, detail="CPF já cadastrado")

        if session.exec(select(Funcionario).where(Funcionario.email == dados.email)).first():
            raise HTTPException(status_code=400, detail="Email já cadastrado")

        password_hash = hash_senha(dados.senha)
        funcionario = Funcionario(
            nome=dados.nome,
            sobrenome=dados.sobrenome,
            data_nascimento=dados.data_nascimento,
            genero=dados.genero,
            possui_filhos=dados.possui_filhos,
            setor_id=dados.setor_id,
            cpf=dados.cpf,
            email=dados.email,
            cep=dados.cep,
            estado=dados.estado,
            cidade=dados.cidade,
            bairro=dados.bairro,
            rua=dados.rua,
            numero=dados.numero,
            password_hash=password_hash,
            senha_atualizada_em=datetime.now(timezone.utc),
        )
        try:
            session.add(funcionario)
            session.flush()
            _registrar_historico(session, funcionario.id, password_hash)
            session.commit()
            session.refresh(funcionario)
            return funcionario
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar funcionário")


def listar_funcionarios():
    with Session(engine) as session:
        return session.exec(select(Funcionario)).all()


def buscar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")
        return funcionario


def atualizar_funcionario(funcionario_id: int, dados: FuncionarioCreate):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        cpf_existente = session.exec(
            select(Funcionario).where(Funcionario.cpf == dados.cpf, Funcionario.id != funcionario_id)
        ).first()
        if cpf_existente:
            raise HTTPException(status_code=400, detail="CPF já cadastrado em outro funcionário")

        email_existente = session.exec(
            select(Funcionario).where(Funcionario.email == dados.email, Funcionario.id != funcionario_id)
        ).first()
        if email_existente:
            raise HTTPException(status_code=400, detail="Email já cadastrado em outro funcionário")

        funcionario.nome = dados.nome
        funcionario.sobrenome = dados.sobrenome
        funcionario.data_nascimento = dados.data_nascimento
        funcionario.genero = dados.genero
        funcionario.possui_filhos = dados.possui_filhos
        funcionario.setor_id = dados.setor_id
        funcionario.cpf = dados.cpf
        funcionario.email = dados.email
        funcionario.cep = dados.cep
        funcionario.estado = dados.estado
        funcionario.cidade = dados.cidade
        funcionario.bairro = dados.bairro
        funcionario.rua = dados.rua
        funcionario.numero = dados.numero

        if dados.senha:
            if _senha_ja_usada(session, funcionario_id, dados.senha):
                raise HTTPException(
                    status_code=400,
                    detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
                )
            funcionario.password_hash = hash_senha(dados.senha)
            funcionario.senha_atualizada_em = datetime.now(timezone.utc)
            _registrar_historico(session, funcionario_id, funcionario.password_hash)

        try:
            session.commit()
            session.refresh(funcionario)
            return funcionario
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar funcionário")


def deletar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")
        try:
            session.delete(funcionario)
            session.commit()
            return {"msg": "Funcionário deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar funcionário")


def renovar_token(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        token = criar_token(funcionario_id, funcionario.is_admin)
        funcionario.token = token
        try:
            session.commit()
            session.refresh(funcionario)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao renovar token")

        return {"token": token}


def trocar_senha(funcionario_id: int, dados: TrocarSenhaRequest):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        if not funcionario.password_hash or not verificar_senha(dados.senha_atual, funcionario.password_hash):
            raise HTTPException(status_code=401, detail="Senha atual incorreta")

        if _senha_ja_usada(session, funcionario_id, dados.nova_senha):
            raise HTTPException(
                status_code=400,
                detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
            )

        novo_hash = hash_senha(dados.nova_senha)
        funcionario.password_hash = novo_hash
        funcionario.senha_atualizada_em = datetime.now(timezone.utc)
        funcionario.senha_temporaria = False
        _registrar_historico(session, funcionario_id, novo_hash)

        try:
            session.commit()
            return {"msg": "Senha alterada com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao alterar senha")


def recuperar_senha(dados: RecuperarSenhaRequest):
    with Session(engine) as session:
        funcionario = session.exec(
            select(Funcionario).where(Funcionario.cpf == dados.cpf)
        ).first()

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        if not funcionario.email:
            raise HTTPException(status_code=400, detail="Funcionário sem email cadastrado. Contate o RH.")

        chars = string.ascii_letters + string.digits
        nova_senha = "".join(secrets.choice(chars) for _ in range(12))

        novo_hash = hash_senha(nova_senha)
        funcionario.password_hash = novo_hash
        funcionario.senha_atualizada_em = datetime.now(timezone.utc)
        funcionario.senha_temporaria = True
        _registrar_historico(session, funcionario.id, novo_hash)

        try:
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao redefinir senha")

        try:
            enviar_email(
                destinatario=funcionario.email,
                assunto="Recuperação de Senha — Sistema de Estoque",
                corpo=(
                    f"Olá, {funcionario.nome}!\n\n"
                    f"Sua nova senha temporária é: {nova_senha}\n\n"
                    "Acesse o sistema e troque a senha assim que possível.\n"
                    "Por segurança, não compartilhe esta senha com ninguém."
                ),
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except Exception:
            raise HTTPException(
                status_code=500,
                detail="Senha redefinida, mas ocorreu um erro ao enviar o email. Contate o administrador.",
            )

        return {"msg": "Nova senha enviada para o email cadastrado"}
