from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select, delete

from utils.database import Estoque, Compra, ItemCompra, Fornecedor, Lote, engine
from utils.money import arredondar
from utils.quantidade import arredondar_quantidade, validar_quantidade_inteira_se_unidade
from utils.erros_banco import tratar_operational_error
from logs.logs import criar_log
from schemas.schemas import EstoqueCreate, EstoqueUpdate, ConfirmarPendenteInput
from repository.lotes import reconciliar_lote_sem_validade, criar_lote


def _validar_fornecedor(session: Session, fornecedor_id):
    """Garante um erro 404 claro (em vez de um erro cru do banco/FK) quando
    o `fornecedor_id` informado no cadastro de produto não existe."""
    if fornecedor_id is not None and not session.get(Fornecedor, fornecedor_id):
        raise HTTPException(status_code=404, detail="Fornecedor não encontrado")


def criar_estoque(dados: EstoqueCreate, funcionario_id: int):
    with Session(engine) as session:
        # _validar_fornecedor roda só mais abaixo, no caminho de produto
        # novo -- não aqui incondicionalmente. No caminho de incremento
        # (produto já existente, logo abaixo) dados.fornecedor_id do
        # payload nem é usado (o fornecedor já cadastrado do produto não
        # muda por incremento), então validar um fornecedor_id que será
        # ignorado só bloquearia incrementos de estoque sem necessidade.

        # with_for_update(): mesma trava usada em repository/vendas.py.
        # Sem ela, duas entradas de estoque simultâneas para o mesmo produto
        # (ex.: dois lançamentos manuais, ou um lançamento concorrendo com a
        # confirmação de um pendente de compra) podem ambas ler a mesma
        # `quantidade` "antiga", cada uma somar o próprio incremento em cima
        # dela e uma das duas sobrescrever o resultado da outra ao salvar --
        # um incremento inteiro perdido (lost update).
        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras).with_for_update()
        ).first()

        if produto_existente:
            # Validação "UN só aceita quantidade inteira" contra a
            # unidade_medida já cadastrada do produto -- o incremento ignora
            # qualquer dados.unidade_medida que tenha vindo no payload, a
            # unidade de um produto já existente não muda por incremento.
            validar_quantidade_inteira_se_unidade(dados.quantidade, produto_existente.unidade_medida, produto_existente.nomedoproduto)
            produto_existente.quantidade = arredondar_quantidade(produto_existente.quantidade + dados.quantidade)
            produto_existente.funcionario_id = funcionario_id
            # Incremento manual (sem lote/validade informados): reconcilia
            # o lote "sem validade" do produto a partir do saldo final já
            # atualizado acima (não um delta isolado -- ver docstring de
            # reconciliar_lote_sem_validade sobre por que um delta isolado
            # é frágil quando o produto já tinha saldo que não estava
            # registrado em nenhum lote). Mantém a invariante soma(Lote.
            # quantidade) == Estoque.quantidade (ver repository/lotes.py).
            reconciliar_lote_sem_validade(session, produto_existente.id)
            try:
                session.commit()
                session.refresh(produto_existente)
                criar_log(funcionario_id, f"Incremento de estoque: {produto_existente.nomedoproduto}")
                return produto_existente
            except OperationalError as exc:
                session.rollback()
                # with_for_update() acima pode colidir com outra transação
                # que trave os mesmos produtos em ordem diferente (ex.:
                # venda, outra entrada de estoque) -- ver utils/erros_banco.py.
                tratar_operational_error(exc, "Não foi possível atualizar o estoque, tente novamente")
            except Exception:
                session.rollback()
                raise HTTPException(status_code=500, detail="Erro ao atualizar estoque")

        # Produto novo (cadastro): aqui sim dados.fornecedor_id é usado de
        # verdade (vira o fornecedor do produto), então validamos que ele
        # existe. A unidade de medida também vem do próprio payload, já que
        # ainda não existe nenhum produto cadastrado com esse código de
        # barras para servir de fonte da verdade.
        _validar_fornecedor(session, dados.fornecedor_id)
        validar_quantidade_inteira_se_unidade(dados.quantidade, dados.unidade_medida, dados.nomedoproduto)

        estoque = Estoque(
            titulo=dados.titulo,
            nomedoproduto=dados.nomedoproduto,
            quantidade=arredondar_quantidade(dados.quantidade),
            unidade_medida=dados.unidade_medida,
            estoque_minimo=arredondar_quantidade(dados.estoque_minimo),
            preco=arredondar(dados.preco),
            preco_custo=arredondar(dados.preco_custo) if dados.preco_custo is not None else Decimal("0.00"),
            codigodebarras=dados.codigodebarras,
            categoria=dados.categoria,
            funcionario_id=funcionario_id,
            fornecedor_id=dados.fornecedor_id,
        )
        try:
            session.add(estoque)
            session.flush()
            # Cadastro novo com quantidade inicial (sem lote/validade
            # informados nesta tela) -- mesma lógica do incremento acima,
            # reconcilia o lote "sem validade" para manter a invariante.
            # reconciliar_lote_sem_validade já é um no-op quando a
            # quantidade inicial é 0 (residual fica 0), então chama
            # incondicionalmente.
            reconciliar_lote_sem_validade(session, estoque.id)
            session.commit()
            session.refresh(estoque)
            criar_log(funcionario_id, f"Inclusão de produto: {estoque.nomedoproduto}")
            return estoque
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível criar o produto, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar produto")


def mostrar_produtos():
    with Session(engine) as session:
        return session.exec(select(Estoque)).all()


def buscar_estoque(estoque_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)
        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")
        return estoque


def atualizar_estoque(estoque_id: int, dados: EstoqueUpdate, funcionario_id: int):
    with Session(engine) as session:
        # with_for_update(): mesma trava usada em criar_estoque/
        # confirmar_pendente/criar_venda. Sem ela, duas edições concorrentes
        # (ou uma edição concorrendo com qualquer outra entrada de estoque
        # do mesmo produto) podiam ler a mesma `quantidade` "antiga" e uma
        # sobrescrever o resultado da outra ao salvar (lost update) --
        # pré-existente antes desta fase, mas que agora alimenta direto
        # reconciliar_lote_sem_validade, amplificando o lost update de
        # Estoque.quantidade para uma divergência permanente também em
        # Lote.quantidade (confirmado: 15/15 rodadas de PUT concorrente
        # real contra MySQL quebraram a invariante, sem nenhuma exceção
        # reportada).
        estoque = session.exec(
            select(Estoque).where(Estoque.id == estoque_id).with_for_update()
        ).first()
        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")

        _validar_fornecedor(session, dados.fornecedor_id)

        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras)
        ).first()
        if produto_existente and produto_existente.id != estoque.id:
            raise HTTPException(status_code=400, detail="Código de barras já cadastrado em outro produto")

        # Atualização: a unidade de medida em si também vem do payload (o
        # formulário de edição permite trocar UN/KG/L do produto), então
        # valida contra o valor que o próprio PUT está definindo.
        validar_quantidade_inteira_se_unidade(dados.quantidade, dados.unidade_medida, dados.nomedoproduto)

        estoque.titulo = dados.titulo
        estoque.nomedoproduto = dados.nomedoproduto
        estoque.quantidade = arredondar_quantidade(dados.quantidade)
        estoque.unidade_medida = dados.unidade_medida
        estoque.estoque_minimo = arredondar_quantidade(dados.estoque_minimo)
        estoque.preco = arredondar(dados.preco)
        estoque.codigodebarras = dados.codigodebarras
        estoque.categoria = dados.categoria
        estoque.funcionario_id = funcionario_id
        estoque.fornecedor_id = dados.fornecedor_id

        # PUT sobrescreve a quantidade total (não é um delta como o
        # incremento de criar_estoque) -- reconciliar_lote_sem_validade
        # recalcula o residual do zero a partir do saldo final já
        # atribuído acima, então funciona igual nos dois casos (não
        # precisa calcular a diferença entre o valor novo e o antigo).
        reconciliar_lote_sem_validade(session, estoque.id)

        try:
            session.commit()
            session.refresh(estoque)
            criar_log(funcionario_id, f"Atualização de produto: {estoque.nomedoproduto}")
            return estoque
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível atualizar o estoque, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar estoque")


def deletar_estoque(estoque_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)
        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")
        try:
            # Lote é um detalhamento do saldo deste produto (não um
            # histórico independente, diferente de ItemVenda/ItemCompra) --
            # ao excluir o produto, os lotes dele deixam de fazer sentido.
            # Excluídos aqui, na mesma transação, para não violar a FK
            # (lote.estoque_id -> estoque.id) nem deixar lote órfão.
            #
            # DELETE explícito por query (em vez de carregar cada Lote com
            # session.exec(select(...)) e marcar para exclusão um a um com
            # session.delete()), seguido de um flush ANTES de deletar
            # Estoque: sem isso, o SQLAlchemy decide por conta própria a
            # ordem do flush (não há Relationship() do SQLModel ligando
            # Lote<->Estoque neste projeto, só a FK crua) e podia emitir
            # DELETE FROM estoque ANTES de DELETE FROM lote, batendo na FK
            # e virando um IntegrityError (1451) cru -- reproduzido ao vivo
            # contra MySQL real para TODO produto que já tivesse qualquer
            # lote. O DELETE direto garante a ordem manualmente, sem
            # depender do unit-of-work adivinhar, e sem introduzir
            # Relationship()/cascade -- padrão que o resto do schema deste
            # projeto não usa (só FK crua em todo lugar).
            session.exec(delete(Lote).where(Lote.estoque_id == estoque_id))
            session.flush()
            session.delete(estoque)
            session.commit()
            return {"msg": "Estoque deletado com sucesso"}
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao deletar estoque")


def listar_pendentes():
    with Session(engine) as session:
        itens = session.exec(
            select(ItemCompra, Compra)
            .join(Compra, ItemCompra.compra_id == Compra.id)
            .where(Compra.status == "autorizada", ItemCompra.lancado_em.is_(None))
        ).all()
        return [
            {
                "id": item.id,
                "compra_id": compra.id,
                "data_entrada": compra.data_autorizacao,
                "nomedoproduto": item.nomedoproduto,
                "codigodebarras": item.codigodebarras,
                "quantidade": item.quantidade,
                "preco_custo": item.preco_custo_unitario,
                "preco_venda": item.preco_venda,
            }
            for item, compra in itens
        ]


def confirmar_pendente(item_id: int, dados: ConfirmarPendenteInput, funcionario_id: int):
    with Session(engine) as session:
        item = session.get(ItemCompra, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item pendente não encontrado")
        if item.lancado_em is not None:
            raise HTTPException(status_code=400, detail="Item já foi lançado no estoque")

        # Mesma trava de criar_estoque(): evita lost update quando a
        # confirmação de um pendente de compra concorre com outra entrada de
        # estoque para o mesmo produto.
        produto_existente = session.exec(
            select(Estoque).where(Estoque.codigodebarras == dados.codigodebarras).with_for_update()
        ).first()

        if produto_existente:
            produto_existente.quantidade = arredondar_quantidade(produto_existente.quantidade + item.quantidade)
            produto_existente.preco_custo = arredondar(item.preco_custo_unitario)
            produto_existente.funcionario_id = funcionario_id
            session.add(produto_existente)
            # Lote e validade (Fase 3): a confirmação de pendente agora
            # sempre informa lote/validade -- diferente do incremento
            # manual via /estoque/inserir, aqui cria um lote RASTREADO de
            # verdade (não cai no lote "sem validade"), já que o
            # lote/validade reais vieram do formulário de confirmação.
            criar_lote(session, produto_existente.id, dados.codigo_lote, item.quantidade, dados.validade)
            # Reconcilia o lote "sem validade" do produto: se o produto já
            # tinha saldo pré-existente que não estava em NENHUM lote
            # (produto legado, cadastrado antes desta fase, ou nunca
            # tocado por ela), essa é a hora de materializá-lo -- senão
            # essas unidades ficam fora do rastreamento por lote para
            # sempre, já que a lista de lotes do produto deixa de estar
            # vazia a partir daqui (ver docstring de
            # reconciliar_lote_sem_validade, cenário C).
            reconciliar_lote_sem_validade(session, produto_existente.id)
            nome_produto = produto_existente.nomedoproduto
        else:
            # Produto novo (não existia ainda com esse código de barras):
            # herda o fornecedor do próprio pedido de compra que o originou
            # (quando o pedido tem um fornecedor definido) -- afinal, foi
            # dele que este produto veio. unidade_medida/estoque_minimo não
            # dá pra deduzir da compra, então vêm do formulário de
            # confirmação (ConfirmarPendenteInput).
            compra = session.get(Compra, item.compra_id)
            novo = Estoque(
                nomedoproduto=dados.nomedoproduto,
                quantidade=item.quantidade,
                unidade_medida=dados.unidade_medida,
                estoque_minimo=arredondar_quantidade(dados.estoque_minimo),
                preco=arredondar(dados.preco_venda),
                preco_custo=arredondar(item.preco_custo_unitario),
                codigodebarras=dados.codigodebarras,
                categoria=dados.categoria,
                funcionario_id=funcionario_id,
                fornecedor_id=compra.fornecedor_id if compra else None,
            )
            session.add(novo)
            session.flush()  # para ter novo.id antes de criar o lote abaixo
            criar_lote(session, novo.id, dados.codigo_lote, item.quantidade, dados.validade)
            # Produto novo: residual esperado é 0 (toda a quantidade já
            # está no lote recém-criado acima), mas chama mesmo assim por
            # consistência/defesa em profundidade -- é um no-op barato
            # quando o residual já é 0.
            reconciliar_lote_sem_validade(session, novo.id)
            nome_produto = novo.nomedoproduto

        item.lancado_em = datetime.now(timezone.utc)
        session.add(item)

        try:
            session.commit()
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível lançar o produto no estoque, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao lançar produto no estoque")

        criar_log(funcionario_id, f"Lançamento de compra pendente: {nome_produto}")
        return {"detail": "Produto lançado no estoque com sucesso"}
