import secrets
import string
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select, delete, func

from utils.database import Funcionario, HistoricoSenha, Setor, engine
from utils.security import (
    criar_token, hash_senha, verificar_senha, HASH_DUMMY_LOGIN,
    LOGIN_MAX_TENTATIVAS, LOGIN_BLOQUEIO_MINUTOS,
)
from utils.email import enviar_email
from utils.erros_banco import tratar_operational_error
from schemas.schemas import FuncionarioCreate, LoginRequest, TrocarSenhaRequest, RecuperarSenhaRequest

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


def _senha_ja_usada(session: Session, funcionario_id: int, nova_senha: str) -> bool:
    historico = session.exec(
        select(HistoricoSenha)
        .where(HistoricoSenha.funcionario_id == funcionario_id)
        .order_by(HistoricoSenha.criado_em.desc())
        .limit(3)
    ).all()
    return any(verificar_senha(nova_senha, h.password_hash) for h in historico)


def _esta_bloqueado(funcionario: Funcionario, agora: datetime) -> bool:
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

    NITPICK (revisão de fix/login-rate-limiting): extraído pra eliminar a
    duplicação entre os 3 pontos de `autenticar_funcionario` que viraram
    `try: ... / except OperationalError: tratar_operational_error(...)`
    depois do CRÍTICO 2 -- o SELECT ... FOR UPDATE em si, o commit do
    incremento de tentativas, e o commit do login bem-sucedido.
    """
    try:
        return operacao()
    except OperationalError as exc:
        session.rollback()
        tratar_operational_error(exc, mensagem)


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
        # CORRIGIDO (CRÍTICO 1 da revisão desta trava): esta consulta usava
        # `.ilike()` (comparação case-insensitive), que o dialeto MySQL do
        # SQLAlchemy compila como `WHERE LOWER(nome) LIKE LOWER(%s) AND
        # LOWER(sobrenome) LIKE LOWER(%s)` -- confirmado inspecionando o SQL
        # compilado. Sem NENHUM índice utilizável em nome/sobrenome, isso já
        # forçava um full table scan (EXPLAIN type=ALL); e sob REPEATABLE
        # READ (padrão do InnoDB), uma leitura de bloqueio (FOR UPDATE) que
        # faz table scan trava a tabela `funcionario` INTEIRA durante a
        # transação, não só a linha procurada -- medido ao vivo contra MySQL
        # real: 10 contas DIFERENTES logando simultaneamente levaram ~9x mais
        # tempo que uma chamada isolada, quando deveriam ser independentes. A
        # própria correção de segurança (lockout) tinha introduzido assim um
        # problema de disponibilidade pior do que o resolvido.
        #
        # A correção tem DUAS partes, as duas necessárias:
        #   1) índice funcional em (LOWER(nome), LOWER(sobrenome))
        #      (ver migration.sql) -- cobre a expressão exata usada aqui.
        #   2) trocar `.ilike()` por `func.lower(col) == valor.lower()`
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
        # CORRIGIDO (CRÍTICO 2 da revisão desta trava): este SELECT ... FOR
        # UPDATE em si não tinha nenhum tratamento de OperationalError --
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
                    func.lower(Funcionario.nome) == nome.lower(),
                    func.lower(Funcionario.sobrenome) == sobrenome.lower(),
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

        # CORRIGIDO (CRÍTICO 3 da revisão desta trava): até aqui, só o login
        # BEM-SUCEDIDO zerava `tentativas_login_falhas`/`bloqueado_ate` (ver
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
            # AVALIADO (IMPORTANTE 3 da revisão desta trava): só este ramo
            # ("conta existe, desbloqueada, senha errada") faz um commit
            # extra aqui (pra persistir o incremento do contador) -- os
            # outros ramos que levam ao mesmo 401 genérico (usuário
            # inexistente, sem senha definida, já bloqueada) não passam por
            # aqui, então respondem sem esse round-trip de escrita extra.
            # Isso cria uma pequena descontinuidade de tempo que, em teoria,
            # poderia ajudar a distinguir de fora o momento em que uma conta
            # passa a existir/estar desbloqueada vs os outros estados.
            # DECISÃO: aceito como risco baixo, sem equalizar, porque (1) o
            # custo DOMINANTE do tempo de resposta já é o bcrypt de
            # verificar_senha() -- dezenas a centenas de ms -- e esse custo
            # já é igual em TODOS os ramos (HASH_DUMMY_LOGIN garante que
            # verificar_senha() roda sempre, ver mais acima); o commit extra
            # aqui é uma única escrita numa linha já localizada pelo índice
            # (CRÍTICO 1), ordens de grandeza mais rápido que o bcrypt, então
            # uma fração pequena do tempo total; (2) distinguir essa
            # diferença de fora exigiria medir muitas requisições com
            # precisão maior que o jitter normal de rede -- fora do modelo
            # de ameaça realista para este projeto acadêmico/pessoal.
            # Equalizar de verdade (ex.: forçar algum round-trip de escrita
            # equivalente nos outros 3 ramos) adicionaria complexidade/risco
            # de bug novo pra fechar uma brecha residual de baixíssimo
            # impacto prático -- não foi considerado valer a pena.
            funcionario.tentativas_login_falhas += 1
            if funcionario.tentativas_login_falhas >= LOGIN_MAX_TENTATIVAS:
                funcionario.bloqueado_ate = agora + timedelta(minutes=LOGIN_BLOQUEIO_MINUTOS)
            session.add(funcionario)
            _com_tratamento_operational_error(session, session.commit, mensagem_erro_transitorio)

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
            "nome_completo": f"{funcionario.nome} {funcionario.sobrenome}",
            "lembrete_senha": lembrete_senha,
            "senha_temporaria": funcionario.senha_temporaria,
        }


def criar_funcionario(dados: FuncionarioCreate):
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
        )
        try:
            session.add(funcionario)
            session.flush()
            _registrar_historico(session, funcionario.id, password_hash)
            session.commit()
            session.refresh(funcionario)
            return funcionario
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao criar funcionário")


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

        if dados.senha:
            if _senha_ja_usada(session, funcionario_id, dados.senha):
                raise HTTPException(
                    status_code=400,
                    detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
                )
            funcionario.password_hash = hash_senha(dados.senha)
            funcionario.senha_atualizada_em = datetime.now(timezone.utc)
            _registrar_historico(session, funcionario_id, funcionario.password_hash)
            # IMPORTANTE 1 da revisão de fix/login-rate-limiting -- ver
            # docstring de _resetar_lockout: reset manual de senha via RH/
            # admin também precisa liberar um lockout em andamento, senão a
            # vítima continua travada mesmo com a senha já corrigida.
            _resetar_lockout(funcionario)

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
        funcionario = session.get(Funcionario, funcionario_id)
        if not funcionario:
            raise HTTPException(status_code=404, detail="Funcionário não encontrado")

        agora = datetime.now(timezone.utc)

        # CORRIGIDO (IMPORTANTE 2 da revisão de fix/login-rate-limiting):
        # este endpoint verificava a senha ATUAL sem nenhum limite de
        # tentativas -- alguém com um token roubado (mas sem saber a senha
        # atual) podia tentar adivinhar indefinidamente, sem nenhum
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
        # ASSIMETRIA INTENCIONAL vs login: aqui, uma senha_atual CORRETA
        # sempre passa, MESMO com a conta `bloqueado_ate` ativo (diferente
        # de autenticar_funcionario, que rejeita até senha certa durante o
        # bloqueio). Isso é necessário pro próprio IMPORTANTE 1 funcionar
        # neste endpoint: sem isso, a vítima de um lockout malicioso
        # (alguém martelando senha errada contra ela via /login OU via este
        # mesmo endpoint) nunca conseguiria chegar até o ponto que reseta o
        # lockout (_resetar_lockout mais abaixo) enquanto o bloqueio
        # estivesse ativo -- o IMPORTANTE 1 ficaria inalcançável aqui.
        # Aceitável porque este endpoint já exige uma prova de identidade
        # mais forte que o login sozinho: um JWT válido para ESTE
        # funcionário_id específico (que só existe se alguém já fez login
        # com sucesso antes, dentro da validade do token) -- diferente do
        # login, que é público e não exige nenhuma prova prévia.
        bloqueado = _esta_bloqueado(funcionario, agora)

        # Mesmo reset de CRÍTICO 3: se o bloqueio já expirou só pelo tempo
        # (sem uma troca de senha bem-sucedida depois), zera o contador
        # antigo antes de processar esta tentativa.
        if funcionario.bloqueado_ate is not None and not bloqueado:
            _resetar_lockout(funcionario)

        senha_atual_confere = bool(
            funcionario.password_hash and verificar_senha(dados.senha_atual, funcionario.password_hash)
        )

        if not senha_atual_confere:
            # Mesma decisão do login: tentativas adicionais durante uma
            # janela de bloqueio já ativa não reiniciam a contagem nem
            # estendem `bloqueado_ate` (evita manter a conta bloqueada
            # indefinidamente só martelando tentativas erradas contra ela).
            if not bloqueado:
                funcionario.tentativas_login_falhas += 1
                if funcionario.tentativas_login_falhas >= LOGIN_MAX_TENTATIVAS:
                    funcionario.bloqueado_ate = agora + timedelta(minutes=LOGIN_BLOQUEIO_MINUTOS)
                session.add(funcionario)
                try:
                    session.commit()
                except OperationalError as exc:
                    session.rollback()
                    tratar_operational_error(exc, "Não foi possível processar a solicitação, tente novamente")
            raise HTTPException(status_code=401, detail="Senha atual incorreta")

        if _senha_ja_usada(session, funcionario_id, dados.nova_senha):
            raise HTTPException(
                status_code=400,
                detail="Nova senha não pode ser igual às 3 últimas senhas utilizadas",
            )

        novo_hash = hash_senha(dados.nova_senha)
        funcionario.password_hash = novo_hash
        funcionario.senha_atualizada_em = datetime.now(timezone.utc)
        funcionario.senha_temporaria = False
        _registrar_historico(session, funcionario_id, novo_hash)
        # IMPORTANTE 1 -- ver docstring de _resetar_lockout.
        _resetar_lockout(funcionario)

        try:
            session.commit()
            return {"msg": "Senha alterada com sucesso"}
        except OperationalError as exc:
            session.rollback()
            tratar_operational_error(exc, "Não foi possível processar a solicitação, tente novamente")
        except Exception:
            session.rollback()
            raise HTTPException(status_code=500, detail="Erro ao alterar senha")


def recuperar_senha(dados: RecuperarSenhaRequest):
    with Session(engine) as session:
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
        # IMPORTANTE 1 da revisão de fix/login-rate-limiting -- ver
        # docstring de _resetar_lockout: recuperação de senha por e-mail
        # também precisa liberar um lockout em andamento, senão a vítima
        # continua travada mesmo com a senha nova já na caixa de entrada.
        _resetar_lockout(funcionario)

        try:
            session.commit()
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
