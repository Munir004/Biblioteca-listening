from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

EXCHANGE_NAME = "exchange_biblioteca"
QUEUE_NAME = "queue_emprestimos"
ROUTING_KEY = "key_emprestimo"

SEGURANCAS_VALIDAS = ("starttls", "ssl", "nenhuma")
PORTA_PADRAO_SMTP = {"starttls": 587, "ssl": 465, "nenhuma": 25}


class ConfigError(Exception):
    """Variável de ambiente ausente ou com valor inválido."""


@dataclass(frozen=True)
class RabbitConfig:
    host: str
    port: int
    usuario: str
    senha: str
    vhost: str


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    seguranca: str
    usuario: str | None
    senha: str | None
    remetente: str
    nome_remetente: str
    timeout: int
    dry_run: bool


def _texto(nome: str, padrao: str = "") -> str:
    return os.getenv(nome, padrao).strip()


def _inteiro(nome: str, padrao: int) -> int:
    bruto = _texto(nome)
    if not bruto:
        return padrao
    try:
        return int(bruto)
    except ValueError:
        raise ConfigError(f"{nome} precisa ser um número inteiro (valor atual: {bruto!r})")


def _booleano(nome: str) -> bool:
    return _texto(nome).lower() in {"1", "true", "t", "yes", "y", "sim", "s", "on"}


def carregar_rabbit() -> RabbitConfig:
    return RabbitConfig(
        host=_texto("RABBITMQ_HOST", "localhost"),
        port=_inteiro("RABBITMQ_PORT", 5672),
        usuario=_texto("RABBITMQ_USER", "admin"),
        senha=os.getenv("RABBITMQ_PASSWORD", "admin"),
        vhost=_texto("RABBITMQ_VHOST", "/"),
    )


def carregar_smtp() -> SmtpConfig:
    dry_run = _booleano("EMAIL_DRY_RUN")
    host = _texto("SMTP_HOST")
    seguranca = _texto("SMTP_SEGURANCA", "starttls").lower()
    usuario = _texto("SMTP_USER") or None
    senha = os.getenv("SMTP_PASSWORD") or None

    if seguranca not in SEGURANCAS_VALIDAS:
        raise ConfigError(
            f"SMTP_SEGURANCA deve ser uma destas: {', '.join(SEGURANCAS_VALIDAS)} "
            f"(valor atual: {seguranca!r})"
        )
    if not dry_run:
        if not host:
            raise ConfigError(
                "SMTP_HOST não definido. Preencha o .env (veja .env.example) "
                "ou use EMAIL_DRY_RUN=true para só simular o envio."
            )
        if usuario and not senha:
            raise ConfigError("SMTP_USER foi definido, mas falta SMTP_PASSWORD.")

    remetente = _texto("EMAIL_REMETENTE") or usuario or "biblioteca@localhost"
    return SmtpConfig(
        host=host,
        port=_inteiro("SMTP_PORT", PORTA_PADRAO_SMTP[seguranca]),
        seguranca=seguranca,
        usuario=usuario,
        senha=senha,
        remetente=remetente,
        nome_remetente=_texto("EMAIL_NOME_REMETENTE", "Biblioteca"),
        timeout=_inteiro("SMTP_TIMEOUT_SEGUNDOS", 20),
        dry_run=dry_run,
    )


def carregar_atraso_retry() -> int:
    return _inteiro("RETRY_DELAY_SEGUNDOS", 10)
