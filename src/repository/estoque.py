from decimal import Decimal
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select, delete

from utils.database import Estoque, Compra, ItemCompra, Fornecedor, Lote, MovimentacaoEstoque, engine
from utils.money import arredondar
from utils.quantidade import arredondar_quantidade, validar_quantidade_inteira_se_unidade
from utils.erros_banco import tratar_operational_error
from logs.logs import criar_log
from schemas.schemas import EstoqueCreate, EstoqueUpdate, ConfirmarPendenteInput, AjusteInventarioInput
from repository.lotes import reconciliar_lote_sem_validade, criar_lote
from repository.movimentacoes import registrar_movimentacao


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
            try:
                # Incremento manual (sem lote/validade informados): reconcilia
                # o lote "sem validade" do produto a partir do saldo final já
                # atualizado acima (não um delta isolado -- ver docstring de
                # reconciliar_lote_sem_validade sobre por que um delta isolado
                # é frágil quando o produto já tinha saldo que não estava
                # registrado em nenhum lote). Mantém a invariante soma(Lote.
                # quantidade) == Estoque.quantidade (ver repository/lotes.py).
                #
                # IMPORTANTE 1 (revisão da Fase 4): esta chamada e o
                # registrar_movimentacao logo abaixo PRECISAM estar dentro
                # do try -- as duas fazem flush, disparando INSERT/UPDATE
                # contra o banco; fora do try (como estava antes), um
                # deadlock do MySQL aqui escapava do tratamento de
                # tratar_operational_error e virava um 500 cru, diferente
                # do ramo "produto novo" logo abaixo (que sempre esteve
                # correto).
                #
                # Histórico de movimentações (Fase 4): CRÍTICO 2 da revisão --
                # reconciliar_lote_sem_validade agora retorna o delta que
                # efetivamente aplicou ao lote "sem validade" (lote_residual,
                # delta_residual) -- a movimentação do incremento é registrada
                # DIRETO nesse lote (lote_id=lote_residual.id), não mais
                # lote_id=None, fechando a contradição do docstring de
                # MovimentacaoEstoque (prometia movimentação para toda
                # alteração de Lote.quantidade, mas nunca gerava uma para o
                # lote "sem validade"). Uma ÚNICA movimentação por incremento,
                # não uma segunda somada a esta -- delta_residual é exatamente
                # igual a dados.quantidade neste caminho (incremento manual não
                # toca nenhum lote datado), exceto no primeiro toque num
                # produto genuinamente legado (ver nuance no docstring de
                # reconciliar_lote_sem_validade).
                lote_residual, delta_residual = reconciliar_lote_sem_validade(session, produto_existente.id)
                if delta_residual != 0:
                    # IMPORTANTE 5 (revisão da Fase 4): ENTRADA_MANUAL, não
                    # ENTRADA_COMPRA -- este incremento via POST
                    # /estoque/inserir não vem de nenhuma compra/fornecedor
                    # rastreado (ENTRADA_COMPRA fica reservado só para
                    # confirmar_pendente).
                    registrar_movimentacao(
                        session, produto_existente.id, "ENTRADA_MANUAL",
                        delta_residual, funcionario_id, lote_id=lote_residual.id,
                    )
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
            #
            # Histórico de movimentações (Fase 4): CRÍTICO 2, mesmo
            # raciocínio do incremento acima -- movimentação ligada DIRETO
            # ao lote "sem validade" (lote_id=lote_residual.id) quando a
            # quantidade inicial é > 0, None quando é 0 (reconciliar não
            # cria lote nenhum nesse caso). Para um cadastro novo,
            # lote_residual/delta "bateriam" exatamente com
            # estoque.quantidade (produto acabou de nascer, impossível ter
            # saldo pré-existente não rastreado) -- por isso a quantidade
            # registrada abaixo usa estoque.quantidade diretamente, mais
            # direto de ler que o delta recém-calculado.
            #
            # IMPORTANTE 6 (revisão da Fase 4): DIFERENTE do incremento
            # acima (que só registra quando o delta é != 0), o CADASTRO
            # sempre gera uma movimentação -- mesmo com saldo inicial 0 --
            # para deixar um rastro auditável de "quando o produto nasceu"
            # dentro do domínio de movimentações de estoque. A regra de
            # pular quando o delta é zero continua valendo só para
            # incremento/ajuste em produto JÁ existente (onde "nada mudou"
            # de fato não deixa rastro nenhum pra deixar).
            #
            # IMPORTANTE 5 (revisão da Fase 4): ENTRADA_MANUAL, não
            # ENTRADA_COMPRA -- cadastro via POST /estoque/inserir não vem
            # de nenhuma confirmação de pendente.
            lote_residual, _delta_residual = reconciliar_lote_sem_validade(session, estoque.id)
            registrar_movimentacao(
                session, estoque.id, "ENTRADA_MANUAL",
                estoque.quantidade, funcionario_id,
                lote_id=lote_residual.id if lote_residual is not None else None,
            )
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
    """PUT /estoque/atualizar: a partir da Fase 4, só edita METADADO do
    produto (nome, preço, categoria, unidade de medida, etc.) -- nunca mais
    `quantidade` (ver docstring de schemas.EstoqueUpdate sobre a decisão de
    arquitetura; alteração de saldo manual agora é sempre via
    `ajustar_inventario`, que exige motivo e gera uma movimentação
    AJUSTE_INVENTARIO).

    with_for_update(): mesma trava usada em criar_estoque/confirmar_pendente/
    criar_venda/ajustar_inventario. Mesmo este endpoint não escrevendo mais
    em `quantidade`, a trava continua valendo a pena: serializa esta edição
    contra um ajuste de inventário concorrente no MESMO produto (ex.: evita
    que a validação de unidade_medida abaixo, feita contra `estoque.
    quantidade` lido aqui, fique baseada num valor que um ajuste concorrente
    está prestes a mudar)."""
    with Session(engine) as session:
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

        # A unidade de medida em si vem do payload (o formulário de edição
        # permite trocar UN/KG/L do produto) -- mas a quantidade usada na
        # validação é a JÁ EXISTENTE do produto (não vem mais do payload):
        # sem isso, um PUT poderia trocar um produto KG com saldo
        # fracionário (ex.: 1.5) para UN sem nenhum erro, deixando o
        # produto com uma quantidade fracionária "escondida" sob uma
        # unidade que não permite fração.
        validar_quantidade_inteira_se_unidade(estoque.quantidade, dados.unidade_medida, dados.nomedoproduto)

        estoque.titulo = dados.titulo
        estoque.nomedoproduto = dados.nomedoproduto
        estoque.unidade_medida = dados.unidade_medida
        estoque.estoque_minimo = arredondar_quantidade(dados.estoque_minimo)
        estoque.preco = arredondar(dados.preco)
        estoque.codigodebarras = dados.codigodebarras
        estoque.categoria = dados.categoria
        estoque.funcionario_id = funcionario_id
        estoque.fornecedor_id = dados.fornecedor_id

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


def ajustar_inventario(estoque_id: int, dados: AjusteInventarioInput, funcionario_id: int):
    """POST /estoque/{id}/ajustar-inventario (Fase 4): único ponto de
    alteração manual de saldo a partir desta fase (ver docstring de
    schemas.EstoqueUpdate). Sempre exige `motivo` (validado na camada
    Pydantic, schemas.AjusteInventarioInput) e gera uma movimentação
    AJUSTE_INVENTARIO com o delta assinado (positivo se aumenta o saldo,
    negativo se reduz).

    Mesmo padrão de lock/deadlock dos outros pontos de escrita de estoque
    (with_for_update() + tratar_operational_error) -- este é um ponto de
    escrita NOVO desta fase, e a Fase 3 já teve a lição de deixar um ponto
    de escrita novo sem essas proteções (ver histórico de
    repository/estoque.py)."""
    with Session(engine) as session:
        estoque = session.exec(
            select(Estoque).where(Estoque.id == estoque_id).with_for_update()
        ).first()
        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")

        validar_quantidade_inteira_se_unidade(dados.nova_quantidade, estoque.unidade_medida, estoque.nomedoproduto)

        nova_quantidade = arredondar_quantidade(dados.nova_quantidade)
        delta = arredondar_quantidade(nova_quantidade - estoque.quantidade)

        estoque.quantidade = nova_quantidade
        estoque.funcionario_id = funcionario_id
        session.add(estoque)

        try:
            # Só mexe em Lote/gera movimentação se o saldo realmente mudou
            # -- uma contagem que confirma o saldo já registrado (delta ==
            # 0) não deixa rastro nenhum, não há nada pra reconciliar nem
            # pra registrar (mesmo raciocínio de no-op já usado em
            # reconciliar_lote_sem_validade quando o residual é 0).
            #
            # IMPORTANTE 1 (revisão da Fase 4): este bloco inteiro
            # (reconciliar_lote_sem_validade + registrar_movimentacao)
            # precisa estar DENTRO do try -- as duas fazem flush,
            # disparando INSERT/UPDATE contra o banco; fora do try (como
            # estava antes), um deadlock do MySQL aqui escapava do
            # tratamento de tratar_operational_error e virava um 500 cru.
            if delta != 0:
                # PUT sobrescrevia a quantidade total e reconciliava o lote
                # "sem validade" a partir do saldo final -- esse
                # comportamento migrou pra cá junto com a responsabilidade
                # de alterar saldo manualmente (ver docstring de
                # schemas.EstoqueUpdate).
                #
                # Histórico de movimentações (Fase 4): CRÍTICO 2 da revisão --
                # mesmo raciocínio de criar_estoque (ver comentários lá) --
                # movimentação ligada DIRETO ao lote "sem validade"
                # (lote_id=lote_residual.id), não mais lote_id=None.
                # ajustar_inventario nunca toca lote datado, então
                # delta_residual bate exatamente com `delta` (nominal), exceto
                # no primeiro toque num produto genuinamente legado (ver nuance
                # no docstring de reconciliar_lote_sem_validade).
                lote_residual, delta_residual = reconciliar_lote_sem_validade(session, estoque.id)
                if delta_residual != 0:
                    registrar_movimentacao(
                        session, estoque.id, "AJUSTE_INVENTARIO", delta_residual, funcionario_id,
                        lote_id=lote_residual.id, motivo=dados.motivo,
                    )

            session.commit()
            session.refresh(estoque)
            criar_log(funcionario_id, f"Ajuste de inventário: {estoque.nomedoproduto} ({dados.motivo})")
            return estoque
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível ajustar o inventário, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao ajustar inventário")


def deletar_estoque(estoque_id: int):
    with Session(engine) as session:
        estoque = session.get(Estoque, estoque_id)
        if not estoque:
            raise HTTPException(status_code=404, detail="Estoque não localizado")
        try:
            # CRÍTICO 1 (revisão da Fase 4): mesmo bug de ordem de delete que
            # a Fase 3 já tinha corrigido para `Lote`, reintroduzido aqui para
            # `MovimentacaoEstoque` -- a FK dela para `estoque`/`lote` (ver
            # migration.sql) também não tem ON DELETE CASCADE, então excluir
            # um produto que já tivesse QUALQUER movimentação registrada (o
            # caso normal de uso real, já que toda entrada/venda/ajuste gera
            # uma) quebrava com IntegrityError/500 -- reproduzido ao vivo
            # contra MySQL real.
            #
            # Ordem correta (cascata manual, mesmo raciocínio do comentário
            # original abaixo sobre Lote): movimentações PRIMEIRO (elas
            # referenciam tanto `estoque_id` quanto, opcionalmente,
            # `lote_id` -- apagar por `estoque_id` cobre as DUAS, já que
            # `registrar_movimentacao` sempre grava o MESMO estoque_id do
            # produto, tenha lote_id ou não), DEPOIS lotes, DEPOIS o produto.
            #
            # Lote é um detalhamento do saldo deste produto (não um
            # histórico independente, diferente de ItemVenda/ItemCompra) --
            # ao excluir o produto, os lotes dele deixam de fazer sentido.
            # Excluídos aqui, na mesma transação, para não violar a FK
            # (lote.estoque_id -> estoque.id) nem deixar lote órfão.
            #
            # DELETE explícito por query (em vez de carregar cada linha com
            # session.exec(select(...)) e marcar para exclusão uma a uma com
            # session.delete()), seguido de um flush ANTES do próximo passo:
            # sem isso, o SQLAlchemy decide por conta própria a ordem do
            # flush (não há Relationship() do SQLModel ligando estas tabelas
            # neste projeto, só a FK crua) e podia emitir o DELETE de uma
            # tabela "de baixo" antes da "de cima", batendo na FK e virando
            # um IntegrityError (1451) cru -- reproduzido ao vivo contra
            # MySQL real para TODO produto que já tivesse qualquer lote (e,
            # agora, qualquer movimentação). O DELETE direto garante a ordem
            # manualmente, sem depender do unit-of-work adivinhar, e sem
            # introduzir Relationship()/cascade -- padrão que o resto do
            # schema deste projeto não usa (só FK crua em todo lugar).
            session.exec(delete(MovimentacaoEstoque).where(MovimentacaoEstoque.estoque_id == estoque_id))
            session.flush()
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

        # IMPORTANTE 1 (revisão da Fase 4): todo o bloco abaixo (criar_lote,
        # reconciliar_lote_sem_validade e registrar_movimentacao -- todas
        # fazem flush, disparando INSERT/UPDATE contra o banco) precisa
        # estar DENTRO do try -- fora dele (como estava antes), um deadlock
        # do MySQL em qualquer uma dessas chamadas escapava do tratamento
        # de tratar_operational_error e virava um 500 cru, diferente de
        # criar_venda e do ramo "produto novo" de criar_estoque (que sempre
        # estiveram corretos).
        try:
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
                lote = criar_lote(session, produto_existente.id, dados.codigo_lote, item.quantidade, dados.validade)
                # Reconcilia o lote "sem validade" do produto: se o produto já
                # tinha saldo pré-existente que não estava em NENHUM lote
                # (produto legado, cadastrado antes desta fase, ou nunca
                # tocado por ela), essa é a hora de materializá-lo -- senão
                # essas unidades ficam fora do rastreamento por lote para
                # sempre, já que a lista de lotes do produto deixa de estar
                # vazia a partir daqui (ver docstring de
                # reconciliar_lote_sem_validade, cenário C).
                lote_residual, delta_residual = reconciliar_lote_sem_validade(session, produto_existente.id)
                # Histórico de movimentações (Fase 4): ligada ao lote RASTREADO
                # recém-criado acima (diferente do incremento manual via
                # /estoque/inserir, aqui há um lote/validade reais por trás).
                registrar_movimentacao(
                    session, produto_existente.id, "ENTRADA_COMPRA",
                    item.quantidade, funcionario_id, lote_id=lote.id,
                )
                # Histórico de movimentações (Fase 4): CRÍTICO 2 da revisão --
                # movimentação ADICIONAL (não substitui a de cima) sempre que
                # reconciliar_lote_sem_validade materializar/mudar algo no lote
                # "sem validade" -- cenário C do docstring de
                # reconciliar_lote_sem_validade: saldo pré-existente do produto
                # que nunca tinha sido rastreado em NENHUM lote, só agora
                # "descoberto" porque a lista de lotes deixou de estar vazia.
                # Não duplica a contabilidade do item.quantidade acima: esta
                # segunda movimentação só existe quando delta_residual != 0,
                # que só acontece por causa desse saldo pré-existente (um
                # produto sem esse saldo "extra" dá delta_residual == 0 aqui,
                # já que o lote recém-criado cobre sozinho toda a entrada desta
                # confirmação).
                if delta_residual != 0:
                    registrar_movimentacao(
                        session, produto_existente.id, "ENTRADA_COMPRA",
                        delta_residual, funcionario_id, lote_id=lote_residual.id,
                    )
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
                lote = criar_lote(session, novo.id, dados.codigo_lote, item.quantidade, dados.validade)
                # Produto novo: residual esperado é 0 (toda a quantidade já
                # está no lote recém-criado acima), mas chama mesmo assim por
                # consistência/defesa em profundidade -- é um no-op barato
                # quando o residual já é 0.
                lote_residual, delta_residual = reconciliar_lote_sem_validade(session, novo.id)
                registrar_movimentacao(
                    session, novo.id, "ENTRADA_COMPRA",
                    item.quantidade, funcionario_id, lote_id=lote.id,
                )
                # Histórico de movimentações (Fase 4): CRÍTICO 2 -- mesmo
                # raciocínio do ramo de produto existente acima. Produto novo:
                # delta_residual normalmente é 0 (residual esperado é 0, toda a
                # quantidade já está no lote recém-criado), então esta segunda
                # movimentação normalmente não é gerada -- mantido por defesa
                # em profundidade/consistência.
                if delta_residual != 0:
                    registrar_movimentacao(
                        session, novo.id, "ENTRADA_COMPRA",
                        delta_residual, funcionario_id, lote_id=lote_residual.id,
                    )
                nome_produto = novo.nomedoproduto

            item.lancado_em = datetime.now(timezone.utc)
            session.add(item)

            session.commit()
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível lançar o produto no estoque, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao lançar produto no estoque")

        criar_log(funcionario_id, f"Lançamento de compra pendente: {nome_produto}")
        return {"detail": "Produto lançado no estoque com sucesso"}
