from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from utils.database import engine, Estoque, Venda, ItemVenda
from utils.money import arredondar
from utils.quantidade import arredondar_quantidade, validar_quantidade_inteira_se_unidade
from utils.timezone import hoje_brasil, limites_do_dia_brasil
from repository.lotes import consumir_fefo
from schemas.schemas import VendaInput

# Código de erro do MySQL/InnoDB para "Deadlock found when trying to get
# lock; try restarting transaction".
MYSQL_ERRO_DEADLOCK = 1213


def _e_deadlock_mysql(exc: OperationalError) -> bool:
    """
    Identifica se um OperationalError do SQLAlchemy é o deadlock do MySQL
    (código 1213), e não outro erro operacional qualquer (perda de conexão,
    timeout, etc.) que não deveria virar um 409 "tente de novo".
    """
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return bool(args) and args[0] == MYSQL_ERRO_DEADLOCK


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
                    consumir_fefo(session, produto.id, item.quantidade, produto.nomedoproduto)
                except HTTPException:
                    session.rollback()
                    raise

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
            if _e_deadlock_mysql(exc):
                # Defesa em profundidade: a ordenação acima elimina o
                # deadlock entre vendas concorrentes, mas uma transação pode
                # ainda assim colidir com outra parte do sistema que trave os
                # mesmos produtos em ordem diferente (ex.: entrada de
                # estoque). Nesse caso devolvemos um erro claro e recuperável
                # em vez do 500 cru que o MySQL geraria.
                raise HTTPException(
                    status_code=409,
                    detail="Não foi possível processar a venda, tente novamente",
                )
            raise

        session.refresh(venda)
        return venda


def vendas_do_dia():
    with Session(engine) as session:
        dia = hoje_brasil()
        inicio_utc, fim_utc = limites_do_dia_brasil(dia)
        vendas = session.exec(
            select(Venda).where(Venda.data >= inicio_utc, Venda.data < fim_utc)
        ).all()
        total = arredondar(sum((v.valor_total for v in vendas), Decimal("0.00")))
        return {"data": dia, "total_vendido": total}


def listar_vendas():
    with Session(engine) as session:
        return session.exec(select(Venda)).all()
