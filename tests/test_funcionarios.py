import pytest
from datetime import date, datetime, timezone, timedelta
from fastapi import HTTPException
from unittest.mock import patch
from sqlmodel import Session

from repository.funcionarios import (
    autenticar_funcionario, criar_funcionario, listar_funcionarios,
    buscar_funcionario, atualizar_funcionario, deletar_funcionario,
    renovar_token, trocar_senha, recuperar_senha,
    _senha_ja_usada, _registrar_historico, MSG_LOGIN_INVALIDO,
)
from schemas.schemas import (
    LoginRequest, FuncionarioCreate, TrocarSenhaRequest, RecuperarSenhaRequest,
)
from utils.database import Funcionario, HistoricoSenha
from utils.security import LOGIN_MAX_TENTATIVAS, LOGIN_BLOQUEIO_MINUTOS
from conftest import make_setor, make_funcionario, pwd

ENDERECO = dict(
    cep="01310100", estado="SP", cidade="SP",
    bairro="Centro", rua="Paulista", numero="100",
)


def _dados_create(setor_id, cpf="52998224725", email="joao@test.com", senha="Test@123"):
    return FuncionarioCreate(
        nome="Joao", sobrenome="Silva",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor_id, senha=senha,
        cpf=cpf, email=email, **ENDERECO,
    )


# ── autenticar_funcionario ────────────────────────────────────────────────────

def test_login_sucesso(engine, session):
    setor = make_setor(session, tipo="rh")
    make_funcionario(session, "joao", "silva", setor.id, cpf="52998224725", email="j@test.com")
    res = autenticar_funcionario(LoginRequest(username="joao.silva", senha="Test@123"))
    assert "token" in res
    assert res["lembrete_senha"] is False
    assert res["senha_temporaria"] is False


def test_login_formato_invalido(engine, session):
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="semPonto", senha="x"))
    assert exc.value.status_code == 401
    assert "Formato" in exc.value.detail


def test_login_usuario_nao_encontrado(engine, session):
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="nao.existe", senha="x"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_login_sem_senha_definida(engine, session):
    setor = make_setor(session, tipo="rh2")
    make_funcionario(session, "sem", "senha", setor.id, with_password=False)
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="sem.senha", senha="Test@123"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_login_senha_errada(engine, session):
    setor = make_setor(session, tipo="rh3")
    make_funcionario(session, "pedro", "certo", setor.id)
    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="pedro.certo", senha="SenhaErrada"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_login_nao_revela_enumeracao_de_usuario(engine, session):
    """
    Correção de segurança (fix/login-rate-limiting): usuário inexistente e
    usuário existente-mas-senha-errada precisam devolver EXATAMENTE a mesma
    mensagem e o mesmo status HTTP -- antes da correção, "Usuário não
    encontrado" vs "Senha incorreta" permitiam descobrir quais usernames
    existem no sistema só pela resposta do login.
    """
    setor = make_setor(session, tipo="rh_enum")
    make_funcionario(session, "existe", "mesmo", setor.id)

    with pytest.raises(HTTPException) as exc_inexistente:
        autenticar_funcionario(LoginRequest(username="nao.existe2", senha="QualquerSenha@1"))

    with pytest.raises(HTTPException) as exc_senha_errada:
        autenticar_funcionario(LoginRequest(username="existe.mesmo", senha="SenhaErrada@1"))

    assert exc_inexistente.value.status_code == exc_senha_errada.value.status_code == 401
    assert exc_inexistente.value.detail == exc_senha_errada.value.detail == MSG_LOGIN_INVALIDO


def test_login_lembrete_senha_um_ano(engine, session):
    setor = make_setor(session, tipo="rh4")
    make_funcionario(session, "ana", "velha", setor.id, password_age_days=366)
    res = autenticar_funcionario(LoginRequest(username="ana.velha", senha="Test@123"))
    assert res["lembrete_senha"] is True


def test_login_lembrete_senha_menos_de_um_ano(engine, session):
    setor = make_setor(session, tipo="rh5")
    make_funcionario(session, "ana", "nova", setor.id, password_age_days=200)
    res = autenticar_funcionario(LoginRequest(username="ana.nova", senha="Test@123"))
    assert res["lembrete_senha"] is False


def test_login_sem_data_senha(engine, session):
    setor = make_setor(session, tipo="rh6")
    f = make_funcionario(session, "sem", "data", setor.id)
    with Session(engine) as s:
        func = s.get(type(f), f.id)
        func.senha_atualizada_em = None
        s.add(func)
        s.commit()
    res = autenticar_funcionario(LoginRequest(username="sem.data", senha="Test@123"))
    assert res["lembrete_senha"] is False


def test_login_senha_temporaria_true(engine, session):
    setor = make_setor(session, tipo="rh7")
    make_funcionario(session, "temp", "user", setor.id, senha_temporaria=True)
    res = autenticar_funcionario(LoginRequest(username="temp.user", senha="Test@123"))
    assert res["senha_temporaria"] is True


def test_login_case_insensitive(engine, session):
    setor = make_setor(session, tipo="rh8")
    make_funcionario(session, "maria", "jose", setor.id)
    res = autenticar_funcionario(LoginRequest(username="MARIA.JOSE", senha="Test@123"))
    assert "token" in res


def test_login_gera_novo_token_a_cada_vez(engine, session):
    setor = make_setor(session, tipo="rh9")
    make_funcionario(session, "log", "duplo", setor.id)
    r1 = autenticar_funcionario(LoginRequest(username="log.duplo", senha="Test@123"))
    r2 = autenticar_funcionario(LoginRequest(username="log.duplo", senha="Test@123"))
    assert r1["token"] != r2["token"]


# ── lockout de login (fix/login-rate-limiting) ─────────────────────────────────

def test_login_bloqueia_apos_max_tentativas(engine, session):
    """
    Correção do achado "zero rate-limiting" da varredura de segurança (20
    tentativas de login seguidas contra a mesma conta em ~4s eram todas
    processadas normalmente antes desta correção, sem nenhum 429/bloqueio).
    Depois de LOGIN_MAX_TENTATIVAS tentativas de senha errada seguidas, a
    conta fica com `bloqueado_ate` no futuro.
    """
    setor = make_setor(session, tipo="lock_login1")
    f = make_funcionario(session, "bruto", "forca", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException) as exc:
            autenticar_funcionario(LoginRequest(username="bruto.forca", senha="SenhaErrada@1"))
        assert exc.value.status_code == 401
        assert exc.value.detail == MSG_LOGIN_INVALIDO

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == LOGIN_MAX_TENTATIVAS
    assert func.bloqueado_ate is not None
    assert func.bloqueado_ate.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def test_login_bloqueado_rejeita_mesmo_com_senha_certa(engine, session):
    """
    Uma vez bloqueada, a conta continua rejeitando login até o tempo de
    bloqueio passar -- mesmo que a senha enviada esteja correta.
    """
    setor = make_setor(session, tipo="lock_login2")
    make_funcionario(session, "ja", "bloqueado", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="ja.bloqueado", senha="SenhaErrada@1"))

    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="ja.bloqueado", senha="Test@123"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_login_nao_incrementa_tentativas_durante_bloqueio(engine, session):
    """
    Decisão documentada em autenticar_funcionario: tentativas adicionais
    durante a janela de bloqueio NÃO reiniciam a contagem nem estendem
    `bloqueado_ate` -- evita que um atacante consiga manter a conta
    bloqueada indefinidamente só martelando login contra ela.
    """
    setor = make_setor(session, tipo="lock_login3")
    f = make_funcionario(session, "trava", "fixa", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="trava.fixa", senha="SenhaErrada@1"))

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    tentativas_apos_bloqueio = func.tentativas_login_falhas
    bloqueado_ate_original = func.bloqueado_ate

    for _ in range(3):
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="trava.fixa", senha="SenhaErrada@1"))
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="trava.fixa", senha="Test@123"))

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == tentativas_apos_bloqueio
    assert func.bloqueado_ate == bloqueado_ate_original


def test_login_sucesso_zera_tentativas_e_bloqueio(engine, session):
    setor = make_setor(session, tipo="lock_login4")
    f = make_funcionario(session, "reseta", "contador", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS - 1):
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="reseta.contador", senha="SenhaErrada@1"))

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == LOGIN_MAX_TENTATIVAS - 1
    assert func.bloqueado_ate is None

    res = autenticar_funcionario(LoginRequest(username="reseta.contador", senha="Test@123"))
    assert "token" in res

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None


def test_login_bloqueio_expira_passado_o_tempo(engine, session):
    """O bloqueio é TEMPORÁRIO: passado `bloqueado_ate`, a senha certa volta a funcionar normalmente."""
    setor = make_setor(session, tipo="lock_login5")
    f = make_funcionario(session, "expirou", "bloqueio", setor.id)
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.add(func)
        s.commit()

    res = autenticar_funcionario(LoginRequest(username="expirou.bloqueio", senha="Test@123"))
    assert "token" in res

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None


def test_login_bloqueio_expirado_reseta_contador_antes_de_tentativa_errada(engine, session):
    """
    CRÍTICO 3 da revisão de fix/login-rate-limiting: test_login_bloqueio_
    expira_passado_o_tempo (acima) só cobria o caso de a próxima tentativa
    ser com a senha CERTA. Mas se `bloqueado_ate` já passou e a PRÓXIMA
    tentativa é uma senha ERRADA (mesmo uma só, isolada, dias depois), o
    contador antigo (ex.: LOGIN_MAX_TENTATIVAS, deixado pelo bloqueio
    anterior) não podia continuar de onde parou -- sem o reset explícito
    quando o bloqueio expira, essa tentativa isolada somaria
    LOGIN_MAX_TENTATIVAS + 1 e rebloquearia a conta instantaneamente, em
    vez de dar as LOGIN_MAX_TENTATIVAS tentativas completas de novo (como
    aconteceria para qualquer conta que nunca tivesse sido bloqueada antes).
    """
    setor = make_setor(session, tipo="lock_login_reset_errada")
    f = make_funcionario(session, "bloqueio", "expirado2", setor.id)
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.add(func)
        s.commit()

    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="bloqueio.expirado2", senha="SenhaErrada@1"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 1, (
        "o bloqueio expirado deveria ter resetado o contador para 0 ANTES de "
        "contar esta tentativa errada -- não acumular a partir do valor antigo "
        "e rebloquear a conta instantaneamente"
    )
    assert func.bloqueado_ate is None


def test_login_usuario_inexistente_nunca_gera_erro_mesmo_apos_varias_tentativas(engine, session):
    """
    Decisão de escopo (ver autenticar_funcionario): não existe linha/conta
    pra bloquear quando o username não existe, então várias tentativas
    contra um username inexistente não incrementam nada nem geram erro
    inesperado -- só o 401 genérico de sempre, em todas as tentativas. Um
    rate-limit por IP foi avaliado e descartado como desproporcional ao
    escopo deste projeto acadêmico/pessoal (sem proxy/observabilidade de IP
    hoje); fica documentado como limitação aceita.
    """
    for _ in range(LOGIN_MAX_TENTATIVAS + 5):
        with pytest.raises(HTTPException) as exc:
            autenticar_funcionario(LoginRequest(username="fantasma.inexistente", senha="QualquerSenha@1"))
        assert exc.value.status_code == 401
        assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_login_sem_senha_definida_nao_conta_tentativa(engine, session):
    """Funcionário sem password_hash não tem senha pra 'forçar' -- essa tentativa não soma no contador."""
    setor = make_setor(session, tipo="lock_login6")
    f = make_funcionario(session, "sem", "senha2", setor.id, with_password=False)

    for _ in range(LOGIN_MAX_TENTATIVAS + 2):
        with pytest.raises(HTTPException) as exc:
            autenticar_funcionario(LoginRequest(username="sem.senha2", senha="QualquerSenha@1"))
        assert exc.value.detail == MSG_LOGIN_INVALIDO

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None


# ── trava de concorrência (with_for_update) ─────────────────────────────────────

def test_autenticar_consulta_funcionario_com_lock_for_update(engine, session, monkeypatch):
    """
    Mesma lógica de test_criar_venda_consulta_produto_com_lock_for_update
    (tests/test_vendas.py): SQLite ignora `SELECT ... FOR UPDATE` (a
    cláusula é apenas ignorada pelo driver), então não dá para reproduzir o
    bloqueio real de linha do MySQL (produção) dentro da suíte de testes.
    Em vez de simular um lock que o SQLite não tem como garantir, este
    teste verifica o contrato que realmente importa: a consulta que
    `autenticar_funcionario` faz ao funcionário pede o lock pessimista.
    Isso é verificado compilando a própria instrução para o dialeto do
    MySQL e conferindo que `FOR UPDATE` aparece no SQL gerado -- se alguém
    remover o `.with_for_update()` do código, este teste quebra.

    Sem essa trava, duas tentativas de login simultâneas contra a MESMA
    conta poderiam ambas ler `tentativas_login_falhas` com o mesmo valor
    "antigo" e incrementar a partir dele (lost update), atrasando o
    bloqueio da conta sob um ataque de força bruta paralelo.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lock_for_update1")
    make_funcionario(session, "trava", "login", setor.id)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    autenticar_funcionario(LoginRequest(username="trava.login", senha="Test@123"))

    assert statements, "esperava que autenticar_funcionario consultasse o funcionário via session.exec"

    for statement in statements:
        assert getattr(statement, "_for_update_arg", None) is not None, (
            "a consulta ao funcionário em autenticar_funcionario precisa usar "
            "with_for_update() para travar a linha e evitar race condition no "
            "contador de tentativas em logins simultâneos"
        )

    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada


def test_autenticar_consulta_usa_lower_sql_dos_dois_lados(engine, session, monkeypatch):
    """
    A consulta comparava
    `func.lower(Funcionario.nome) == nome.lower()` -- o lado esquerdo vira
    `LOWER()` do MySQL (resolvido em cima do valor armazenado), mas o lado
    direito usava `.lower()` do PYTHON, aplicado antes de virar parâmetro da
    query. Python e MySQL não garantem o MESMO case-folding para todo
    caractere Unicode -- se divergissem para algum caractere específico, um
    usuário legítimo tomaria 401 mesmo com a senha certa. Corrigido aplicando
    `func.lower()` nos dois lados (MySQL faz o case-folding dos dois, nunca
    mistura com Python). Confirma, inspecionando o SQL compilado para o
    dialeto MySQL, que `LOWER()` envolve o parâmetro em AMBOS os lados da
    comparação (duas ocorrências de `lower(%s)`, uma por coluna).
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lower_sql1")
    make_funcionario(session, "maria", "lower", setor.id)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    autenticar_funcionario(LoginRequest(username="maria.lower", senha="Test@123"))

    assert statements
    compilada = str(statements[0].compile(dialect=mysql.dialect()))
    assert compilada.count("lower(%s)") == 2, (
        "esperava LOWER() do MySQL envolvendo o parâmetro dos dois lados da "
        "comparação (nome e sobrenome) -- não misturar com .lower() do "
        f"Python no valor de entrada. SQL compilado: {compilada!r}"
    )


def test_trocar_senha_consulta_funcionario_com_lock_for_update(engine, session, monkeypatch):
    """
    Este endpoint lia o funcionário com `session.get(Funcionario, funcionario_id)`
    (sem trava nenhuma) e fazia o mesmo padrão "ler, incrementar em memória,
    escrever" que o login tinha antes da correção equivalente lá.
    Reproduzido ao vivo (threads reais contra MySQL real, descartado depois):
    20 tentativas simultâneas de senha_atual errada contra a MESMA conta
    deixavam o contador em 1-2 (nunca nos 5 esperados) -- a conta nunca
    bloqueava de verdade.

    Mesma limitação de ambiente que test_autenticar_consulta_funcionario_com_
    lock_for_update: SQLite (usado pela suíte) ignora `SELECT ... FOR UPDATE`,
    então não reproduz o lock real de linha do MySQL aqui -- o teste verifica
    o contrato que importa (a consulta pede o lock pessimista), compilando a
    própria instrução para o dialeto MySQL.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.dialects import mysql

    setor = make_setor(session, tipo="lock_for_update_troca")
    f = make_funcionario(session, "trava", "trocasenha", setor.id)

    statements = []
    orig_exec = sqlmodel_mod.Session.exec

    def espiar_exec(self, statement, *args, **kwargs):
        statements.append(statement)
        return orig_exec(self, statement, *args, **kwargs)

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", espiar_exec)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaSenha@456"))

    assert statements, "esperava que trocar_senha consultasse o funcionário via session.exec"

    # A primeira consulta é a do funcionário (com lock); as seguintes (ex.:
    # _senha_ja_usada consultando HistoricoSenha) não usam -- nem precisam de
    # -- with_for_update(), então só a primeira é verificada aqui.
    primeira = statements[0]
    assert getattr(primeira, "_for_update_arg", None) is not None, (
        "a consulta ao funcionário em trocar_senha precisa usar "
        "with_for_update() para travar a linha e evitar race condition no "
        "contador de tentativas sob chamadas simultâneas a este endpoint"
    )

    compilada = str(primeira.compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in compilada


# ── trava de concorrência (deadlock) ────────────────────────────────────────────

def test_login_deadlock_mysql_vira_409_nao_500(engine, session, monkeypatch):
    """
    Mesmo padrão de test_criar_venda_deadlock_mysql_vira_409_nao_500
    (tests/test_vendas.py): se o commit do login colidir com outra
    transação que trave a mesma linha em ordem diferente, o MySQL recusa
    com OperationalError (código 1213, deadlock). autenticar_funcionario
    captura especificamente esse erro e devolve um 409 limpo, em vez de
    deixar vazar um 500 cru. Testado no commit que grava o incremento de
    `tentativas_login_falhas` (o commit novo introduzido pelo lockout) --
    o commit do caminho de sucesso tem a mesma proteção, coberto por
    test_login_outro_operational_error_nao_vira_409 logo abaixo.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="deadlock_login1")
    make_funcionario(session, "trava", "deadlock", setor.id)

    class FakeOrigDeadlock(Exception):
        args = (1213, "Deadlock found when trying to get lock; try restarting transaction")

    chamadas = {"n": 0}

    def commit_que_falha_com_deadlock(self, *args, **kwargs):
        chamadas["n"] += 1
        raise OperationalError("COMMIT", {}, FakeOrigDeadlock())

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha_com_deadlock)

    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="trava.deadlock", senha="SenhaErrada@1"))

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()
    assert chamadas["n"] == 1


def test_login_outro_operational_error_nao_vira_409(engine, session, monkeypatch):
    """O tratamento é específico do código 1213 -- outro OperationalError (ex.: perda de conexão) continua propagando."""
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="deadlock_login2")
    make_funcionario(session, "outro", "erro", setor.id)

    class FakeOrigOutroErro(Exception):
        args = (2006, "MySQL server has gone away")

    def commit_que_falha_outro_erro(self, *args, **kwargs):
        raise OperationalError("COMMIT", {}, FakeOrigOutroErro())

    monkeypatch.setattr(sqlmodel_mod.Session, "commit", commit_que_falha_outro_erro)

    with pytest.raises(OperationalError):
        autenticar_funcionario(LoginRequest(username="outro.erro", senha="Test@123"))


def test_login_select_lock_wait_timeout_vira_409_nao_500(engine, session, monkeypatch):
    """
    CRÍTICO 2 da revisão de fix/login-rate-limiting: o SELECT ... FOR UPDATE
    do login (que busca o funcionário e trava a linha) não tinha nenhum
    tratamento de OperationalError -- só os commits tinham. Reproduzido ao
    vivo contra MySQL real (innodb_lock_wait_timeout reduzido só para o
    teste, igual o painel de revisão fez): um lock-wait-timeout de verdade
    (código 1205 -- outra transação segurando a mesma linha por tempo
    suficiente) escapava cru como um 500. Agora o SELECT também está
    protegido, e `utils/erros_banco.py` trata 1205 com a mesma resposta 409
    já usada para 1213 (deadlock) -- do ponto de vista do cliente são o
    mesmo tipo de falha transitória de concorrência.
    """
    import sqlmodel as sqlmodel_mod
    from sqlalchemy.exc import OperationalError

    setor = make_setor(session, tipo="lock_wait_login1")
    make_funcionario(session, "trava", "espera", setor.id)

    class FakeOrigLockWaitTimeout(Exception):
        args = (1205, "Lock wait timeout exceeded; try restarting transaction")

    chamadas = {"n": 0}

    def exec_que_falha_com_lock_wait_timeout(self, statement, *args, **kwargs):
        chamadas["n"] += 1
        raise OperationalError("SELECT", {}, FakeOrigLockWaitTimeout())

    monkeypatch.setattr(sqlmodel_mod.Session, "exec", exec_que_falha_com_lock_wait_timeout)

    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="trava.espera", senha="Test@123"))

    assert exc.value.status_code == 409
    assert "tente novamente" in exc.value.detail.lower()
    assert chamadas["n"] == 1


# ── criar_funcionario ─────────────────────────────────────────────────────────

def test_criar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="est")
    dados = _dados_create(setor.id)
    f = criar_funcionario(dados)
    assert f.id is not None
    assert f.cpf == "52998224725"
    assert f.email == "joao@test.com"


def test_criar_funcionario_sem_senha(engine, session):
    setor = make_setor(session, tipo="est2")
    dados = _dados_create(setor.id, senha=None)
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "Senha" in exc.value.detail


def test_criar_funcionario_cpf_duplicado(engine, session):
    setor = make_setor(session, tipo="est3")
    make_funcionario(session, cpf="52998224725", email="a@test.com", setor_id=setor.id)
    dados = _dados_create(setor.id, cpf="52998224725", email="b@test.com")
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "CPF" in exc.value.detail


def test_criar_funcionario_email_duplicado(engine, session):
    setor = make_setor(session, tipo="est4")
    make_funcionario(session, cpf="11144477735", email="dup@test.com", setor_id=setor.id)
    dados = _dados_create(setor.id, cpf="52998224725", email="dup@test.com")
    with pytest.raises(HTTPException) as exc:
        criar_funcionario(dados)
    assert exc.value.status_code == 400
    assert "Email" in exc.value.detail


def test_criar_funcionario_registra_historico(engine, session):
    setor = make_setor(session, tipo="est5")
    dados = _dados_create(setor.id, cpf="52998224725", email="hist@test.com")
    f = criar_funcionario(dados)
    with Session(engine) as s:
        hist = s.exec(
            __import__("sqlmodel").select(HistoricoSenha).where(HistoricoSenha.funcionario_id == f.id)
        ).all()
    assert len(hist) == 1


def test_criar_funcionario_erro_interno(engine, session):
    setor = make_setor(session, tipo="est6")
    dados = _dados_create(setor.id, cpf="52998224725", email="err@test.com")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            criar_funcionario(dados)
        assert exc.value.status_code == 500


# ── listar / buscar ───────────────────────────────────────────────────────────

def test_listar_funcionarios_vazio(engine, session):
    assert listar_funcionarios() == []


def test_listar_funcionarios_multiplos(engine, session):
    setor = make_setor(session, tipo="lst")
    make_funcionario(session, setor_id=setor.id)
    make_funcionario(session, setor_id=setor.id)
    assert len(listar_funcionarios()) == 2


def test_buscar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="bsc")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = buscar_funcionario(f.id)
    assert resultado.id == f.id


def test_buscar_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        buscar_funcionario(9999)
    assert exc.value.status_code == 404


# ── atualizar_funcionario ─────────────────────────────────────────────────────

def test_atualizar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="upd")
    f = make_funcionario(session, nome="Antigo", setor_id=setor.id, cpf="52998224725", email="old@test.com")
    dados = FuncionarioCreate(
        nome="Novo", sobrenome="Silva",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha=None,
        cpf="52998224725", email="new@test.com", **ENDERECO,
    )
    resultado = atualizar_funcionario(f.id, dados)
    assert resultado.nome == "Novo"
    assert resultado.email == "new@test.com"


def test_atualizar_sem_senha_mantem_hash(engine, session):
    setor = make_setor(session, tipo="upd2")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="keep@test.com")
    hash_original = f.password_hash
    dados = _dados_create(setor.id, cpf="52998224725", email="keep@test.com", senha=None)
    atualizar_funcionario(f.id, dados)
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.password_hash == hash_original


def test_atualizar_com_nova_senha(engine, session):
    setor = make_setor(session, tipo="upd3")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="chg@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="chg@test.com", senha="Nova@123456")
    atualizar_funcionario(f.id, dados)
    res = autenticar_funcionario(LoginRequest(username="joao.silva", senha="Nova@123456"))
    assert "token" in res


def test_atualizar_com_nova_senha_reseta_lockout(engine, session):
    """
    IMPORTANTE 1 da revisão de fix/login-rate-limiting: reset manual de
    senha via RH/admin (atualizar_funcionario) também precisa liberar um
    lockout em andamento -- senão a vítima de um lockout malicioso
    continua travada mesmo com a senha já corrigida pelo RH.
    """
    setor = make_setor(session, tipo="upd_lockout")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rhreset@test.com")
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_BLOQUEIO_MINUTOS)
        s.add(func)
        s.commit()

    dados = _dados_create(setor.id, cpf="52998224725", email="rhreset@test.com", senha="NovaSenhaRH@999")
    atualizar_funcionario(f.id, dados)

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None

    res = autenticar_funcionario(LoginRequest(username="joao.silva", senha="NovaSenhaRH@999"))
    assert "token" in res


def test_atualizar_funcionario_inexistente(engine, session):
    setor = make_setor(session, tipo="upd4")
    dados = _dados_create(setor.id)
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(9999, dados)
    assert exc.value.status_code == 404


def test_atualizar_cpf_duplicado_outro_funcionario(engine, session):
    setor = make_setor(session, tipo="upd5")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="a@test.com")
    f2 = make_funcionario(session, setor_id=setor.id, cpf="11144477735", email="b@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="b@test.com")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f2.id, dados)
    assert exc.value.status_code == 400
    assert "CPF" in exc.value.detail


def test_atualizar_email_duplicado_outro_funcionario(engine, session):
    setor = make_setor(session, tipo="upd6")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="dup@test.com")
    f2 = make_funcionario(session, setor_id=setor.id, cpf="11144477735", email="b@test.com")
    dados = _dados_create(setor.id, cpf="11144477735", email="dup@test.com")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f2.id, dados)
    assert exc.value.status_code == 400
    assert "Email" in exc.value.detail


def test_atualizar_senha_historico_bloqueado(engine, session):
    setor = make_setor(session, tipo="upd7")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="hist2@test.com")
    dados = _dados_create(setor.id, cpf="52998224725", email="hist2@test.com", senha="Test@123")
    with pytest.raises(HTTPException) as exc:
        atualizar_funcionario(f.id, dados)
    assert exc.value.status_code == 400
    assert "últimas senhas" in exc.value.detail


def test_atualizar_erro_interno(engine, session):
    setor = make_setor(session, tipo="upd8")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="interr@test.com")
    dados = FuncionarioCreate(
        nome="X", sobrenome="Y",
        data_nascimento=date(1990, 1, 1),
        genero="M", possui_filhos=False,
        setor_id=setor.id, senha=None,
        cpf="52998224725", email="interr@test.com", **ENDERECO,
    )
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            atualizar_funcionario(f.id, dados)
        assert exc.value.status_code == 500


# ── deletar_funcionario ───────────────────────────────────────────────────────

def test_deletar_funcionario_sucesso(engine, session):
    setor = make_setor(session, tipo="del")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = deletar_funcionario(f.id)
    assert "deletado" in resultado["msg"]


def test_deletar_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        deletar_funcionario(9999)
    assert exc.value.status_code == 404


def test_deletar_funcionario_duas_vezes(engine, session):
    setor = make_setor(session, tipo="del2")
    f = make_funcionario(session, setor_id=setor.id)
    deletar_funcionario(f.id)
    with pytest.raises(HTTPException) as exc:
        deletar_funcionario(f.id)
    assert exc.value.status_code == 404


def test_deletar_erro_interno(engine, session):
    setor = make_setor(session, tipo="del3")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            deletar_funcionario(f.id)
        assert exc.value.status_code == 500


# ── renovar_token ─────────────────────────────────────────────────────────────

def test_renovar_token_sucesso(engine, session):
    setor = make_setor(session, tipo="ren")
    f = make_funcionario(session, setor_id=setor.id)
    resultado = renovar_token(f.id)
    assert "token" in resultado
    assert isinstance(resultado["token"], str)


def test_renovar_token_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        renovar_token(9999)
    assert exc.value.status_code == 404


def test_renovar_token_erro_interno(engine, session):
    setor = make_setor(session, tipo="ren2")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            renovar_token(f.id)
        assert exc.value.status_code == 500


# ── trocar_senha ──────────────────────────────────────────────────────────────

def test_trocar_senha_sucesso(engine, session):
    setor = make_setor(session, tipo="troca")
    f = make_funcionario(session, setor_id=setor.id)
    dados = TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaSenha@999")
    resultado = trocar_senha(f.id, dados)
    assert "sucesso" in resultado["msg"]


def test_trocar_senha_atual_errada(engine, session):
    setor = make_setor(session, tipo="troca2")
    f = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Errada@123", nova_senha="Nova@999"))
    assert exc.value.status_code == 401


def test_trocar_senha_reutilizacao_bloqueada(engine, session):
    setor = make_setor(session, tipo="troca3")
    f = make_funcionario(session, setor_id=setor.id)
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Test@123"))
    assert exc.value.status_code == 400
    assert "últimas senhas" in exc.value.detail


def test_trocar_senha_historico_tres_ultimas(engine, session):
    setor = make_setor(session, tipo="troca4")
    f = make_funcionario(session, setor_id=setor.id)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Segunda@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Segunda@999", nova_senha="Terceira@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Terceira@999", nova_senha="Quarta@999"))
    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Quarta@999", nova_senha="Segunda@999"))
    assert exc.value.status_code == 400


def test_trocar_senha_depois_de_quatro_trocas_permite_primeira(engine, session):
    setor = make_setor(session, tipo="troca5")
    f = make_funcionario(session, setor_id=setor.id)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Segunda@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Segunda@999", nova_senha="Terceira@999"))
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Terceira@999", nova_senha="Quarta@999"))
    resultado = trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Quarta@999", nova_senha="Test@123"))
    assert "sucesso" in resultado["msg"]


def test_trocar_senha_marca_temporaria_false(engine, session):
    setor = make_setor(session, tipo="troca6")
    f = make_funcionario(session, setor_id=setor.id, senha_temporaria=True)
    trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Nova@99999"))
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.senha_temporaria is False


def test_trocar_senha_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        trocar_senha(9999, TrocarSenhaRequest(senha_atual="x", nova_senha="y"))
    assert exc.value.status_code == 404


def test_trocar_senha_erro_interno(engine, session):
    setor = make_setor(session, tipo="troca7")
    f = make_funcionario(session, setor_id=setor.id)
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Nova@99999"))
        assert exc.value.status_code == 500


# ── trocar_senha -- lockout (IMPORTANTE 1 e 2 da revisão de fix/login-rate-limiting) ──

def test_trocar_senha_sucesso_reseta_lockout_ja_expirado(engine, session):
    """
    IMPORTANTE 1: trocar_senha muda o password_hash mas, antes desta
    correção, não tocava em tentativas_login_falhas/bloqueado_ate -- mesmo
    com a senha corrigida, a vítima de um lockout malicioso (via /login)
    continuava travada os minutos inteiros. Com a senha_atual CORRETA, a
    troca bem-sucedida zera o lockout de uma conta cujo bloqueio já EXPIROU
    só pelo tempo (diferente de uma conta ainda ATIVAMENTE bloqueada, que é
    rejeitada antes mesmo de chegar aqui -- ver
    test_trocar_senha_rejeitada_mesmo_com_senha_correta_durante_bloqueio).
    """
    setor = make_setor(session, tipo="troca_lockout1")
    f = make_funcionario(session, setor_id=setor.id)
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)  # já expirado
        s.add(func)
        s.commit()

    resultado = trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaSenha@999"))
    assert "sucesso" in resultado["msg"]

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None


def test_trocar_senha_errada_repetida_bloqueia_conta(engine, session):
    """
    IMPORTANTE 2: trocar-senha verificava a senha ATUAL sem nenhum limite
    de tentativas -- alguém com um token roubado (mas sem saber a senha
    atual) podia tentar adivinhar indefinidamente. Depois de
    LOGIN_MAX_TENTATIVAS tentativas erradas seguidas AQUI, a conta fica
    bloqueada -- reaproveitando a mesma infraestrutura do lockout do login.
    """
    setor = make_setor(session, tipo="troca_lockout2")
    f = make_funcionario(session, setor_id=setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException) as exc:
            trocar_senha(f.id, TrocarSenhaRequest(senha_atual="SenhaErrada@1", nova_senha="Nova@99999"))
        assert exc.value.status_code == 401

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == LOGIN_MAX_TENTATIVAS
    assert func.bloqueado_ate is not None
    assert func.bloqueado_ate.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # Mesma decisão do login: martelar mais tentativas erradas durante o
    # bloqueio não estende bloqueado_ate nem incrementa mais o contador.
    bloqueado_ate_original = func.bloqueado_ate
    with pytest.raises(HTTPException):
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="OutraErrada@1", nova_senha="Nova@99999"))
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == LOGIN_MAX_TENTATIVAS
    assert func.bloqueado_ate == bloqueado_ate_original


def test_trocar_senha_bloqueio_tambem_afeta_login(engine, session):
    """
    Confirma a decisão de reaproveitar a MESMA infraestrutura: um lockout
    disparado via trocar-senha (senha atual errada repetida) também
    bloqueia o /login dessa conta, e vice-versa -- é o mesmo
    funcionário/conta, os mesmos campos.
    """
    setor = make_setor(session, tipo="troca_lockout3")
    f = make_funcionario(session, "bloqueio", "cruzado", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException):
            trocar_senha(f.id, TrocarSenhaRequest(senha_atual="SenhaErrada@1", nova_senha="Nova@99999"))

    with pytest.raises(HTTPException) as exc:
        autenticar_funcionario(LoginRequest(username="bloqueio.cruzado", senha="Test@123"))
    assert exc.value.status_code == 401
    assert exc.value.detail == MSG_LOGIN_INVALIDO


def test_trocar_senha_rejeitada_mesmo_com_senha_correta_durante_bloqueio(engine, session):
    """
    Simétrico ao login (ver comentário em trocar_senha): com a conta
    bloqueada por força bruta no /login, trocar_senha rejeita mesmo com a
    senha_atual CORRETA, sem sequer verificá-la -- caso contrário, alguém
    com um token roubado poderia continuar testando a senha atual à vontade
    enquanto a conta estivesse bloqueada, tornando o lockout deste endpoint
    cosmético contra o próprio ataque que ele existe pra conter. A
    recuperação durante o bloqueio passa por `recuperar_senha` (e-mail) ou
    `atualizar_funcionario` (RH/admin), não mais por este endpoint.
    """
    setor = make_setor(session, tipo="troca_lockout4")
    f = make_funcionario(session, "bloqueado", "porlogin", setor.id)

    for _ in range(LOGIN_MAX_TENTATIVAS):
        with pytest.raises(HTTPException):
            autenticar_funcionario(LoginRequest(username="bloqueado.porlogin", senha="SenhaErrada@1"))

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.bloqueado_ate is not None
    bloqueado_ate_original = func.bloqueado_ate
    tentativas_original = func.tentativas_login_falhas

    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="NovaSenha@999"))
    assert exc.value.status_code == 401

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    # Rejeitado sem sequer tocar no contador/bloqueio -- a senha nunca foi
    # verificada.
    assert func.tentativas_login_falhas == tentativas_original
    assert func.bloqueado_ate == bloqueado_ate_original


def test_trocar_senha_reset_de_lockout_expirado_persiste_mesmo_com_senha_reutilizada(engine, session):
    """
    Cenário: bloqueio já EXPIRADO só pelo tempo (contador alto,
    `bloqueado_ate` no passado, sem nenhuma troca de senha bem-sucedida
    depois) + senha_atual CERTA + nova_senha igual a uma das últimas 3
    (dispara 400 de reuso). Antes desta correção, o reset do lockout (feito
    só em memória no topo de trocar_senha) nunca era persistido nesse
    caminho -- a sessão saía pelo 400 sem nenhum commit alcançar o
    `funcionario`, recriando o mesmo bug do CRÍTICO 3 do login (bloqueio
    "preso" além do tempo configurado) só que por este caminho específico.
    Confirma que, mesmo recebendo o 400 esperado, o contador fica resetado
    no banco depois.
    """
    setor = make_setor(session, tipo="troca_lockout5")
    f = make_funcionario(session, "reset", "expirado", setor.id)

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) - timedelta(minutes=1)  # já expirado
        s.add(func)
        s.commit()

    with pytest.raises(HTTPException) as exc:
        trocar_senha(f.id, TrocarSenhaRequest(senha_atual="Test@123", nova_senha="Test@123"))
    assert exc.value.status_code == 400
    assert "últimas senhas" in exc.value.detail

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0, (
        "o reset do lockout expirado precisa ser persistido mesmo quando a "
        "checagem de reuso de senha dispara um 400 em seguida"
    )
    assert func.bloqueado_ate is None


# ── recuperar_senha ───────────────────────────────────────────────────────────

def test_recuperar_senha_sucesso(engine, session):
    setor = make_setor(session, tipo="rec")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec@test.com")

    with patch("repository.funcionarios.enviar_email") as mock_email:
        resultado = recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    mock_email.assert_called_once()
    assert "enviada" in resultado["msg"]


def test_recuperar_senha_marca_temporaria(engine, session):
    setor = make_setor(session, tipo="rec2")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec2@test.com")
    with patch("repository.funcionarios.enviar_email"):
        recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    with Session(engine) as s:
        func = s.get(type(f), f.id)
    assert func.senha_temporaria is True


def test_recuperar_senha_reseta_lockout(engine, session):
    """
    IMPORTANTE 1 da revisão de fix/login-rate-limiting: recuperação de
    senha por e-mail também precisa liberar um lockout em andamento --
    senão a vítima continua travada mesmo com a senha nova já na caixa de
    entrada.
    """
    setor = make_setor(session, tipo="rec_lockout")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="reclock@test.com")
    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
        func.tentativas_login_falhas = LOGIN_MAX_TENTATIVAS
        func.bloqueado_ate = datetime.now(timezone.utc) + timedelta(minutes=LOGIN_BLOQUEIO_MINUTOS)
        s.add(func)
        s.commit()

    with patch("repository.funcionarios.enviar_email"):
        recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))

    with Session(engine) as s:
        func = s.get(Funcionario, f.id)
    assert func.tentativas_login_falhas == 0
    assert func.bloqueado_ate is None


def test_recuperar_senha_funcionario_inexistente(engine, session):
    with pytest.raises(HTTPException) as exc:
        recuperar_senha(RecuperarSenhaRequest(cpf="00000000000"))
    assert exc.value.status_code == 404


def test_recuperar_senha_sem_email(engine, session):
    setor = make_setor(session, tipo="rec3")
    f = make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec3@test.com")
    with Session(engine) as s:
        func = s.get(type(f), f.id)
        func.email = None
        s.add(func)
        s.commit()
    with pytest.raises(HTTPException) as exc:
        recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 400


def test_recuperar_senha_email_nao_configurado(engine, session):
    setor = make_setor(session, tipo="rec4")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec4@test.com")
    with patch("repository.funcionarios.enviar_email", side_effect=RuntimeError("não configurado")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 503


def test_recuperar_senha_erro_smtp(engine, session):
    setor = make_setor(session, tipo="rec5")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec5@test.com")
    with patch("repository.funcionarios.enviar_email", side_effect=Exception("SMTP Error")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 500


def test_recuperar_senha_erro_db(engine, session):
    setor = make_setor(session, tipo="rec6")
    make_funcionario(session, setor_id=setor.id, cpf="52998224725", email="rec6@test.com")
    with patch.object(Session, "commit", side_effect=Exception("DB Error")):
        with pytest.raises(HTTPException) as exc:
            recuperar_senha(RecuperarSenhaRequest(cpf="52998224725"))
    assert exc.value.status_code == 500


# ── helpers internos ──────────────────────────────────────────────────────────

_MSG_ERRO_TRANSITORIO_TESTE = "Não foi possível processar a solicitação, tente novamente"


def test_senha_ja_usada_true(engine, session):
    setor = make_setor(session, tipo="hlp")
    f = make_funcionario(session, setor_id=setor.id)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "Test@123", _MSG_ERRO_TRANSITORIO_TESTE) is True


def test_senha_ja_usada_false(engine, session):
    setor = make_setor(session, tipo="hlp2")
    f = make_funcionario(session, setor_id=setor.id)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "SenhaNova@999", _MSG_ERRO_TRANSITORIO_TESTE) is False


def test_senha_ja_usada_sem_historico(engine, session):
    setor = make_setor(session, tipo="hlp3")
    f = make_funcionario(session, setor_id=setor.id, with_password=False)
    with Session(engine) as s:
        assert _senha_ja_usada(s, f.id, "Qualquer@123", _MSG_ERRO_TRANSITORIO_TESTE) is False
