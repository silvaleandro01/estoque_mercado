"""Lotes e validade (Fase 3).

Ver docstring de `utils.database.Lote` para a decisão de arquitetura
completa: `Estoque.quantidade` é a fonte da verdade do saldo total (travada
com `with_for_update()`, mesma trava já validada nas Fases 1/2); `Lote` é só
um detalhamento de como esse saldo está repartido por validade. Este módulo
garante, em todo ponto que altera `Estoque.quantidade`, que a invariante

    soma(Lote.quantidade de um produto) == Estoque.quantidade desse produto

nunca fica divergente -- nem por uma janela de tempo, já que os ajustes
aqui acontecem na MESMA sessão/transação de quem chama (repository/estoque.py
e repository/vendas.py nunca fazem commit entre o ajuste de `Estoque.
quantidade` e o ajuste correspondente em `Lote`).

Produtos cadastrados antes desta fase (ou cuja quantidade muda por um
caminho que não informa lote/validade -- cadastro manual, incremento manual
via /estoque/inserir, edição direta via PUT /estoque/atualizar) não travam:
o ajuste cai num "lote sem validade conhecida" (`validade IS NULL`), criado
sob demanda. Esse é o "lote legado". Na ordem de consumo (FEFO, ver
`consumir_fefo`), lotes com validade definida vêm sempre antes (ordenados
pela validade mais próxima primeiro); o(s) lote(s) sem validade só entram
por último (por data de entrada, mais antigo primeiro) -- assim um produto
com validade real cadastrada nunca fica "escondido atrás" de um lote legado
de validade desconhecida, que é justamente o que motiva esta fase (evitar
desperdício por vencimento).
"""

from decimal import Decimal
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from utils.database import Lote, Estoque, engine
from utils.quantidade import arredondar_quantidade
from utils.timezone import hoje_brasil

CODIGO_LOTE_LEGADO = "LEGADO"


def _lote_sem_validade(session: Session, estoque_id: int) -> Optional[Lote]:
    """Busca (travando) o lote "sem validade conhecida" do produto, se
    existir. Não cria -- quem decide criar é `reconciliar_lote_sem_validade`."""
    return session.exec(
        select(Lote)
        .where(Lote.estoque_id == estoque_id, Lote.validade.is_(None))
        .with_for_update()
    ).first()


def reconciliar_lote_sem_validade(session: Session, estoque_id: int) -> None:
    """
    Reconcilia a quantidade do lote "sem validade" (legado) do produto para
    que a invariante

        soma(Lote.quantidade de um produto) == Estoque.quantidade desse produto

    nunca divirja. Substitui a antiga `ajustar_lote_sem_validade`, que
    recebia um `delta` e somava/subtraía nesse lote assumindo (de forma
    frágil) que ele já refletia corretamente o saldo antes da operação --
    suposição falsa em pelo menos 3 cenários reais, confirmados num painel
    de revisão com MySQL real:

      A) saldo todo em lote(s) COM validade real, PUT reduz
         Estoque.quantidade -- a versão "delta" não achava nenhum lote sem
         validade e não fazia nada, deixando soma(Lote) > Estoque.quantidade;
      B) produto legado (saldo > 0, zero lotes) tocado pela primeira vez
         por uma operação que não é venda (incremento manual, PUT,
         confirmação de pendente) -- a versão "delta" só registrava o
         delta daquela operação, ignorando o saldo pré-existente;
      C) produto legado recebendo uma NOVA entrada com lote rastreado
         (ex.: confirmação de compra pendente) -- a lista de lotes deixava
         de estar vazia, então a materialização do lote sem validade (que
         só rodava em `consumir_fefo` quando não havia NENHUM lote) nunca
         mais disparava, perdendo o saldo antigo para sempre e causando
         rejeição falsa de "estoque insuficiente" numa venda que deveria
         passar.

    Em vez de aplicar um delta, esta função CALCULA do zero, a cada
    chamada:

        residual = Estoque.quantidade - soma(Lote.quantidade dos lotes
                                             COM validade real)

    e faz o lote "sem validade" refletir EXATAMENTE esse residual --
    criando a linha se ainda não existir (quando `residual != 0`) ou
    atualizando a já existente, em qualquer direção -- inclusive para um
    valor NEGATIVO: se os lotes datados somarem mais do que o total
    declarado em `Estoque.quantidade` (cenário A, depois de um PUT que
    reduz o total sem dizer de qual lote tirar), um residual negativo é a
    única forma de a soma aritmética continuar batendo com o total. Esse
    "lote" é uma linha de correção/placeholder, não um lote físico -- fica
    de fora do consumo FEFO porque `consumir_fefo` só seleciona
    `Lote.quantidade > 0`, e se autocorrige (pode voltar a ficar positivo
    ou zerar) na próxima operação que recalcule o residual deste produto.

    PRÉ-CONDIÇÕES (responsabilidade de quem chama, ver docstring do
    módulo): `Estoque.quantidade` já precisa refletir o valor FINAL da
    operação, qualquer lote com validade real desta operação já precisa
    ter sido criado/ajustado, e a linha de `Estoque` já precisa estar
    travada (`with_for_update()`) na MESMA transação -- senão duas
    transações concorrentes podem calcular residuais a partir de saldos
    desatualizados (o `session.get()` abaixo não pede lock por conta
    própria: ele só reaproveita, dentro da mesma sessão/transação, o lock
    que o chamador já adquiriu -- mesmo raciocínio já usado em
    `consumir_fefo`).
    """
    produto = session.get(Estoque, estoque_id)
    quantidade_total = produto.quantidade if produto else Decimal("0.000")

    lotes_datados = session.exec(
        select(Lote)
        .where(Lote.estoque_id == estoque_id, Lote.validade.is_not(None))
        .with_for_update()
    ).all()
    soma_datados = sum((l.quantidade for l in lotes_datados), Decimal("0.000"))

    residual = arredondar_quantidade(quantidade_total - soma_datados)

    lote = _lote_sem_validade(session, estoque_id)
    if lote is None:
        if residual == 0:
            return
        lote = Lote(
            estoque_id=estoque_id,
            codigo_lote=CODIGO_LOTE_LEGADO,
            quantidade=Decimal("0.000"),
            validade=None,
            data_entrada=datetime.now(timezone.utc),
        )
        session.add(lote)
        session.flush()

    lote.quantidade = residual
    session.add(lote)


def criar_lote(session: Session, estoque_id: int, codigo_lote: str, quantidade: Decimal,
               validade: Optional[date], data_entrada: Optional[datetime] = None) -> Lote:
    """Cria um lote novo rastreado (entrada de estoque com lote/validade
    conhecidos -- ex.: confirmação de compra pendente). `quantidade` já deve
    vir validada (> 0) pelo chamador; aqui só arredonda para 3 casas."""
    lote = Lote(
        estoque_id=estoque_id,
        codigo_lote=codigo_lote,
        quantidade=arredondar_quantidade(quantidade),
        validade=validade,
        data_entrada=data_entrada or datetime.now(timezone.utc),
    )
    session.add(lote)
    session.flush()
    return lote


def consumir_fefo(session: Session, estoque_id: int, quantidade: Decimal, nome_produto: str) -> None:
    """
    Baixa `quantidade` dos lotes do produto, sempre do que vence mais cedo
    primeiro (First Expired, First Out) -- se um lote não bastar sozinho,
    continua baixando do(s) próximo(s) por ordem de validade até completar.

    IMPORTANTE (ordem de chamada): deve ser chamada DEPOIS de travar
    (`with_for_update()`) e confirmar que `Estoque.quantidade >= quantidade`,
    mas ANTES de decrementar `Estoque.quantidade` -- a materialização do
    "lote legado" (quando o produto ainda não tem nenhum lote) usa o saldo
    atual de `Estoque.quantidade`, que neste ponto ainda precisa ser o
    saldo PRÉ-venda (ver repository/vendas.py).

    Se a soma dos lotes não bastar para cobrir `quantidade` (só deveria
    acontecer se a soma dos lotes já estivesse divergente do saldo total --
    nunca em operação normal, já que a invariante é mantida em todo outro
    ponto de escrita), levanta 400 com a mesma mensagem de "estoque
    insuficiente" usada no restante do sistema, em vez de deixar lote com
    quantidade negativa.
    """
    lotes = session.exec(
        select(Lote)
        .where(Lote.estoque_id == estoque_id, Lote.quantidade > 0)
        .with_for_update()
    ).all()

    if not lotes:
        # Produto sem NENHUM lote ainda (estoque legado, nunca tocado por
        # esta fase) -- materializa um lote "sem validade" cobrindo o saldo
        # atual antes de consumir, para o produto entrar no fluxo de lotes
        # a partir de agora sem travar a venda.
        produto = session.get(Estoque, estoque_id)
        saldo_atual = produto.quantidade if produto else Decimal("0.000")
        if saldo_atual > 0:
            reconciliar_lote_sem_validade(session, estoque_id)
            lotes = session.exec(
                select(Lote)
                .where(Lote.estoque_id == estoque_id, Lote.quantidade > 0)
                .with_for_update()
            ).all()

    # FEFO: validade definida primeiro (mais próxima primeiro), lote(s) sem
    # validade por último (ver docstring do módulo) -- data_entrada e id
    # como desempate estável e determinístico.
    lotes_ordenados = sorted(
        lotes,
        key=lambda l: (l.validade is None, l.validade or date.max, l.data_entrada, l.id),
    )

    restante = arredondar_quantidade(quantidade)
    for lote in lotes_ordenados:
        if restante <= 0:
            break
        baixa = min(lote.quantidade, restante)
        lote.quantidade = arredondar_quantidade(lote.quantidade - baixa)
        restante = arredondar_quantidade(restante - baixa)
        session.add(lote)

    if restante > 0:
        raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {nome_produto}")


def listar_alerta_vencimento(dias: int = 7):
    """
    Lista lotes vencendo nos próximos `dias` dias e, separadamente, os já
    vencidos. Só considera lotes com validade CONHECIDA (`validade IS NOT
    NULL`) e saldo positivo -- lote "sem validade" (legado) não entra em
    nenhuma das duas listas, porque não há como saber se está vencido ou
    não (ver docstring do módulo).

    Usa `hoje_brasil()` (não `date.today()`) pelo mesmo motivo já
    documentado em utils/timezone.py: o servidor pode rodar em UTC, e perto
    da meia-noite em Brasília isso mudaria o "hoje" usado no corte.
    """
    with Session(engine) as session:
        hoje = hoje_brasil()
        limite = hoje + timedelta(days=dias)

        linhas = session.exec(
            select(Lote, Estoque)
            .join(Estoque, Lote.estoque_id == Estoque.id)
            .where(Lote.validade.is_not(None), Lote.quantidade > 0)
            .order_by(Lote.validade)
        ).all()

        vencendo, vencidos = [], []
        for lote, produto in linhas:
            dias_restantes = (lote.validade - hoje).days
            item = {
                "lote_id": lote.id,
                "estoque_id": produto.id,
                "nomedoproduto": produto.nomedoproduto,
                "codigodebarras": produto.codigodebarras,
                "codigo_lote": lote.codigo_lote,
                "quantidade": lote.quantidade,
                "validade": lote.validade,
                "dias_restantes": dias_restantes,
            }
            if lote.validade < hoje:
                vencidos.append(item)
            elif lote.validade <= limite:
                vencendo.append(item)

        return {"dias": dias, "vencendo": vencendo, "vencidos": vencidos}
