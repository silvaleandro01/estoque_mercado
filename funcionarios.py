from sqlmodel import Session, select
import calendar
from fastapi import HTTPException
from datetime import datetime, timedelta, timezone, date
from jose import jwt, JWTError
from jose.exceptions import ExpiredSignatureError
from passlib.context import CryptContext
import re
import os

from database import Funcionario, FuncionarioCreate, Setor, engine, SECRET_KEY, ALGORITHM, SenhaHistorico, Ponto, Salario, Holerite, SalarioHistorico

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def criar_token(funcionario_id: int, is_admin: bool, horas: int = 12):
    if is_admin:
        expiracao = datetime.now(timezone.utc) + timedelta(days=365 * 100)
    else:
        expiracao = datetime.now(timezone.utc) + timedelta(hours=horas)

    payload = {
        "sub": str(funcionario_id),
        "exp": expiracao,
        "is_admin": is_admin
    }

    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, expiracao

def verificar_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        sub = payload.get("sub")
        if sub is None:
            return None

        return int(sub)

    except (ExpiredSignatureError, JWTError):
        return None

def converter_data(data_str: str):
    try:
        return date.fromisoformat(data_str)
    except:
        raise HTTPException(status_code=400, detail="Data inválida, use YYYY-MM-DD")

def validar_senha_forte(password: str):
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 8 caracteres")
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="A senha não pode ter mais de 72 caracteres (limite do sistema)")
    if not re.search("[a-z]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter letras minúsculas")
    if not re.search("[A-Z]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter letras maiúsculas")
    if not re.search("[0-9]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter números")
    if not re.search("[!@#$%^&*(),.?\":{}|<>]", password):
        raise HTTPException(status_code=400, detail="A senha deve conter caracteres especiais")

def gerar_username(nome: str, sobrenome: str):
    return f"{nome.strip().lower()}.{sobrenome.strip().lower()}"

def criar_funcionario(dados: FuncionarioCreate):
    with Session(engine) as session:
        dados_dict = dados.model_dump()
        valor_mensal = dados_dict.pop("valor_mensal", 0.0)
        
        if isinstance(dados_dict.get("data_nascimento"), str):
            dados_dict["data_nascimento"] = converter_data(dados_dict["data_nascimento"])

        funcionario = Funcionario(**dados_dict)
        try:
            session.add(funcionario)
            session.flush()
            session.refresh(funcionario)

            salario = Salario(funcionario_id=funcionario.id, valor_mensal=valor_mensal, valor_hora=valor_mensal / 176)
            session.add(salario)

            historico = SalarioHistorico(funcionario_id=funcionario.id, valor_antigo=0.0, valor_novo=valor_mensal)
            session.add(historico)

            session.commit()
            session.refresh(funcionario)
            return funcionario
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar funcionário")

        return funcionario

def autenticar_funcionario(username: str, password: str = ""):
    with Session(engine) as session:
        username = username.strip() # Remove espaços no início e fim
        partes = username.split(".", 1) # Divide apenas no primeiro ponto
        if len(partes) < 2:
             print(f"Tentativa de login com formato inválido: {username}")
             raise HTTPException(status_code=401, detail="Formato de usuário inválido (nome.sobrenome)")
        
        nome, sobrenome = partes[0].strip(), partes[1].strip()
        funcionario = session.exec(
            select(Funcionario).where(
                Funcionario.nome.ilike(nome), 
                Funcionario.sobrenome.ilike(sobrenome)
            )
        ).first()

        if not funcionario:
            
            raise HTTPException(status_code=401, detail="Usuário não encontrado. Verifique se o nome e sobrenome estão corretos.")

        if funcionario.password_hash is None:
            return {"status": "primeiro_acesso", "funcionario_id": funcionario.id}
        
        if funcionario.last_password_change:
            dias_desde_troca = (datetime.now(timezone.utc) - funcionario.last_password_change.replace(tzinfo=timezone.utc)).days
            if dias_desde_troca >= 15:
                return {"status": "senha_expirada", "funcionario_id": funcionario.id}

        if not pwd_context.verify(password, funcionario.password_hash):
            raise HTTPException(status_code=401, detail="Senha incorreta")

        token, exp = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        funcionario.token_expiracao = exp
        session.add(funcionario)
        session.commit()

        setor = session.get(Setor, funcionario.setor_id)
        return {
            "status": "sucesso", 
            "token": token,
            "is_admin": funcionario.is_admin,
            "setor": setor.tipo if setor else None
        }

def definir_nova_senha(funcionario_id: int, nova_senha: str):
    validar_senha_forte(nova_senha)
    
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
             raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        historico = session.exec(
            select(SenhaHistorico)
            .where(SenhaHistorico.funcionario_id == funcionario_id)
            .order_by(SenhaHistorico.data_criacao.desc())
            .limit(3)
        ).all()

        for registro in historico:
            if pwd_context.verify(nova_senha, registro.password_hash):
                raise HTTPException(status_code=400, detail="Você não pode usar as últimas 3 senhas")

        hash_novo = pwd_context.hash(nova_senha)
        funcionario.password_hash = hash_novo
        funcionario.last_password_change = datetime.now(timezone.utc)

        novo_historico = SenhaHistorico(funcionario_id=funcionario_id, password_hash=hash_novo)
        session.add(novo_historico)
 
        token, exp = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        funcionario.token_expiracao = exp
        
        session.add(funcionario)
        session.commit()

        setor = session.get(Setor, funcionario.setor_id)
        return {
            "status": "sucesso", 
            "token": token, 
            "is_admin": funcionario.is_admin,
            "setor": setor.tipo if setor else None
        }

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

        update_data = dados.model_dump()

        if "data_nascimento" in update_data:
            if isinstance(update_data["data_nascimento"], str):
                update_data["data_nascimento"] = converter_data(update_data["data_nascimento"])

        for key, value in update_data.items():
            setattr(funcionario, key, value)

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

def validar_funcionario_por_token(token: str):
    funcionario_id = verificar_token(token)

    if funcionario_id is None:
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=401, detail="Sessão inválida")

        agora = datetime.now(timezone.utc)

        expiracao = funcionario.token_expiracao
        if expiracao and expiracao.tzinfo is None:
            expiracao = expiracao.replace(tzinfo=timezone.utc)

        if not expiracao or expiracao < agora:
            raise HTTPException(status_code=401, detail="Token expirado")

        return funcionario

def verificar_permissao(funcionario: Funcionario, setores_permitidos: str | list[str]):
    if funcionario.is_admin:
        return True

    if isinstance(setores_permitidos, str):
        setores_permitidos = [setores_permitidos]

    with Session(engine) as session:
        setor = session.get(Setor, funcionario.setor_id)

        if not setor or setor.tipo.lower() not in [s.lower() for s in setores_permitidos]:
             raise HTTPException(status_code=403, detail="Acesso negado")

    return True


def renovar_token(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)

        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        token, exp = criar_token(funcionario_id, funcionario.is_admin)

        funcionario.token = token
        funcionario.token_expiracao = exp

        try:
            session.commit()
            session.refresh(funcionario)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao renovar token")

        return {
            "token": token,
            "expiracao": exp
        }

def registrar_ponto_funcionario(funcionario_id: int, data_manual: date = None, hora_manual: datetime = None):
    with Session(engine) as session:
        hoje = data_manual if data_manual else date.today()
        agora = hora_manual if hora_manual else datetime.now()
        
        ponto = session.exec(
            select(Ponto).where(Ponto.funcionario_id == funcionario_id, Ponto.data == hoje)
        ).first()

        if not ponto:
            ponto = Ponto(funcionario_id=funcionario_id, data=hoje, entrada=agora)
            session.add(ponto)
            msg = "Entrada registrada"
        elif not ponto.saida_almoco:
            ponto.saida_almoco = agora
            msg = "Saída para almoço registrada"
        elif not ponto.retorno_almoco:
            ponto.retorno_almoco = agora
            msg = "Retorno do almoço registrado"
        elif not ponto.saida:
            ponto.saida = agora
            periodo1 = (ponto.saida_almoco - ponto.entrada).total_seconds() / 3600
            periodo2 = (ponto.saida - ponto.retorno_almoco).total_seconds() / 3600
            total = periodo1 + periodo2
            
            ponto.horas_trabalhadas = round(total, 2)
            if total > 8:
                extra = total - 8
                ponto.horas_extras = round(extra, 2)
                ponto.horas_devidas = 0
            else:
                ponto.horas_extras = 0
                ponto.horas_devidas = round(8 - total, 2)
                
            msg = "Saída encerrada. Horas calculadas."
        else:
            raise HTTPException(status_code=400, detail="Todos os pontos de hoje já foram batidos.")

        session.add(ponto)
        session.commit()
        return {"detail": msg}

def obter_status_ponto(funcionario_id: int):
    with Session(engine) as session:
        hoje = date.today()
        return session.exec(
            select(Ponto).where(Ponto.funcionario_id == funcionario_id, Ponto.data == hoje)
        ).first()

def relatorio_mensal_funcionario(funcionario_id: int, mes: int, ano: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        inicio_mes = date(ano, mes, 1)
        if mes == 12:
            fim_mes = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            fim_mes = date(ano, mes + 1, 1) - timedelta(days=1)

        pontos = session.exec(
            select(Ponto).where(
                Ponto.funcionario_id == funcionario_id,
                Ponto.data >= inicio_mes,
                Ponto.data <= fim_mes
            ).order_by(Ponto.data.desc())
        ).all()
        
        salario = session.exec(select(Salario).where(Salario.funcionario_id == funcionario_id)).first()
        valor_hora = salario.valor_hora if salario else 0.0

        total_trabalhado = sum(p.horas_trabalhadas for p in pontos)
        total_extra = sum(p.horas_extras for p in pontos)
        total_devido = sum(p.horas_devidas for p in pontos)
        saldo_mensal = total_extra - total_devido

        total_financeiro = 0.0
        pontos_detalhados = []
        for p in pontos:
            h_normais = min(p.horas_trabalhadas, 8.0)
            h_extras = max(0.0, p.horas_trabalhadas - 8.0)
            
            ganho_dia = (h_normais * valor_hora) + (h_extras * valor_hora * 1.5)
            total_financeiro += ganho_dia

            p_data = p.model_dump()
            p_data["valor_monetario"] = round(ganho_dia, 2)
            pontos_detalhados.append(p_data)

        return {
            "funcionario": f"{funcionario.nome} {funcionario.sobrenome}" if funcionario else "Colaborador",
            "pontos": pontos_detalhados,
            "resumo": {
                "total_trabalhado_mes": round(total_trabalhado, 2),
                "total_extra_mes": round(total_extra, 2),
                "total_devido_mes": round(total_devido, 2),
                "saldo_mensal": round(saldo_mensal, 2),
                "salario_base": salario.valor_mensal if salario else 0,
                "valor_hora": round(valor_hora, 2),
                "total_a_receber": round(total_financeiro, 2)
            }
        }

def relatorio_geral_pontos_rh(mes: int, ano: int):
    with Session(engine) as session:
        inicio_mes = date(ano, mes, 1)
        if mes == 12:
            fim_mes = date(ano + 1, 1, 1) - timedelta(days=1)
        else:
            fim_mes = date(ano, mes + 1, 1) - timedelta(days=1)

        statement = select(Ponto, Funcionario).join(Funcionario).where(
            Ponto.data >= inicio_mes,
            Ponto.data <= fim_mes
        ).order_by(Ponto.data.desc(), Funcionario.nome)
        
        resultados = session.exec(statement).all()
        
        return [{
            "id": p.id,
            "data": p.data,
            "funcionario": f"{f.nome} {f.sobrenome}",
            "trabalhadas": p.horas_trabalhadas,
            "extras": p.horas_extras,
            "devidas": p.horas_devidas,
            "entrada": p.entrada,
            "saida": p.saida
        } for p, f in resultados]

def definir_salario_funcionario(funcionario_id: int, valor: float):
    with Session(engine) as session:
        salario = session.exec(select(Salario).where(Salario.funcionario_id == funcionario_id)).first()
        valor_antigo = salario.valor_mensal if salario else 0.0

        if not salario:
            salario = Salario(funcionario_id=funcionario_id)

        salario.valor_mensal = valor
        salario.valor_hora = valor / 176

        historico = SalarioHistorico(funcionario_id=funcionario_id, valor_antigo=valor_antigo, valor_novo=valor)
        
        session.add(salario)
        session.add(historico)
        session.commit()
        session.refresh(salario)
        return salario

def buscar_historico_salarial(funcionario_id: int):
    with Session(engine) as session:
        return session.exec(select(SalarioHistorico).where(SalarioHistorico.funcionario_id == funcionario_id).order_by(SalarioHistorico.data_alteracao.desc())).all()

def fechar_folha_mensal(mes: int, ano: int):
    with Session(engine) as session:
        funcionarios = session.exec(select(Funcionario).where(Funcionario.is_admin == False)).all()
        total_processado = 0
        
        for f in funcionarios:
            relatorio = relatorio_mensal_funcionario(f.id, mes, ano)
            resumo = relatorio["resumo"]
            
            h_extras = resumo["total_extra_mes"]
            h_trabalhadas = resumo["total_trabalhado_mes"]
            v_hora = resumo["valor_hora"]
            
            v_extras = round(h_extras * v_hora * 1.5, 2)
            v_base_proporcional = round(max(0, resumo["total_a_receber"] - v_extras), 2)
            
            bruto_total = v_base_proporcional + v_extras
            
            fator_proporcao = min(h_trabalhadas / 176, 1.0) if h_trabalhadas > 0 else 0
            
            inss = round(bruto_total * 0.11, 2)
            irpf = round(bruto_total * 0.075, 2) if bruto_total > 1903.98 else 0
            vt = round(v_base_proporcional * 0.06, 2)
            vale = round(bruto_total * 0.40, 2)
            fgts = round(bruto_total * 0.08, 2)
            
            vr_desc = round(220.0 * fator_proporcao, 2)
            contribuicao = round(30.0 * fator_proporcao, 2)
            ajuda_custo = round(100.0 * fator_proporcao, 2)
            
            liquido = round((bruto_total + ajuda_custo) - (inss + irpf + vt + vale + contribuicao + vr_desc), 2)
            
            dias_no_mes = calendar.monthrange(ano, mes)[1]

            holerite = session.exec(
                select(Holerite).where(
                    Holerite.funcionario_id == f.id, 
                    Holerite.mes == mes, 
                    Holerite.ano == ano
                )
            ).first()
            
            if not holerite:
                holerite = Holerite(funcionario_id=f.id, mes=mes, ano=ano, data_competencia=date(ano, mes, 1))
            
            holerite.salario_base = v_base_proporcional
            holerite.valor_bruto = bruto_total
            holerite.valor_liquido = liquido
            holerite.data_competencia = date(ano, mes, 1)
            holerite.inss = round(inss, 2)
            holerite.irpf = round(irpf, 2)
            holerite.fgts = round(fgts, 2)
            holerite.vale_transporte = round(vt, 2)
            holerite.vale_refeicao = vr_desc
            holerite.adiantamento = round(vale, 2)
            holerite.contribuicao_assistencial = contribuicao
            holerite.ajuda_custo = ajuda_custo
            holerite.horas_extras_valor = v_extras
            holerite.horas_trabalhadas = resumo["total_trabalhado_mes"]
            holerite.horas_extras = resumo["total_extra_mes"]
            holerite.horas_devidas = resumo["total_devido_mes"]
            holerite.dias_trabalhados = dias_no_mes
            holerite.data_emissao = datetime.now()
            
            session.add(holerite)
            total_processado += 1
            
        session.commit()
        return {"detail": f"Folha de {mes}/{ano} fechada para {total_processado} funcionários."}

def assinar_holerite_funcionario(funcionario_id: int, holerite_id: int):
    with Session(engine) as session:
        holerite = session.get(Holerite, holerite_id)
        if not holerite or holerite.funcionario_id != funcionario_id:
            raise HTTPException(status_code=404, detail="Holerite não encontrado")
        
        holerite.assinado = True
        holerite.data_assinatura = datetime.now()
        session.add(holerite)
        session.commit()
        return {"detail": "Holerite assinado com sucesso"}

def buscar_holerite_funcionario(funcionario_id: int, mes: int, ano: int):
    try:
        with Session(engine) as session:
            statement = select(Holerite).where(
                Holerite.funcionario_id == funcionario_id, 
                Holerite.mes == mes, 
                Holerite.ano == ano
            )
            return session.exec(statement).first()
    except Exception as e:
        print(f"Erro de Banco de Dados: {e}")
        return None