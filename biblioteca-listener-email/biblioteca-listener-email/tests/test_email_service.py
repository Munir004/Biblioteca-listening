import smtplib
from datetime import date

import pytest

import email_service
from config import SmtpConfig
from email_service import (
    EmailService,
    ErroConfiguracaoSmtp,
    ErroEmailPermanente,
    ErroEmailTemporario,
    montar_email,
)
from mensagem import EmprestimoMensagem


def mensagem(**mudancas):
    base = dict(
        emprestimo_id=7,
        nome_livro="Dom Casmurro",
        nome_cliente="Maria Silva",
        email_cliente="maria@exemplo.com",
        data_emprestimo=date(2026, 10, 2),
    )
    base.update(mudancas)
    return EmprestimoMensagem(**base)


def config(**mudancas):
    base = dict(
        host="smtp.teste", port=587, seguranca="starttls", usuario="bib@teste.com",
        senha="segredo", remetente="bib@teste.com", nome_remetente="Biblioteca",
        timeout=5, dry_run=False,
    )
    base.update(mudancas)
    return SmtpConfig(**base)


class FakeSMTP:
    """Substitui smtplib.SMTP / SMTP_SSL: guarda o que aconteceu e pode falhar sob demanda."""

    instancias: list = []
    erro_conexao = None
    erro_login = None
    erro_envio = None

    def __init__(self, host, port, timeout=None, context=None):
        if FakeSMTP.erro_conexao:
            raise FakeSMTP.erro_conexao
        self.host, self.port, self.context = host, port, context
        self.tls = False
        self.login_feito = None
        self.enviadas = []
        FakeSMTP.instancias.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, usuario, senha):
        if FakeSMTP.erro_login:
            raise FakeSMTP.erro_login
        self.login_feito = (usuario, senha)

    def send_message(self, msg):
        if FakeSMTP.erro_envio:
            raise FakeSMTP.erro_envio
        self.enviadas.append(msg)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture(autouse=True)
def smtp_falso(monkeypatch):
    FakeSMTP.instancias = []
    FakeSMTP.erro_conexao = FakeSMTP.erro_login = FakeSMTP.erro_envio = None
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTP)


# ------------------------------ conteúdo do e-mail ------------------------------
def test_montar_email_tem_destinatario_assunto_e_dados():
    email = montar_email(mensagem(), "bib@teste.com", "Biblioteca")
    assert "maria@exemplo.com" in email["To"]
    assert email["Subject"] == "Empréstimo confirmado: Dom Casmurro"
    assert "bib@teste.com" in email["From"]
    texto = email.get_body(preferencelist=("plain",)).get_content()
    assert "Dom Casmurro" in texto and "02/10/2026" in texto and "#7" in texto
    assert email.get_body(preferencelist=("html",)) is not None


def test_montar_email_sem_data():
    email = montar_email(mensagem(data_emprestimo=None), "bib@teste.com", "Biblioteca")
    texto = email.get_body(preferencelist=("plain",)).get_content()
    assert "foi registrado." in texto


def test_html_escapa_conteudo_do_usuario():
    email = montar_email(mensagem(nome_cliente="<script>x</script>"), "bib@teste.com", "Biblioteca")
    html = email.get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_quebra_de_linha_nao_vira_cabecalho_injetado():
    email = montar_email(mensagem(nome_livro="Livro\r\nBcc: alguem@x.com"), "bib@teste.com", "Biblioteca")
    assert email["Bcc"] is None
    assert "\n" not in email["Subject"]


def test_acentos_no_nome_do_cliente():
    email = montar_email(mensagem(nome_cliente="João Conceição"), "bib@teste.com", "Biblioteca")
    assert "João Conceição" in email.get_body(preferencelist=("plain",)).get_content()


# ------------------------------ envio ------------------------------
def test_envio_com_starttls_e_login():
    EmailService(config()).enviar_confirmacao_emprestimo(mensagem())
    (smtp,) = FakeSMTP.instancias
    assert smtp.tls is True
    assert smtp.login_feito == ("bib@teste.com", "segredo")
    assert len(smtp.enviadas) == 1


def test_envio_sem_usuario_nao_faz_login():
    EmailService(config(usuario=None, senha=None, seguranca="nenhuma")).enviar_confirmacao_emprestimo(mensagem())
    (smtp,) = FakeSMTP.instancias
    assert smtp.tls is False and smtp.login_feito is None and len(smtp.enviadas) == 1


def test_dry_run_nao_abre_conexao():
    FakeSMTP.erro_conexao = AssertionError("não deveria conectar")
    EmailService(config(dry_run=True)).enviar_confirmacao_emprestimo(mensagem())
    assert FakeSMTP.instancias == []


# ------------------------------ classificação dos erros ------------------------------
@pytest.mark.parametrize(
    "onde, erro, esperado",
    [
        ("erro_login", smtplib.SMTPAuthenticationError(535, b"senha errada"), ErroConfiguracaoSmtp),
        ("erro_envio", smtplib.SMTPSenderRefused(553, b"remetente", "bib@teste.com"), ErroConfiguracaoSmtp),
        ("erro_envio", smtplib.SMTPNotSupportedError("sem STARTTLS"), ErroConfiguracaoSmtp),
        ("erro_envio", smtplib.SMTPRecipientsRefused({"maria@exemplo.com": (550, b"nao existe")}), ErroEmailPermanente),
        ("erro_envio", smtplib.SMTPRecipientsRefused({"maria@exemplo.com": (450, b"caixa cheia")}), ErroEmailTemporario),
        ("erro_envio", smtplib.SMTPDataError(554, b"rejeitado"), ErroEmailPermanente),
        ("erro_envio", smtplib.SMTPDataError(451, b"tente depois"), ErroEmailTemporario),
        ("erro_envio", smtplib.SMTPServerDisconnected("caiu"), ErroEmailTemporario),
        ("erro_conexao", ConnectionRefusedError("recusada"), ErroEmailTemporario),
        ("erro_conexao", TimeoutError("demorou"), ErroEmailTemporario),
    ],
)
def test_classificacao_dos_erros_de_smtp(onde, erro, esperado):
    setattr(FakeSMTP, onde, erro)
    with pytest.raises(esperado):
        EmailService(config()).enviar_confirmacao_emprestimo(mensagem())
