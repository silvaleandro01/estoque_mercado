import pytest
from unittest.mock import patch, MagicMock


def test_enviar_email_sem_configuracao_lanca_erro(monkeypatch):
    import utils.email as email_mod
    monkeypatch.setattr(email_mod, "SMTP_HOST", "")
    monkeypatch.setattr(email_mod, "SMTP_USER", "")

    from utils.email import enviar_email
    with pytest.raises(RuntimeError, match="não configurado"):
        enviar_email("dest@test.com", "assunto", "corpo")


def test_enviar_email_sem_usuario_lanca_erro(monkeypatch):
    import utils.email as email_mod
    monkeypatch.setattr(email_mod, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(email_mod, "SMTP_USER", "")

    from utils.email import enviar_email
    with pytest.raises(RuntimeError):
        enviar_email("dest@test.com", "assunto", "corpo")


def test_enviar_email_sucesso(monkeypatch):
    import utils.email as email_mod
    monkeypatch.setattr(email_mod, "SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(email_mod, "SMTP_PORT", 587)
    monkeypatch.setattr(email_mod, "SMTP_USER", "remetente@test.com")
    monkeypatch.setattr(email_mod, "SMTP_PASSWORD", "senha")
    monkeypatch.setattr(email_mod, "SMTP_FROM", "remetente@test.com")

    mock_smtp = MagicMock()
    mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_smtp):
        from utils.email import enviar_email
        enviar_email("dest@test.com", "Assunto Teste", "Corpo do email")

    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with("remetente@test.com", "senha")
    mock_smtp.send_message.assert_called_once()


def test_enviar_email_erro_smtp_propaga(monkeypatch):
    import utils.email as email_mod
    monkeypatch.setattr(email_mod, "SMTP_HOST", "smtp.test.com")
    monkeypatch.setattr(email_mod, "SMTP_USER", "u@test.com")
    monkeypatch.setattr(email_mod, "SMTP_PASSWORD", "x")
    monkeypatch.setattr(email_mod, "SMTP_FROM", "u@test.com")

    import smtplib
    with patch("smtplib.SMTP", side_effect=smtplib.SMTPException("falha")):
        from utils.email import enviar_email
        with pytest.raises(smtplib.SMTPException):
            enviar_email("dest@test.com", "A", "B")
