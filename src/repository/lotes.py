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
    existir. Não cria -- quem decide criar é `ajustar_lote_sem_validade`."""
    return session.exec(
        select(Lote)
        .where(Lote.estoque_id == estoque_id, Lote.validade.is_(None))
        .with_for_update()
    ).first()


def ajustar_lote_sem_validade(session: Session, estoque_id: int, delta: Decimal) -> None:
    """
    Soma (ou subtrai, se `delta` negativo) `delta` no lote "sem validade"
    do produto, criando esse lote se ainda não existir (só quando
    `delta > 0` -- não faz sentido criar um lote já para subtrair dele).
    Mantém a invariante soma(Lote.quantidade) == Estoque.quantidade quando
    a quantidade total muda por um caminho que não informa lote/validade
    (ver docstring do módulo).

    Satura em zero: um delta negativo maior que o saldo do lote sem
    validade não deixa esse lote com quantidade negativa -- nesse caso a
    edição manual upstream já estava reduzindo o estoque mais do que o
    lote legado consegue "explicar", e zerar o lote é o melhor que dá para
    fazer aqui sem inventar validade/proveniência que não existe.
    """
    delta = arredondar_quantidade(delta)
    if delta == 0:
        return

    lote = _lote_sem_validade(session, estoque_id)
    if lote is None:
        if delta <= 0:
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

    nova_quantidade = lote.quantidade + delta
    lote.quantidade = arredondar_quantidade(nova_quantidade if nova_quantidade > 0 else Decimal("0.000"))
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
            ajustar_lote_sem_validade(session, estoque_id, saldo_atual)
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
