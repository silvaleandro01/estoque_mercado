from datetime import date, datetime, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from utils.database import Ponto, Salario, Funcionario, engine
from utils.money import arredondar
from logs.logs import criar_log
from schemas.schemas import PontoRelatorioOut, PontoResumoOut, PontoDiaOut, PontoGeralItemOut

# Jornada padrão: 8h/dia (CLT, 44h/semana -- mesmo divisor usado em
# repository/funcionarios.py::definir_salario para valor_hora, 220h/mês).
# Acima disso vira hora extra (50%); abaixo vira hora devida.
JORNADA_PADRAO_HORAS = Decimal("8.00")

ORDEM_MARCOS = ("entrada", "saida_almoco", "retorno_almoco", "saida")
_ROTULO_MARCO = {
    "entrada": "Entrada",
    "saida_almoco": "Saída para almoço",
    "retorno_almoco": "Retorno do almoço",
    "saida": "Saída",
}


def _proximo_marco(ponto: Ponto):
    for marco in ORDEM_MARCOS:
        if getattr(ponto, marco) is None:
            return marco
    return None


def _aware(momento):
    """SQLite não preserva timezone em colunas datetime -- ao reler do
    banco, um valor gravado com tzinfo=UTC volta naive (mesmo problema já
    tratado em repository/funcionarios.py::_esta_bloqueado). Normaliza para
    UTC antes de qualquer subtração entre momentos."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


def _calcular_horas_dia(ponto: Ponto) -> None:
    """Preenche horas_trabalhadas/horas_extras/horas_devidas de `ponto`.

    Só roda quando `saida` já foi batida -- um dia ainda em aberto fica com
    os três zerados (valor default do modelo). Desconta o intervalo de
    almoço (saida_almoco -> retorno_almoco) do total, quando os dois marcos
    de almoço foram batidos.
    """
    if not (ponto.entrada and ponto.saida):
        return
    total = _aware(ponto.saida) - _aware(ponto.entrada)
    if ponto.saida_almoco and ponto.retorno_almoco:
        total -= (_aware(ponto.retorno_almoco) - _aware(ponto.saida_almoco))
    horas = arredondar(Decimal(total.total_seconds()) / Decimal(3600))
    if horas < 0:
        horas = Decimal("0.00")
    ponto.horas_trabalhadas = horas
    if horas > JORNADA_PADRAO_HORAS:
        ponto.horas_extras = arredondar(horas - JORNADA_PADRAO_HORAS)
        ponto.horas_devidas = Decimal("0.00")
    else:
        ponto.horas_extras = Decimal("0.00")
        ponto.horas_devidas = arredondar(JORNADA_PADRAO_HORAS - horas)


def _intervalo_mes(mes: int, ano: int):
    inicio = date(ano, mes, 1)
    fim = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return inicio, fim


def _valor_hora(session: Session, funcionario_id: int) -> Decimal:
    salario = session.exec(select(Salario).where(Salario.funcionario_id == funcionario_id)).first()
    return salario.valor_hora if salario else Decimal("0.00")


def bater_ponto(funcionario_id: int) -> dict:
    hoje = date.today()
    with Session(engine) as session:
        ponto = session.exec(
            select(Ponto).where(Ponto.funcionario_id == funcionario_id, Ponto.data == hoje)
        ).first()
        # Achado do painel de revisão: sem lock, duas requisições quase
        # simultâneas (duplo clique) podiam ver "não existe" as duas e criar
        # duas linhas de Ponto pro mesmo dia. A UniqueConstraint(funcionario_id,
        # data) em utils/database.py::Ponto fecha essa brecha de verdade --
        # aqui só precisamos converter o IntegrityError dela num 409 claro
        # em vez de deixar escapar cru como 500.
        eh_insercao_nova = ponto is None
        if not ponto:
            ponto = Ponto(funcionario_id=funcionario_id, data=hoje)

        marco = _proximo_marco(ponto)
        if marco is None:
            raise HTTPException(status_code=400, detail="Todos os marcos de ponto de hoje já foram registrados")

        agora = datetime.now(timezone.utc)
        setattr(ponto, marco, agora)
        if marco == "saida":
            _calcular_horas_dia(ponto)

        try:
            session.add(ponto)
            session.commit()
        except IntegrityError:
            session.rollback()
            if eh_insercao_nova:
                raise HTTPException(
                    status_code=409,
                    detail="Ponto já registrado por outra requisição -- atualize a página e confira",
                )
            raise HTTPException(status_code=500, detail="Erro ao registrar ponto")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao registrar ponto")

    criar_log(funcionario_id, f"Ponto registrado: {marco} às {agora.strftime('%H:%M')}")
    return {"detail": f"Ponto registrado -- {_ROTULO_MARCO[marco]} às {agora.strftime('%H:%M')}"}


def status_hoje(funcionario_id: int) -> Ponto:
    hoje = date.today()
    with Session(engine) as session:
        ponto = session.exec(
            select(Ponto).where(Ponto.funcionario_id == funcionario_id, Ponto.data == hoje)
        ).first()
        return ponto or Ponto(funcionario_id=funcionario_id, data=hoje)


def montar_relatorio(session: Session, funcionario: Funcionario, mes: int, ano: int) -> PontoRelatorioOut:
    """Núcleo de relatorio_funcionario, recebendo uma `session` já aberta --
    usado tanto pela função pública abaixo (que abre a sua própria) quanto
    por repository/folha.py::fechar_folha, que chama isto de DENTRO de uma
    sessão já aberta (abrir uma segunda Session aqui, aninhada sobre a
    mesma conexão, corrompia a transação externa em SQLite -- reproduzido
    em teste: o holerite do primeiro funcionário do loop sumia, gravado com
    o funcionario_id do próximo). Sem underscore de propósito -- é parte da
    API pública entre módulos (mesma convenção de reconciliar_lote_sem_validade/
    criar_lote/registrar_movimentacao em repository/lotes.py e
    repository/movimentacoes.py: função cross-module que recebe uma session
    já aberta é pública, nunca prefixada). `funcionario` precisa já vir
    validado como não-None -- quem chama é responsável pelo 404, esta função
    não valida de novo."""
    inicio, fim = _intervalo_mes(mes, ano)
    valor_hora = _valor_hora(session, funcionario.id)
    pontos = session.exec(
        select(Ponto)
        .where(Ponto.funcionario_id == funcionario.id, Ponto.data >= inicio, Ponto.data < fim)
        .order_by(Ponto.data)
    ).all()

    dias = []
    total_trabalhado = Decimal("0.00")
    total_extra = Decimal("0.00")
    total_devido = Decimal("0.00")
    total_a_receber = Decimal("0.00")
    for p in pontos:
        # horas_trabalhadas JÁ inclui as horas extras (pagas à parte
        # abaixo) -- aqui só soma o adicional de 50% sobre elas, não o
        # valor_hora inteiro de novo (senão a hora extra seria paga a
        # 2.5x, não a 1.5x).
        valor_dia = arredondar(
            p.horas_trabalhadas * valor_hora + p.horas_extras * valor_hora * Decimal("0.5")
        )
        dias.append(
            PontoDiaOut(
                data=p.data,
                entrada=p.entrada,
                saida_almoco=p.saida_almoco,
                retorno_almoco=p.retorno_almoco,
                saida=p.saida,
                horas_extras=p.horas_extras,
                horas_devidas=p.horas_devidas,
                valor_monetario=valor_dia,
            )
        )
        total_trabalhado += p.horas_trabalhadas
        total_extra += p.horas_extras
        total_devido += p.horas_devidas
        total_a_receber += valor_dia

    return PontoRelatorioOut(
        funcionario=f"{funcionario.nome} {funcionario.sobrenome}",
        resumo=PontoResumoOut(
            total_trabalhado_mes=arredondar(total_trabalhado),
            total_extra_mes=arredondar(total_extra),
            total_devido_mes=arredondar(total_devido),
            saldo_mensal=arredondar(total_extra - total_devido),
            total_a_receber=arredondar(total_a_receber),
        ),
        pontos=dias,
    )


def relatorio_funcionario(funcionario_id: int, mes: int, ano: int) -> PontoRelatorioOut:
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")
        return montar_relatorio(session, funcionario, mes, ano)


def relatorio_geral(mes: int, ano: int) -> list:
    inicio, fim = _intervalo_mes(mes, ano)
    with Session(engine) as session:
        pontos = session.exec(
            select(Ponto).where(Ponto.data >= inicio, Ponto.data < fim).order_by(Ponto.data)
        ).all()
        resultado = []
        for p in pontos:
            funcionario = session.get(Funcionario, p.funcionario_id)
            resultado.append(
                PontoGeralItemOut(
                    data=p.data,
                    funcionario=f"{funcionario.nome} {funcionario.sobrenome}" if funcionario else "?",
                    entrada=p.entrada,
                    saida=p.saida,
                    trabalhadas=p.horas_trabalhadas,
                    extras=p.horas_extras,
                    devidas=p.horas_devidas,
                )
            )
        return resultado
