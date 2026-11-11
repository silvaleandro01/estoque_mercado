import secrets
import string
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select, delete, func

from utils.database import Funcionario, HistoricoSenha, Setor, Salario, SalarioHistorico, engine
from utils.security import (
    criar_token, hash_senha, verificar_senha, HASH_DUMMY_LOGIN,
    LOGIN_MAX_TENTATIVAS, LOGIN_BLOQUEIO_MINUTOS,
)
from utils.email import enviar_email
from utils.erros_banco import tratar_operational_error
from utils.money import arredondar
from logs.logs import criar_log
from schemas.schemas import FuncionarioCreate, LoginRequest, TrocarSenhaRequest, RecuperarSenhaRequest

# Divisor legal (CLT) para converter salário mensal em valor/hora: jornada
# de 44h semanais equivale a 220h/mês -- mesmo divisor usado em
# repository/folha.py para o cálculo de hora extra.
_DIVISOR_HORAS_MES = Decimal("220")

# Mensagem de erro ÚNICA para TODO caso de login inválido -- usuário não
# encontrado, usuário existe mas nunca teve senha definida, senha errada, e
# (depois da Fase de lockout) conta temporariamente bloqueada. Antes desta
# correção (fix/login-rate-limiting) cada caso tinha uma mensagem diferente
# ("Usuário não encontrado" vs "Senha incorreta"), o que permitia descobrir
# quais usernames existem no sistema só observando a resposta de
# /funcionarios/login -- confirmado ao vivo contra o servidor real numa
# varredura de segurança. Ver também HASH_DUMMY_LOGIN (utils/security.py)
# para a mitigação do mesmo vazamento por tempo de resposta.
MSG_LOGIN_INVALIDO = "Usuário ou senha inválidos"


def _registrar_historico(session: Session, funcionario_id: int, password_hash: str):
    session.add(HistoricoSenha(funcionario_id=funcionario_id, password_hash=password_hash))


def _senha_ja_usada(
    session: Session, funcionario_id: int, nova_senha: str, mensagem_erro_transitorio: str
) -> bool:
    # Envolvida em _com_tratamento_operational_error: chamada de dentro de
    # trocar_senha/atualizar_funcionario enquanto a linha do funcionário já
    # está travada (FOR UPDATE) nessas duas rotas, então um deadlock/lock-
    # wait-timeout aqui precisa virar o mesmo 409 "tente novamente" do resto
    # do fluxo, não escapar cru como 500.
    historico = _com_tratamento_operational_error(
        session,
        lambda: session.exec(
            select(HistoricoSenha)
            .where(HistoricoSenha.funcionario_id == funcionario_id)
            .order_by(HistoricoSenha.criado_em.desc())
            .limit(3)
        ).all(),
        mensagem_erro_transitorio,
    )
    return any(verificar_senha(nova_senha, h.password_hash) for h in historico)


def _esta_bloqueado(funcionario: Funcionario, agora: datetime) -> bool:
    # `bloqueado_ate` só é zerado quando alguém tenta logar/trocar senha
    # depois que o bloqueio expirou (ver _resetar_lockout) -- não há job que
    # limpe contas paradas. Por isso NUNCA consultar o banco com
    # `bloqueado_ate IS NOT NULL` sozinho (dá falso positivo em conta cujo
    # bloqueio já passou do tempo); sempre repetir esta comparação com
    # `agora`, igual abaixo.
    bloqueado_ate = funcionario.bloqueado_ate
    if not bloqueado_ate:
        return False
    if bloqueado_ate.tzinfo is None:
        bloqueado_ate = bloqueado_ate.replace(tzinfo=timezone.utc)
    return bloqueado_ate > agora


def _resetar_lockout(funcionario: Funcionario) -> None:
    """
    Zera tentativas_login_falhas/bloqueado_ate -- chamado por todo ponto que
    define um novo password_hash com sucesso (trocar_senha, recuperar_senha,
    atualizar_funcionario) e pelo login bem-sucedido em autenticar_funcionario.

    CORRIGIDO (IMPORTANTE 1 da revisão de fix/login-rate-limiting): antes
    desta correção, nenhum dos três fluxos de troca de senha tocava nesses
    campos -- só mudavam password_hash. Resultado: mesmo com a senha já
    corrigida (pela própria vítima via "esqueci minha senha", ou por um
    admin/RH via reset manual no cadastro), a vítima de um lockout
    malicioso (alguém martelando senha errada contra a conta dela)
    continuava travada pelos minutos inteiros do bloqueio -- a nova senha
    não adiantava nada até o tempo passar sozinho.
    """
    funcionario.tentativas_login_falhas = 0
    funcionario.bloqueado_ate = None


def _com_tratamento_operational_error(session: Session, operacao, mensagem: str):
    """
    Executa `operacao` (uma função sem argumentos -- tipicamente
    `session.commit` ou um `lambda` envolvendo um `session.exec(...)`) e,
    se ela levantar OperationalError, faz rollback da sessão e delega para
    `tratar_operational_error` (-> HTTPException 409 se for deadlock/lock-
    wait-timeout do MySQL, senão relança a exceção original sem mudança).
    """
    try:
        return operacao()
    except OperationalError as exc:
        session.rollback()
        tratar_operational_error(exc, mensagem)


def _registrar_tentativa_falha(
    session: Session, funcionario: Funcionario, agora: datetime, mensagem_erro_transitorio: str
) -> None:
    """
    Incrementa tentativas_login_falhas, aplica bloqueado_ate quando atinge
    LOGIN_MAX_TENTATIVAS, e persiste -- compartilhado entre
    autenticar_funcionario e trocar_senha, que reaproveitam a mesma
    infraestrutura de lockout para a mesma conta.
    """
    funcionario.tentativas_login_falhas += 1
    if funcionario.tentativas_login_falhas >= LOGIN_MAX_TENTATIVAS:
        funcionario.bloqueado_ate = agora + timedelta(minutes=LOGIN_BLOQUEIO_MINUTOS)
    session.add(funcionario)
    _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)


def autenticar_funcionario(dados: LoginRequest):
    with Session(engine) as session:
        partes = dados.username.strip().split(".", 1)
        if len(partes) < 2:
            raise HTTPException(status_code=401, detail="Formato inválido. Use nome.sobrenome")

        nome, sobrenome = partes[0].strip(), partes[1].strip()
        # with_for_update(): trava a linha do funcionário (quando ele existe)
        # durante todo o processo de login -- mesmo padrão de concorrência já
        # usado em repository/estoque.py e repository/vendas.py. Sem ela,
        # duas tentativas de login simultâneas contra a MESMA conta poderiam
        # ambas ler `tentativas_login_falhas` com o mesmo valor "antigo" e
        # incrementar a partir dele (lost update), deixando o contador andar
        # mais devagar do que deveria sob um ataque de força bruta paralelo.
        #
        # CORRIGIDO: esta consulta usava `.ilike()` (comparação case-
        # insensitive), que o dialeto MySQL do SQLAlchemy compila como
        # `WHERE LOWER(nome) LIKE LOWER(%s) AND LOWER(sobrenome) LIKE
        # LOWER(%s)` -- confirmado inspecionando o SQL compilado. Sem NENHUM
        # índice utilizável em nome/sobrenome, isso já forçava um full table
        # scan (EXPLAIN type=ALL); e sob REPEATABLE READ (padrão do InnoDB),
        # uma leitura de bloqueio (FOR UPDATE) que faz table scan trava a
        # tabela `funcionario` INTEIRA durante a transação, não só a linha
        # procurada -- medido ao vivo contra MySQL real: 10 contas DIFERENTES
        # logando simultaneamente levaram ~9x mais tempo que uma chamada
        # isolada, quando deveriam ser independentes. A própria correção de
        # segurança (lockout) tinha introduzido assim um problema de
        # disponibilidade pior do que o resolvido.
        #
        # A correção tem DUAS partes, as duas necessárias:
        #   1) índice funcional em (LOWER(nome), LOWER(sobrenome))
        #      (ver migration.sql) -- cobre a expressão exata usada aqui.
        #   2) trocar `.ilike()` por `func.lower(col) == func.lower(valor)`
        #      (equivalente em resultado -- nome/sobrenome não têm wildcards
        #      de uso legítimo, então LIKE nunca fazia pattern matching real
        #      aqui, só comparação case-insensitive; como bônus, fecha
        #      também a possibilidade de alguém injetar `%`/`_` no username
        #      para forçar um scan ainda mais caro ou casar múltiplas
        #      contas). Confirmado ao vivo com EXPLAIN que só com as DUAS
        #      partes juntas o MySQL passa a usar o índice (type=ref) --
        #      `LOWER(col) LIKE LOWER(%s)` (a forma antiga) não usa um
        #      índice funcional mesmo quando ele existe e cobre a expressão;
        #      só `LOWER(col) = LOWER(%s)` usa.
        #
        # CORRIGIDO: o lado direito da comparação usava
        # `nome.lower()`/`sobrenome.lower()` -- `.lower()`
        # do PYTHON, aplicado ANTES de virar parâmetro da query -- enquanto o
        # lado esquerdo (`func.lower(Funcionario.nome)`) é resolvido pelo
        # MySQL (`LOWER()` do SQL) em cima do valor armazenado. Python e
        # MySQL não usam necessariamente o MESMO algoritmo de case-folding
        # para todo caractere Unicode (ex.: alguns caracteres especiais se
        # comportam diferente em cada um) -- se um username legítimo contiver
        # um desses caracteres, os dois lados poderiam divergir e um usuário
        # real tomaria 401 mesmo com a senha certa. Corrigido aplicando
        # `func.lower()` dos DOIS lados (deixa o MySQL fazer o case-folding
        # dos dois, nunca mistura com `.lower()` do Python) -- elimina a
        # possibilidade de divergência entre os dois mecanismos. Não muda a
        # expressão indexada (continua `LOWER(coluna)` do lado esquerdo),
        # então o índice funcional acima continua válido sem nenhuma mudança
        # de schema.
        #
        # CORRIGIDO: este SELECT ... FOR UPDATE em si não tinha nenhum
        # tratamento de OperationalError --
        # só os commits mais abaixo tinham. Reproduzido ao vivo contra MySQL
        # real (innodb_lock_wait_timeout reduzido só para o teste): um
        # lock-wait-timeout de verdade (código 1205 -- outra transação
        # segurando a MESMA linha por tempo suficiente) escapava cru daqui
        # como um 500, em vez do 409 "tente novamente" que o resto do
        # sistema já usa para contenção transitória de lock. `erros_banco.py`
        # foi estendido para tratar 1205 igual a 1213 (deadlock) -- do ponto
        # de vista do cliente são o mesmo tipo de falha transitória.
        mensagem_erro_transitorio = "Não foi possível processar o login, tente novamente"
        funcionario = _com_tratamento_operational_error(
            session,
            lambda: session.exec(
                select(Funcionario)
                .where(
                    func.lower(Funcionario.nome) == func.lower(nome),
                    func.lower(Funcionario.sobrenome) == func.lower(sobrenome),
                )
                .with_for_update()
            ).first(),
            mensagem_erro_transitorio,
        )

        agora = datetime.now(timezone.utc)

        # Sempre roda verificar_senha() -- mesmo quando não há um
        # funcionário/hash real para comparar -- contra HASH_DUMMY_LOGIN
        # (hash bcrypt fixo que não corresponde a nenhuma senha real).
        # Mitigação de timing-attack: bcrypt é propositalmente lento; pular
        # essa chamada inteiramente quando o usuário não existe (ou já está
        # bloqueado) deixaria essa resposta mensuravelmente mais rápida que a
        # de "usuário existe, senha errada", vazando por uma via diferente
        # (tempo de resposta) a mesma informação que a mensagem genérica
        # abaixo tenta esconder.
        hash_para_verificar = (
            funcionario.password_hash
            if funcionario and funcionario.password_hash
            else HASH_DUMMY_LOGIN
        )
        senha_confere = verificar_senha(dados.senha, hash_para_verificar)

        bloqueado = bool(funcionario and _esta_bloqueado(funcionario, agora))

        # CORRIGIDO: até aqui, só o login BEM-SUCEDIDO zerava
        # `tentativas_login_falhas`/`bloqueado_ate` (ver
        # mais abaixo). Se o bloqueio já tinha EXPIRADO só pelo tempo
        # (`bloqueado_ate` no passado) mas nunca houve um login bem-sucedido
        # depois disso, o contador antigo (ex.: LOGIN_MAX_TENTATIVAS) ficava
        # parado -- e a PRÓXIMA tentativa, mesmo uma senha ERRADA isolada
        # dias depois, já somava LOGIN_MAX_TENTATIVAS + 1 e rebloqueava a
        # conta instantaneamente, em vez de dar as LOGIN_MAX_TENTATIVAS
        # tentativas completas de novo (confirmado por reprodução). Reset
        # explícito ANTES de computar `tentativa_de_senha_errada` abaixo, pra
        # que o incremento desta tentativa (se for o caso) parta de 0, não do
        # valor antigo -- junto do commit que já existir mais abaixo para
        # este mesmo fluxo (sem round-trip extra ao banco).
        bloqueio_expirado = bool(funcionario and funcionario.bloqueado_ate is not None and not bloqueado)
        if bloqueio_expirado:
            _resetar_lockout(funcionario)

        # Lockout (fix/login-rate-limiting) -- decisões de escopo:
        #   - usuário inexistente: não existe linha/conta pra incrementar ou
        #     bloquear. Um rate-limit por IP foi avaliado e descartado por
        #     ser desproporcional ao escopo deste projeto acadêmico/pessoal
        #     (sem proxy reverso/observabilidade de IP hoje); fica como
        #     limitação aceita e documentada.
        #   - funcionário existe mas nunca definiu senha (password_hash
        #     nulo): mesma lógica -- não há senha "para forçar", então essa
        #     tentativa não soma no contador.
        #   - conta JÁ bloqueada (`bloqueado` True): tentativas adicionais
        #     durante a janela de bloqueio NÃO reiniciam a contagem nem
        #     estendem `bloqueado_ate` -- evita que um atacante consiga
        #     manter a conta bloqueada indefinidamente só martelando login
        #     contra ela (negação de serviço ao dono legítimo da conta).
        tentativa_de_senha_errada = (
            funcionario is not None
            and funcionario.password_hash is not None
            and not bloqueado
            and not senha_confere
        )

        if tentativa_de_senha_errada:
            # AVALIADO: só este ramo ("conta existe, desbloqueada, senha
            # errada") faz um commit extra aqui (pra persistir o incremento
            # do contador) -- os outros ramos que levam ao mesmo 401 genérico
            # (usuário inexistente, sem senha definida, já bloqueada) não
            # passam por aqui, então respondem sem esse round-trip de escrita
            # extra. Isso cria uma pequena descontinuidade de tempo que, em
            # teoria, poderia ajudar a distinguir de fora o momento em que
            # uma conta passa a existir/estar desbloqueada vs os outros
            # estados. DECISÃO: aceito como risco baixo, sem equalizar,
            # porque (1) o custo DOMINANTE do tempo de resposta já é o bcrypt
            # de verificar_senha() -- dezenas a centenas de ms -- e esse
            # custo já é igual em TODOS os ramos (HASH_DUMMY_LOGIN garante
            # que verificar_senha() roda sempre, ver mais acima); o commit
            # extra aqui é uma única escrita numa linha já localizada pelo
            # índice, ordens de grandeza mais rápido que o bcrypt, então uma
            # fração pequena do tempo total; (2) distinguir essa diferença de
            # fora exigiria medir muitas requisições com precisão maior que
            # o jitter normal de rede -- fora do modelo de ameaça realista
            # para este projeto acadêmico/pessoal. Equalizar de verdade (ex.:
            # forçar algum round-trip de escrita equivalente nos outros 3
            # ramos) adicionaria complexidade/risco de bug novo pra fechar
            # uma brecha residual de baixíssimo impacto prático -- não foi
            # considerado valer a pena.
            _registrar_tentativa_falha(session, funcionario, agora, mensagem_erro_transitorio)

        if not funcionario or not funcionario.password_hash or bloqueado or not senha_confere:
            # Mesma mensagem genérica também para conta bloqueada -- ver
            # decisão documentada no relatório da correção: uma mensagem
            # diferente tipo "conta bloqueada" confirmaria, por si só, que o
            # username existe (voltaria a abrir o canal de enumeração que a
            # unificação acima fechou), então o custo de usabilidade (o
            # usuário não sabe que está bloqueado, só que "a senha está
            # errada") foi aceito em troca de não vazar essa informação.
            raise HTTPException(status_code=401, detail=MSG_LOGIN_INVALIDO)

        # Login bem-sucedido: zera o contador e qualquer bloqueio residual.
        _resetar_lockout(funcionario)
        token = criar_token(funcionario.id, funcionario.is_admin)
        funcionario.token = token
        session.add(funcionario)
        _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)

        setor = session.get(Setor, funcionario.setor_id)

        ultima = funcionario.senha_atualizada_em
        if ultima and ultima.tzinfo is None:
            ultima = ultima.replace(tzinfo=timezone.utc)
        lembrete_senha = bool(ultima and (agora - ultima) >= timedelta(days=365))

        return {
            "token": token,
            "is_admin": funcionario.is_admin,
            "setor": setor.tipo if setor else None,
            "cargo": funcionario.cargo,
            "bate_ponto": funcionario.bate_ponto,
            "nome_completo": f"{funcionario.nome} {funcionario.sobrenome}",
            "lembrete_senha": lembrete_senha,
            "senha_temporaria": funcionario.senha_temporaria,
        }


def criar_funcionario(dados: FuncionarioCreate, funcionario_id_solicitante: int):
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
            cargo=dados.cargo,
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
            senha_temporaria=True,
            bate_ponto=dados.bate_ponto,
            # Sempre derivado do cargo -- nunca aceito como input do
            # cliente (ver schemas.FuncionarioCreate).
            cargo_confianca=(dados.cargo == "diretoria"),
        )
        try:
            session.add(funcionario)
            session.flush()
            _registrar_historico(session, funcionario.id, password_hash)
            session.commit()
            session.refresh(funcionario)
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar funcionário")

    # Achado do painel de revisão: o frontend já manda `valor_mensal` no
    # cadastro de funcionário, mas até esta correção o schema não tinha
    # esse campo -- o Pydantic descartava em silêncio, RH achava que tinha
    # salvo o salário e nada era persistido. Fora da transação acima (igual
    # ao padrão já usado para log em outros pontos): se isto falhar, o
    # funcionário já foi criado com sucesso, só o salário fica pendente de
    # definir manualmente depois.
    if dados.valor_mensal is not None:
        definir_salario(funcionario.id, dados.valor_mensal, funcionario_id_solicitante)

    return funcionario


def listar_funcionarios():
    with Session(engine) as session:
        return session.exec(select(Funcionario)).all()


def buscar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")
        return funcionario


def atualizar_funcionario(funcionario_id: int, dados: FuncionarioCreate, funcionario_id_solicitante: int):
    with Session(engine) as session:
        mensagem_erro_transitorio = "Não foi possível processar a solicitação, tente novamente"

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
        funcionario.cargo = dados.cargo
        funcionario.cpf = dados.cpf
        funcionario.email = dados.email
        funcionario.cep = dados.cep
        funcionario.estado = dados.estado
        funcionario.cidade = dados.cidade
        funcionario.bairro = dados.bairro
        funcionario.rua = dados.rua
        funcionario.numero = dados.numero
        funcionario.bate_ponto = dados.bate_ponto
        funcionario.cargo_confianca = (dados.cargo == "diretoria")

        if dados.senha:
            if _senha_ja_usada(session, funcionario_id, dados.senha, mensagem_erro_transitorio):
                raise HTTPException(
                    status_code=400,
                    detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
                )
            funcionario.password_hash = hash_senha(dados.senha)
            funcionario.senha_atualizada_em = datetime.now(timezone.utc)
            _registrar_historico(session, funcionario_id, funcionario.password_hash)
            # Ver docstring de _resetar_lockout: reset manual de senha via
            # RH/admin também precisa liberar um lockout em andamento, senão
            # a vítima continua travada mesmo com a senha já corrigida.
            _resetar_lockout(funcionario)

        try:
            _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)
            session.refresh(funcionario)
        except HTTPException:
            raise
        except OperationalError:
            raise
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao atualizar funcionário")

    # Ver mesmo comentário em criar_funcionario: o frontend já manda
    # valor_mensal na edição de funcionário também, mesmo gap de dado
    # perdido em silêncio.
    if dados.valor_mensal is not None:
        definir_salario(funcionario_id, dados.valor_mensal, funcionario_id_solicitante)

    return funcionario


def deletar_funcionario(funcionario_id: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")
        try:
            # Bug pré-existente (de uma fase anterior a esta, não da Fase 4 de
            # histórico de movimentações) descoberto durante a correção dos
            # achados do painel de revisão da Fase 4: a FK de
            # `historico_senha` para `funcionario` (ver migration.sql) nunca
            # teve ON DELETE configurado -- deletar um funcionário que já
            # tivesse QUALQUER linha em historico_senha (ou seja, qualquer
            # funcionário real que já trocou de senha alguma vez, seja pelo
            # fluxo de troca obrigatória no primeiro acesso ou por
            # recuperação de senha -- ver criar_funcionario/trocar_senha/
            # recuperar_senha acima, que sempre chamam _registrar_historico)
            # quebrava com IntegrityError/500 -- reproduzido ao vivo contra
            # MySQL real.
            #
            # DECISÃO: diferente de `movimentacao_estoque.funcionario_id`
            # (ON DELETE SET NULL -- preserva o histórico de auditoria de
            # ESTOQUE, só anonimiza a autoria; ver repository/estoque.py e
            # migration.sql), `historico_senha` é só um mecanismo interno de
            # bloqueio de reuso de senha (ver _senha_ja_usada acima) -- não
            # é log de auditoria de negócio que precise sobreviver à saída
            # do funcionário. Sem o funcionário dono, a linha não tem mais
            # nenhum propósito, então apaga junto -- mesmo padrão (DELETE
            # explícito por query, na MESMA transação, com flush ANTES do
            # delete do pai) já usado para Lote/MovimentacaoEstoque em
            # repository/estoque.py::deletar_estoque. Nenhuma mudança de
            # schema (ON DELETE CASCADE) foi necessária para esta correção.
            session.exec(delete(HistoricoSenha).where(HistoricoSenha.funcionario_id == funcionario_id))
            session.flush()
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
        mensagem_erro_transitorio = "Não foi possível processar a solicitação, tente novamente"

        # CORRIGIDO: este endpoint lia o funcionário com
        # `session.get(Funcionario, funcionario_id)` -- sem nenhuma trava --
        # e fazia o MESMO padrão "ler, incrementar em memória, escrever" que
        # o login tinha antes da correção equivalente lá (ver
        # autenticar_funcionario acima para o raciocínio completo sobre por
        # que isso é um lost update sob concorrência). Reproduzido ao vivo
        # (threads reais contra MySQL real): 20 tentativas simultâneas de
        # senha_atual errada deixavam o contador em 1-2 (nunca nos 5
        # esperados) -- a conta nunca bloqueava de verdade.
        #
        # Diferente do login, `funcionario_id` aqui já vem validado do token
        # JWT (ver services/auth.py) -- é a própria PK da tabela, que já tem
        # índice (chave primária) -- então a correção não precisou de nenhum
        # índice novo em migration.sql, só travar esta leitura com
        # `with_for_update()`, mesmo padrão já usado no login.
        funcionario = _com_tratamento_operational_error(
            session,
            lambda: session.exec(
                select(Funcionario).where(Funcionario.id == funcionario_id).with_for_update()
            ).first(),
            mensagem_erro_transitorio,
        )
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        agora = datetime.now(timezone.utc)

        # CORRIGIDO: este endpoint verificava a senha ATUAL sem nenhum
        # limite de tentativas -- alguém com um token roubado (mas sem saber
        # a senha atual) podia tentar adivinhar indefinidamente, sem nenhum
        # throttle; o mesmo tipo de força bruta que o lockout do login
        # mitiga. DECISÃO: reaproveita a MESMA infraestrutura
        # (tentativas_login_falhas/bloqueado_ate) em vez de um mecanismo
        # separado -- é o MESMO funcionário/conta, e um atacante adivinhando
        # a senha atual aqui é funcionalmente o mesmo ataque. Diferente do
        # login, este endpoint já exige um token válido para ESTE
        # funcionário_id específico (não há username pra descobrir por
        # enumeração), então não precisa da mitigação de timing/mensagem
        # genérica do login -- só do limite de tentativas em si.
        #
        # SIMÉTRICO ao login: com a conta bloqueada, rejeita incondicionalmente
        # -- mesmo com a senha_atual CORRETA -- sem gastar uma tentativa de
        # verificação de senha. Alguém com um token roubado não consegue
        # seguir testando a senha atual indefinidamente só porque a conta já
        # está bloqueada (isso tornaria o próprio lockout deste endpoint
        # cosmético contra o ataque que ele existe pra conter). A recuperação
        # de uma conta travada por um lockout malicioso não passa mais por
        # aqui enquanto o bloqueio estiver ativo -- usa `recuperar_senha`
        # (reset por e-mail/CPF) ou `atualizar_funcionario` (reset via
        # RH/admin), que já liberam o lockout (ver docstring de
        # _resetar_lockout) e não reabrem esta janela de adivinhação.
        bloqueado = _esta_bloqueado(funcionario, agora)
        if bloqueado:
            raise HTTPException(status_code=401, detail="Senha atual incorreta")

        # Mesmo reset do login: se o bloqueio já expirou só pelo tempo (sem
        # uma troca de senha bem-sucedida depois), zera o contador antigo
        # antes de processar esta tentativa.
        #
        # CORRIGIDO: este reset, feito só em memória aqui, podia ser
        # descartado SILENCIOSAMENTE se a checagem de reuso de senha
        # (_senha_ja_usada, mais abaixo) disparasse um 400 antes de qualquer
        # commit alcançar este `funcionario` -- a sessão saía sem persistir
        # nada, recriando o mesmo bug do CRÍTICO 3 do login, só que por este
        # caminho específico. Reproduzido: conta com contador alto +
        # `bloqueado_ate` no passado (bloqueio já expirado) + senha atual
        # CERTA + nova senha igual a uma das últimas 3 -> 400, e o contador
        # continuava alto no banco depois.
        #
        # `bloqueio_resetado` sinaliza que este reset ainda precisa ser
        # persistido antes de qualquer saída da função -- os dois pontos mais
        # abaixo que podem terminar a função (o 400 de reutilização de senha,
        # e o commit final de sucesso) verificam essa flag e garantem que ele
        # seja commitado independentemente de qual dos dois for alcançado. A
        # trava pega no SELECT ... FOR UPDATE acima continua ativa o tempo
        # todo até ali -- nenhum commit acontece entre a leitura e estes dois
        # pontos de saída, então não há janela destravada no meio.
        bloqueio_resetado = False
        if funcionario.bloqueado_ate is not None:
            _resetar_lockout(funcionario)
            bloqueio_resetado = True

        senha_atual_confere = bool(
            funcionario.password_hash and verificar_senha(dados.senha_atual, funcionario.password_hash)
        )

        if not senha_atual_confere:
            # Chegou até aqui só se a conta NÃO estava bloqueada (ver early
            # return acima), então sempre soma a tentativa -- sem o guard
            # "if not bloqueado" que o login tem (lá, usuário inexistente/
            # sem senha/já bloqueado levam ao mesmo 401 sem esse commit
            # extra; aqui já se sabe que o funcionário existe e não está
            # bloqueado antes de chegar neste ramo).
            _registrar_tentativa_falha(session, funcionario, agora, mensagem_erro_transitorio)
            raise HTTPException(status_code=401, detail="Senha atual incorreta")

        if _senha_ja_usada(session, funcionario_id, dados.nova_senha, mensagem_erro_transitorio):
            # Se o bloqueio tinha expirado e foi resetado só em memória (este
            # caminho não passa pelo branch de "senha errada" acima, que já
            # persistiria o reset junto do incremento), commita agora, ANTES
            # deste 400 -- senão o reset nunca chegaria ao banco.
            if bloqueio_resetado:
                session.add(funcionario)
                _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)
            raise HTTPException(
                status_code=400,
                detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
            )

        novo_hash = hash_senha(dados.nova_senha)
        funcionario.password_hash = novo_hash
        funcionario.senha_atualizada_em = datetime.now(timezone.utc)
        funcionario.senha_temporaria = False
        _registrar_historico(session, funcionario_id, novo_hash)
        # IMPORTANTE 1 -- ver docstring de _resetar_lockout. Idempotente se
        # já tiver sido resetado (e persistido) acima.
        _resetar_lockout(funcionario)
        session.add(funcionario)

        # `except OperationalError: raise` preserva o comportamento de deixar
        # um OperationalError que NÃO seja deadlock/lock-wait-timeout
        # propagar cru (mesmo padrão do login -- ver
        # test_login_outro_operational_error_nao_vira_409), em vez de
        # convertê-lo também em 500 genérico.
        try:
            _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)
            return {"msg": "Senha alterada com sucesso"}
        except HTTPException:
            raise
        except OperationalError:
            raise
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao alterar senha")


def recuperar_senha(dados: RecuperarSenhaRequest):
    with Session(engine) as session:
        mensagem_erro_transitorio = "Não foi possível processar a solicitação, tente novamente"

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
        # Ver docstring de _resetar_lockout: recuperação de senha por e-mail
        # também precisa liberar um lockout em andamento, senão a vítima
        # continua travada mesmo com a senha nova já na caixa de entrada.
        _resetar_lockout(funcionario)

        try:
            _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)
        except HTTPException:
            raise
        except OperationalError:
            raise
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


def definir_salario(funcionario_id: int, valor: Decimal, funcionario_id_solicitante: int):
    with Session(engine) as session:
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        nome_completo = f"{funcionario.nome} {funcionario.sobrenome}"
        valor = arredondar(valor)
        valor_hora = arredondar(valor / _DIVISOR_HORAS_MES)
        salario = session.exec(select(Salario).where(Salario.funcionario_id == funcionario_id)).first()

        try:
            if not salario:
                session.add(Salario(funcionario_id=funcionario_id, valor_mensal=valor, valor_hora=valor_hora))
            elif salario.valor_mensal != valor:
                session.add(
                    SalarioHistorico(
                        funcionario_id=funcionario_id,
                        valor_antigo=salario.valor_mensal,
                        valor_novo=valor,
                    )
                )
                salario.valor_mensal = valor
                salario.valor_hora = valor_hora
                session.add(salario)
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao definir salário")

    criar_log(funcionario_id_solicitante, f"Salário de {nome_completo} definido para R$ {valor:.2f}")
    return {"detail": "Salário atualizado com sucesso"}


def salario_historico(funcionario_id: int):
    with Session(engine) as session:
        return session.exec(
            select(SalarioHistorico)
            .where(SalarioHistorico.funcionario_id == funcionario_id)
            .order_by(SalarioHistorico.data_alteracao.desc())
        ).all()
