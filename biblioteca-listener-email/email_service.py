
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from config import SmtpConfig
from mensagem import EmprestimoMensagem

log = logging.getLogger("listener.email")


class ErroEmailPermanente(Exception):
    pass


class ErroEmailTemporario(Exception):
    pass


class ErroConfiguracaoSmtp(Exception):
    pass


def _uma_linha(texto: str) -> str:
    
    return " ".join(texto.split())


def montar_email(
    msg: EmprestimoMensagem, remetente: str, nome_remetente: str
) -> EmailMessage:
    livro = _uma_linha(msg.nome_livro)
    cliente = _uma_linha(msg.nome_cliente)
    quando = f" em {msg.data_emprestimo:%d/%m/%Y}" if msg.data_emprestimo else ""

    texto = (
        f"Olá, {cliente}!\n\n"
        f"O empréstimo do livro \"{livro}\" foi registrado{quando}.\n"
        f"Número do empréstimo: #{msg.emprestimo_id}\n\n"
        f"Boa leitura!\n"
        f"{nome_remetente}\n"
    )
    html = (
        "<html><body style=\"font-family: Arial, sans-serif; color: #222;\">"
        f"<p>Olá, <strong>{escape(cliente)}</strong>!</p>"
        f"<p>O empréstimo do livro <strong>&ldquo;{escape(livro)}&rdquo;</strong> "
        f"foi registrado{escape(quando)}.</p>"
        f"<p>Número do empréstimo: <strong>#{msg.emprestimo_id}</strong></p>"
        f"<p>Boa leitura!<br>{escape(nome_remetente)}</p>"
        "</body></html>"
    )

    email = EmailMessage()
    email["Subject"] = f"Empréstimo confirmado: {livro}"
    email["From"] = formataddr((_uma_linha(nome_remetente), remetente))
    email["To"] = formataddr((cliente, msg.email_cliente))
    email.set_content(texto, cte="quoted-printable")
    email.add_alternative(html, subtype="html", cte="quoted-printable")
    return email


class EmailService:
    def __init__(self, config: SmtpConfig):
        self._cfg = config

    def enviar_confirmacao_emprestimo(self, msg: EmprestimoMensagem) -> None:
        try:
            email = montar_email(msg, self._cfg.remetente, self._cfg.nome_remetente)
        except (ValueError, TypeError) as erro:
            raise ErroEmailPermanente(f"não foi possível montar o e-mail: {erro}") from erro

        if self._cfg.dry_run:
            corpo = email.get_body(preferencelist=("plain",)).get_content()
            log.info(
                "[SIMULADO] e-mail NÃO enviado (EMAIL_DRY_RUN ligado)\n"
                "  Para: %s\n  Assunto: %s\n  ---\n%s",
                email["To"], email["Subject"], corpo,
            )
            return

        self._enviar_por_smtp(email)
        log.info("E-mail enviado para %s (empréstimo #%s)", msg.email_cliente, msg.emprestimo_id)


    def _enviar_por_smtp(self, email: EmailMessage) -> None:
        cfg = self._cfg
        try:
            with self._abrir_conexao() as smtp:
                if cfg.usuario:
                    smtp.login(cfg.usuario, cfg.senha)
                smtp.send_message(email)


        except smtplib.SMTPAuthenticationError as erro:
            raise ErroConfiguracaoSmtp(
                f"o servidor SMTP recusou o usuário/senha ({erro.smtp_code}). "
                "No Gmail é preciso usar uma 'senha de app'."
            ) from erro
        except smtplib.SMTPSenderRefused as erro:
            raise ErroConfiguracaoSmtp(
                f"o servidor SMTP recusou o remetente {cfg.remetente!r} ({erro.smtp_code})."
            ) from erro
        except smtplib.SMTPNotSupportedError as erro:
            raise ErroConfiguracaoSmtp(
                f"o servidor não suporta o que foi pedido ({erro}). "
                "Confira SMTP_SEGURANCA e SMTP_PORT."
            ) from erro


        except smtplib.SMTPRecipientsRefused as erro:
            codigos = [codigo for codigo, _ in erro.recipients.values()]
            if codigos and all(500 <= codigo < 600 for codigo in codigos):
                raise ErroEmailPermanente(f"destinatário recusado pelo servidor: {erro.recipients}") from erro
            raise ErroEmailTemporario(f"destinatário recusado temporariamente: {erro.recipients}") from erro
        except smtplib.SMTPDataError as erro:
            if 500 <= erro.smtp_code < 600:
                raise ErroEmailPermanente(f"servidor rejeitou o e-mail ({erro.smtp_code}): {erro.smtp_error!r}") from erro
            raise ErroEmailTemporario(f"servidor adiou o e-mail ({erro.smtp_code}): {erro.smtp_error!r}") from erro


        except (smtplib.SMTPException, OSError) as erro:
            raise ErroEmailTemporario(
                f"falha de comunicação com {cfg.host}:{cfg.port} ({type(erro).__name__}: {erro})"
            ) from erro

    def _abrir_conexao(self) -> smtplib.SMTP:
        cfg = self._cfg
        if cfg.seguranca == "ssl":
            return smtplib.SMTP_SSL(
                cfg.host, cfg.port, timeout=cfg.timeout, context=ssl.create_default_context()
            )
        smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        if cfg.seguranca == "starttls":
            try:
                smtp.starttls(context=ssl.create_default_context())
            except Exception:
                smtp.close()
                raise
        return smtp
