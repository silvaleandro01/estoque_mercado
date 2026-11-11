from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from utils.database import Funcionario, Holerite, Salario, engine
from utils.money import arredondar
from logs.logs import criar_log
from repository import pontos as pontos_repo

# Tabelas de alíquota progressiva do INSS/IRPF -- valores de referência
# conhecidos publicamente (2024/2025), fixados aqui como constantes.
# ATENÇÃO: essas tabelas mudam por portaria TODA faixa de ano fiscal; quem
# for reaproveitar este código em produção de verdade precisa atualizar os
# valores abaixo (aceitável ficarem desatualizados num projeto de estudo,
# mas documentado para não ser confundido com um bug).
_FAIXAS_INSS = (
    (Decimal("1412.00"), Decimal("0.075")),
    (Decimal("2666.68"), Decimal("0.09")),
    (Decimal("4000.03"), Decimal("0.12")),
    (Decimal("7786.02"), Decimal("0.14")),
)

# (limite superior da faixa, alíquota, parcela a deduzir) -- aplicado sobre
# (valor_bruto - INSS). Não considera dedução por dependente: o modelo de
# Funcionario só tem `possui_filhos` booleano, sem quantidade de
# dependentes -- limitação conhecida desta primeira versão.
_FAIXAS_IRPF = (
    (Decimal("2259.20"), Decimal("0.00"), Decimal("0.00")),
    (Decimal("2826.65"), Decimal("0.075"), Decimal("169.44")),
    (Decimal("3751.05"), Decimal("0.15"), Decimal("381.44")),
    (Decimal("4664.68"), Decimal("0.225"), Decimal("662.77")),
)
_IRPF_ALIQUOTA_ACIMA_DO_TETO = Decimal("0.275")
_IRPF_DEDUCAO_ACIMA_DO_TETO = Decimal("896.00")

_ALIQUOTA_FGTS = Decimal("0.08")
_ALIQUOTA_VALE_TRANSPORTE = Decimal("0.06")


def _dias_uteis_mes(mes: int, ano: int) -> int:
    """Conta os dias de segunda a sexta do mês -- a jornada de 5x2 nunca
    gera `Ponto` batido em fim de semana, então usar "30 dias corridos"
    como divisor do salário-base (como a versão anterior desta função
    fazia) penalizava TODO mundo, não só quem faltava de verdade: mesmo
    frequência perfeita (bateu todo dia útil) dava só ~22/30 ≈ 73% do
    salário nominal. Achado do painel de revisão. Dividir por dias úteis
    do mês, não por 30, faz frequência perfeita = salário cheio."""
    total_dias = monthrange(ano, mes)[1]
    return sum(
        1 for dia in range(1, total_dias + 1)
        if date(ano, mes, dia).weekday() < 5  # 0=segunda ... 4=sexta
    )


def _calcular_inss(valor_bruto: Decimal) -> Decimal:
    """Desconto de INSS, progressivo por faixa: cada faixa paga só a sua
    alíquota sobre a parte do salário que cai nela (não é "achar a faixa e
    aplicar a alíquota no total"). Teto de contribuição = última faixa."""
    teto = _FAIXAS_INSS[-1][0]
    base = min(valor_bruto, teto)
    desconto = Decimal("0.00")
    piso_anterior = Decimal("0.00")
    for limite, aliquota in _FAIXAS_INSS:
        if base <= piso_anterior:
            break
        faixa = min(base, limite) - piso_anterior
        desconto += faixa * aliquota
        piso_anterior = limite
    return arredondar(desconto)


def _calcular_irpf(base_calculo: Decimal) -> Decimal:
    for limite, aliquota, deducao in _FAIXAS_IRPF:
        if base_calculo <= limite:
            imposto = base_calculo * aliquota - deducao
            return arredondar(max(imposto, Decimal("0.00")))
    imposto = base_calculo * _IRPF_ALIQUOTA_ACIMA_DO_TETO - _IRPF_DEDUCAO_ACIMA_DO_TETO
    return arredondar(max(imposto, Decimal("0.00")))


def fechar_folha(mes: int, ano: int, funcionario_id_solicitante: int) -> dict:
    data_competencia = date(ano, mes, 1)
    dias_uteis = _dias_uteis_mes(mes, ano)
    criados = 0
    pulados_concorrencia = 0
    with Session(engine) as session:
        # cargo de confiança (diretoria) tipicamente não bate ponto -- fica
        # de fora da consolidação automática desta primeira versão (ver
        # Funcionario.bate_ponto).
        funcionarios = session.exec(select(Funcionario).where(Funcionario.bate_ponto == True)).all()

        for funcionario in funcionarios:
            ja_existe = session.exec(
                select(Holerite).where(
                    Holerite.funcionario_id == funcionario.id,
                    Holerite.mes == mes,
                    Holerite.ano == ano,
                )
            ).first()
            if ja_existe:
                continue

            relatorio = pontos_repo.montar_relatorio(session, funcionario, mes, ano)
            salario = session.exec(select(Salario).where(Salario.funcionario_id == funcionario.id)).first()
            valor_mensal = salario.valor_mensal if salario else Decimal("0.00")
            valor_hora = salario.valor_hora if salario else Decimal("0.00")

            dias_trabalhados = sum(1 for p in relatorio.pontos if p.saida is not None)
            # Prorata por dias ÚTEIS do mês, não por 30 corridos -- ver
            # docstring de _dias_uteis_mes. min() protege contra
            # dias_trabalhados > dias_uteis (ex.: alguém bateu ponto num
            # sábado) virar salário acima do nominal.
            dias_pagos = min(dias_trabalhados, dias_uteis)
            salario_base = (
                arredondar(valor_mensal * Decimal(dias_pagos) / Decimal(dias_uteis))
                if dias_uteis > 0 else Decimal("0.00")
            )
            horas_extras_valor = arredondar(relatorio.resumo.total_extra_mes * valor_hora * Decimal("1.5"))
            # Simétrico à hora extra: horas devidas (chegou atrasado/saiu
            # cedo num dia que ainda conta como "dia trabalhado" pro
            # salário-base acima) descontam do bruto, não ficam só
            # informativas no holerite. Achado do painel de revisão.
            horas_devidas_valor = arredondar(relatorio.resumo.total_devido_mes * valor_hora)

            # Campos sem regra de cálculo definida nesta primeira versão --
            # gravados em 0.00 até ganharem uma fonte de dado/regra real
            # (ver docstring de Holerite em utils/database.py).
            ajuda_custo = Decimal("0.00")
            adiantamento = Decimal("0.00")
            contribuicao_assistencial = Decimal("0.00")
            vale_refeicao = Decimal("0.00")

            valor_bruto = arredondar(salario_base + horas_extras_valor - horas_devidas_valor)
            if valor_bruto < Decimal("0.00"):
                valor_bruto = Decimal("0.00")
            inss = _calcular_inss(valor_bruto)
            irpf = _calcular_irpf(arredondar(valor_bruto - inss))
            fgts = arredondar(valor_bruto * _ALIQUOTA_FGTS)
            vale_transporte = arredondar(salario_base * _ALIQUOTA_VALE_TRANSPORTE)

            valor_liquido = arredondar(
                valor_bruto + ajuda_custo - inss - irpf - vale_transporte
                - contribuicao_assistencial - adiantamento
            )

            holerite = Holerite(
                funcionario_id=funcionario.id,
                mes=mes,
                ano=ano,
                data_competencia=data_competencia,
                valor_bruto=valor_bruto,
                valor_liquido=valor_liquido,
                salario_base=salario_base,
                inss=inss,
                irpf=irpf,
                fgts=fgts,
                vale_transporte=vale_transporte,
                vale_refeicao=vale_refeicao,
                contribuicao_assistencial=contribuicao_assistencial,
                ajuda_custo=ajuda_custo,
                adiantamento=adiantamento,
                horas_extras_valor=horas_extras_valor,
                horas_trabalhadas=relatorio.resumo.total_trabalhado_mes,
                dias_trabalhados=dias_trabalhados,
                horas_extras=relatorio.resumo.total_extra_mes,
                horas_devidas=relatorio.resumo.total_devido_mes,
            )
            # Achado do painel de revisão: duas chamadas concorrentes de
            # fechar_folha (RH clicando duas vezes, ou dois gerentes ao
            # mesmo tempo) passavam as duas pelo "ja_existe is None" acima e
            # inseriam holerite duplicado -- a UniqueConstraint em
            # utils/database.py::Holerite fecha a brecha de verdade. Usa
            # SAVEPOINT (begin_nested) por funcionário -- se ESTE insert
            # colidir, só ele é descartado; os holerites de outros
            # funcionários já inseridos nesta mesma chamada continuam de pé
            # até o commit final.
            try:
                with session.begin_nested():
                    session.add(holerite)
                    session.flush()
                criados += 1
            except IntegrityError:
                pulados_concorrencia += 1

        try:
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao fechar a folha")

    detalhe = f"Folha de {mes}/{ano} fechada para {criados} funcionário(s)"
    if pulados_concorrencia:
        detalhe += f" ({pulados_concorrencia} já processado(s) por outra solicitação simultânea)"
    criar_log(funcionario_id_solicitante, detalhe)
    return {"detail": detalhe}


def meu_holerite(funcionario_id: int, mes: int, ano: int) -> Holerite:
    with Session(engine) as session:
        return session.exec(
            select(Holerite).where(
                Holerite.funcionario_id == funcionario_id, Holerite.mes == mes, Holerite.ano == ano
            )
        ).first()


def buscar_holerite(funcionario_id: int, mes: int, ano: int) -> Holerite:
    return meu_holerite(funcionario_id, mes, ano)


def assinar_holerite(holerite_id: int, funcionario_id: int) -> Holerite:
    with Session(engine) as session:
        holerite = session.get(Holerite, holerite_id)
        if not holerite:
            raise HTTPException(status_code=404, detail="Holerite não encontrado")
        if holerite.funcionario_id != funcionario_id:
            raise HTTPException(status_code=403, detail="Você só pode assinar o próprio holerite")

        if not holerite.assinado:
            holerite.assinado = True
            holerite.data_assinatura = datetime.now(timezone.utc)
            try:
                session.add(holerite)
                session.commit()
                session.refresh(holerite)
            except Exception:
                session.rollback()
                raise HTTPException(status_code=500, detail="Erro ao assinar holerite")
        return holerite
