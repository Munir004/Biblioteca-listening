
from __future__ import annotations

import logging
import os
import signal
import sys

from config import ConfigError, carregar_atraso_retry, carregar_rabbit, carregar_smtp
from consumer import ErroFatal, executar
from email_service import EmailService, ErroConfiguracaoSmtp

log = logging.getLogger("listener")


def _encerrar(_signum, _frame):
    raise KeyboardInterrupt  


def main() -> int:
    nivel = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


    logging.getLogger("pika").setLevel(logging.DEBUG if nivel == "DEBUG" else logging.CRITICAL)

    try:
        rabbit = carregar_rabbit()
        smtp = carregar_smtp()
        atraso_retry = carregar_atraso_retry()
    except ConfigError as erro:
        log.error("Configuração inválida: %s", erro)
        return 2

    if smtp.dry_run:
        log.warning("EMAIL_DRY_RUN ligado: os e-mails serão apenas mostrados aqui, não enviados.")
    else:
        log.info("E-mails via %s:%s (%s), remetente %s", smtp.host, smtp.port, smtp.seguranca, smtp.remetente)

    signal.signal(signal.SIGTERM, _encerrar)
    try:
        executar(rabbit, EmailService(smtp), atraso_retry=atraso_retry)
    except KeyboardInterrupt:
        log.info("Encerrado.")
        return 0
    except ErroConfiguracaoSmtp as erro:
        log.critical(
            "Listener parado: %s A mensagem em andamento continua na fila e será processada "
            "quando você corrigir o .env e iniciar de novo.", erro,
        )
        return 1
    except ErroFatal as erro:
        log.critical("Listener parado: %s", erro)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
