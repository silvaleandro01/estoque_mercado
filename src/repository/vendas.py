from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from utils.database import engine, Estoque, Venda, ItemVenda, Compra, Despesa
from utils.money import arredondar
from utils.quantidade import arredondar_quantidade, validar_quantidade_inteira_se_unidade
from utils.timezone import hoje_brasil, limites_do_dia_brasil, limites_dos_ultimos_dias
from utils.erros_banco import tratar_operational_error
from repository.lotes import consumir_fefo, reconciliar_lote_sem_validade
from repository.movimentacoes import registrar_movimentacao
from logs.logs import criar_log
from schemas.schemas import VendaInput


def criar_venda(dados: VendaInput, funcionario_id: int):
    with Session(engine) as session:
        venda = Venda(funcionario_id=funcionario_id)
        session.add(venda)
        session.flush()

        total = Decimal("0.00")
        # Trava os produtos sempre na mesma ordem (código de barras),
        # independente da ordem em que os itens chegaram no carrinho/payload.
        # Sem isso, duas vendas concorrentes com os mesmos produtos em ordens
        # invertidas (venda A trava X depois Y; venda B trava Y depois X)
        # cada uma segura o lock que a outra precisa para continuar — um
        # deadlock clássico do MySQL/InnoDB, reproduzido com 53% de falha
        # (HTTP 500 cru) em teste de carga real com vendas concorrentes.
        # Ordenando por uma chave estável e determinística, toda transação
        # adquire os locks na mesma sequência, o que elimina a espera
        # circular que causa o deadlock.
        itens_ordenados = sorted(dados.itens, key=lambda item: item.codigodebarras)

        try:
            for item in itens_ordenados:
                # with_for_update() trava a linha do produto até o fim da
                # transação (commit/rollback). Isso evita que duas vendas
                # concorrentes leiam o mesmo saldo de estoque "velho" e ambas
                # concluam a venda, o que poderia deixar `quantidade` negativo
                # (ou vender mais itens do que existem fisicamente).
                produto = session.exec(
                    select(Estoque).where(Estoque.codigodebarras == item.codigodebarras).with_for_update()
                ).first()

                if not produto:
                    session.rollback()
                    raise HTTPException(status_code=404, detail=f"Produto {item.codigodebarras} não encontrado")

                # A validação "produto UN só aceita quantidade inteira"
                # existia só no frontend -- ver docstring de
                # validar_quantidade_inteira_se_unidade(). Checa contra a
                # unidade_medida do produto já cadastrado (fonte da verdade),
                # não contra nada que viesse do payload da venda.
                try:
                    validar_quantidade_inteira_se_unidade(item.quantidade, produto.unidade_medida, produto.nomedoproduto)
                except HTTPException:
                    session.rollback()
                    raise

                if produto.quantidade < item.quantidade:
                    session.rollback()
                    raise HTTPException(status_code=400, detail=f"Estoque insuficiente para {produto.nomedoproduto}")

                # FEFO (First Expired, First Out): baixa primeiro do(s)
                # lote(s) que vencem mais cedo. Precisa rodar ANTES de
                # decrementar produto.quantidade -- consumir_fefo usa o
                # saldo AINDA PRÉ-venda para materializar um "lote legado"
                # quando o produto não tem nenhum lote cadastrado (ver
                # docstring de repository.lotes.consumir_fefo).
                try:
                    consumos = consumir_fefo(session, produto.id, item.quantidade, produto.nomedoproduto)
                except HTTPException:
                    session.rollback()
                    raise

                # Histórico de movimentações (Fase 4): uma movimentação
                # VENDA POR LOTE consumido (não uma única linha agregando
                # a venda inteira) -- cada consumo de lote é um evento
                # distinto, espelhando exatamente o que consumir_fefo
                # baixou de cada lote.
                for lote_id, baixa in consumos:
                    registrar_movimentacao(
                        session, produto.id, "VENDA", -baixa, funcionario_id, lote_id=lote_id,
                    )

                produto.quantidade = arredondar_quantidade(produto.quantidade - item.quantidade)
                preco_total = arredondar(produto.preco * item.quantidade)
                total += preco_total

                session.add(ItemVenda(
                    venda_id=venda.id,
                    codigodebarras=item.codigodebarras,
                    quantidade=item.quantidade,
                    preco_unitario=produto.preco,
                    preco_total=preco_total,
                ))

            venda.valor_total = arredondar(total)
            session.add(venda)
            session.commit()
        except OperationalError as exc:
            session.rollback()
            # Defesa em profundidade: a ordenação acima elimina o deadlock
            # entre vendas concorrentes, mas uma transação pode ainda assim
            # colidir com outra parte do sistema que trave os mesmos
            # produtos em ordem diferente (ex.: entrada de estoque). Nesse
            # caso devolvemos um erro claro e recuperável em vez do 500 cru
            # que o MySQL geraria (ver utils/erros_banco.py).
            tratar_operational_error(exc, "Não foi possível processar a venda, tente novamente")

        session.refresh(venda)
        return venda


def vendas_do_dia():
    with Session(engine) as session:
        dia = hoje_brasil()
        inicio_utc, fim_utc = limites_do_dia_brasil(dia)
        vendas = session.exec(
            select(Venda)
            # Venda cancelada não é "vendida" de verdade -- não deveria
            # entrar no total do caixa do dia nem na listagem de onde o
            # próprio cancelamento é disparado (ver cancelar_venda).
            .where(Venda.data >= inicio_utc, Venda.data < fim_utc, Venda.status == "concluida")
            .order_by(Venda.data.desc())
        ).all()
        total = arredondar(sum((v.valor_total for v in vendas), Decimal("0.00")))
        return {
            "data": dia,
            "total_vendido": total,
            "lista": [{"id": v.id, "data": v.data, "valor_total": v.valor_total} for v in vendas],
        }


def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()


def cancelar_venda(venda_id: int, funcionario_id: int):
    """POST /vendas/cancelar/{id} (Fase 8 -- ver docstring de Venda e de
    MovimentacaoEstoque, que já reservava CANCELAMENTO_VENDA no enum para
    quando esta fase chegasse): devolve ao estoque os itens de uma venda e
    marca a venda como cancelada (estado terminal, não é possível cancelar
    de novo nem reverter).

    DEVOLUÇÃO POR LOTE: diferente de `criar_venda` (que sabe exatamente de
    qual lote FEFO cada item saiu, via `consumir_fefo`), não existe hoje
    nenhum vínculo persistido entre uma venda e os lotes que ela consumiu --
    `MovimentacaoEstoque` não tem `venda_id` (ver docstring do modelo). Sem
    esse vínculo, não há como devolver cada item ao lote físico exato de
    onde saiu. A devolução aqui usa o mesmo mecanismo já estabelecido para
    todo ajuste de saldo sem lote físico conhecido (criar_estoque,
    ajustar_inventario, confirmar_pendente): incrementa
    `Estoque.quantidade` e reconcilia o "lote sem validade" (ver docstring
    de `reconciliar_lote_sem_validade`) -- uma escolha razoável para um
    estorno (a mercadoria devolvida volta ao MESMO estoque físico,
    independente de qual lote tinha sido debitado), mas que não preserva a
    validade original de cada unidade devolvida.

    Mesmo padrão de lock/deadlock dos outros pontos de escrita de estoque
    (with_for_update() + tratar_operational_error), e mesma ordenação por
    codigodebarras de `criar_venda` -- duas transações que travam os mesmos
    produtos (uma venda nova, um cancelamento) precisam adquirir os locks
    sempre na mesma ordem para não haver deadlock entre elas.
    """
    with Session(engine) as session:
        venda = session.exec(
            select(Venda).where(Venda.id == venda_id).with_for_update()
        ).first()
        if not venda:
            raise HTTPException(status_code=404, detail="Venda não encontrada")
        if venda.status != "concluida":
            raise HTTPException(status_code=400, detail="Venda já está cancelada")

        itens = session.exec(select(ItemVenda).where(ItemVenda.venda_id == venda_id)).all()
        itens_ordenados = sorted(itens, key=lambda item: item.codigodebarras)

        try:
            for item in itens_ordenados:
                produto = session.exec(
                    select(Estoque).where(Estoque.codigodebarras == item.codigodebarras).with_for_update()
                ).first()
                if not produto:
                    # Produto excluído do estoque depois da venda -- não há
                    # mais pra onde devolver esta linha específica (ver
                    # repository/estoque.py::deletar_estoque). A venda ainda
                    # é cancelada normalmente; só esta devolução de item é
                    # pulada.
                    continue

                produto.quantidade = arredondar_quantidade(produto.quantidade + item.quantidade)
                session.add(produto)

                lote_residual, delta_residual = reconciliar_lote_sem_validade(session, produto.id)
                if delta_residual != 0:
                    registrar_movimentacao(
                        session, produto.id, "CANCELAMENTO_VENDA", delta_residual, funcionario_id,
                        lote_id=lote_residual.id if lote_residual else None,
                    )

            venda.status = "cancelada"
            venda.cancelada_em = datetime.now(timezone.utc)
            venda.cancelada_por_id = funcionario_id
            session.add(venda)
            session.commit()
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível cancelar a venda, tente novamente")
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao cancelar venda")

        session.refresh(venda)

    criar_log(funcionario_id, f"Venda cancelada: #{venda_id}")
    return {"msg": f"Venda #{venda_id} cancelada, estoque devolvido"}


def _stats_do_periodo(session: Session, inicio, fim) -> dict:
    # Venda cancelada não é faturamento real -- mesmo filtro de
    # vendas_do_dia.
    vendas = session.exec(
        select(Venda).where(Venda.data >= inicio, Venda.data < fim, Venda.status == "concluida")
    ).all()
    faturamento = arredondar(sum((v.valor_total for v in vendas), Decimal("0.00")))

    # Só conta como investimento o que já foi efetivamente autorizado --
    # mesmo filtro de status usado em compras_do_dia.
    compras = session.exec(
        select(Compra).where(Compra.status == "autorizada", Compra.data >= inicio, Compra.data < fim)
    ).all()
    investimento = arredondar(sum((c.valor_total for c in compras), Decimal("0.00")))

    despesas_periodo = session.exec(select(Despesa).where(Despesa.data >= inicio, Despesa.data < fim)).all()
    despesas = arredondar(sum((d.valor for d in despesas_periodo), Decimal("0.00")))

    lucro_liquido = arredondar(faturamento - investimento - despesas)

    return {
        "vendas_count": len(vendas),
        "faturamento": faturamento,
        "investimento": investimento,
        "despesas": despesas,
        "lucro_liquido": lucro_liquido,
    }


def dashboard_stats():
    """Agrega vendas, compras autorizadas e despesas em janelas de período
    (diário = dia civil em Brasília; as demais, rolantes a partir de agora --
    ver limites_dos_ultimos_dias) para o Dashboard Executivo."""
    with Session(engine) as session:
        janelas = {
            "diario": limites_do_dia_brasil(),
            "semanal": limites_dos_ultimos_dias(7),
            "mensal": limites_dos_ultimos_dias(30),
            "bimestral": limites_dos_ultimos_dias(60),
            "trimestral": limites_dos_ultimos_dias(90),
            "semestral": limites_dos_ultimos_dias(180),
            "anual": limites_dos_ultimos_dias(365),
        }
        return {
            chave: _stats_do_periodo(session, inicio, fim)
            for chave, (inicio, fim) in janelas.items()
        }
