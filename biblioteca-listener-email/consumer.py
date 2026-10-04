
from __future__ import annotations

import logging
import time
from typing import Callable

import pika
from pika.exceptions import (
    AMQPConnectionError,
    ChannelClosedByBroker,
    ProbableAccessDeniedError,
    ProbableAuthenticationError,
)

from config import EXCHANGE_NAME, QUEUE_NAME, ROUTING_KEY, RabbitConfig
from email_service import (
    EmailService,
    ErroConfiguracaoSmtp,
    ErroEmailPermanente,
    ErroEmailTemporario,
)
from mensagem import EmprestimoMensagem, MensagemInvalida

log = logging.getLogger("listener.consumer")


class ErroFatal(Exception):
    pass





def processar_mensagem(
    canal,
    delivery_tag: int,
    corpo: bytes,
    email_service: EmailService,
    atraso_retry: float,
    dormir: Callable[[float], None],
) -> None:
    
    log.debug("Corpo bruto da mensagem #%s: %r", delivery_tag, corpo)
    try:
        msg = EmprestimoMensagem.de_json(corpo)
    except MensagemInvalida as erro:
        log.error("Mensagem #%s descartada (inválida): %s | corpo=%r", delivery_tag, erro, corpo[:500])
        canal.basic_reject(delivery_tag=delivery_tag, requeue=False)
        return

    log.info(
        "Empréstimo #%s recebido: livro=%r cliente=%r email=%s",
        msg.emprestimo_id, msg.nome_livro, msg.nome_cliente, msg.email_cliente,
    )

    try:
        email_service.enviar_confirmacao_emprestimo(msg)
    except ErroEmailPermanente as erro:
        log.error("Empréstimo #%s descartado: %s", msg.emprestimo_id, erro)
        canal.basic_reject(delivery_tag=delivery_tag, requeue=False)
    except ErroEmailTemporario as erro:
        log.warning(
            "Empréstimo #%s: %s. Volta para a fila; nova tentativa em %ss.",
            msg.emprestimo_id, erro, atraso_retry,
        )
        canal.basic_nack(delivery_tag=delivery_tag, requeue=True)
        dormir(atraso_retry)
    except ErroConfiguracaoSmtp:

        raise
    else:
        canal.basic_ack(delivery_tag=delivery_tag)





def declarar_topologia(canal) -> None:
    
    canal.exchange_declare(exchange=EXCHANGE_NAME, exchange_type="direct", durable=True)
    canal.queue_declare(queue=QUEUE_NAME, durable=True)
    canal.queue_bind(queue=QUEUE_NAME, exchange=EXCHANGE_NAME, routing_key=ROUTING_KEY)


def _sessao(cfg: RabbitConfig, email_service: EmailService, atraso_retry: float) -> None:
    parametros = pika.ConnectionParameters(
        host=cfg.host,
        port=cfg.port,
        virtual_host=cfg.vhost,
        credentials=pika.PlainCredentials(cfg.usuario, cfg.senha),
        heartbeat=60,
        blocked_connection_timeout=300,
    )
    log.info("Conectando ao RabbitMQ em %s:%s ...", cfg.host, cfg.port)
    conexao = pika.BlockingConnection(parametros)
    try:
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.basic_qos(prefetch_count=1)  

        def ao_receber(ch, metodo, _propriedades, corpo):
            processar_mensagem(ch, metodo.delivery_tag, corpo, email_service, atraso_retry, conexao.sleep)

        canal.basic_consume(queue=QUEUE_NAME, on_message_callback=ao_receber, auto_ack=False)
        log.info("Conectado. Aguardando mensagens na fila %r (Ctrl+C para sair).", QUEUE_NAME)
        canal.start_consuming()
    finally:
        if conexao.is_open:
            try:
                conexao.close()
            except Exception:  
                pass


def executar(
    cfg: RabbitConfig,
    email_service: EmailService,
    atraso_retry: float = 10,
    espera_reconexao: float = 5,
) -> None:
    
    while True:
        try:
            _sessao(cfg, email_service, atraso_retry)
            return
        except (ProbableAuthenticationError, ProbableAccessDeniedError) as erro:
            raise ErroFatal(
                f"o RabbitMQ recusou o usuário/senha {cfg.usuario!r} ou o acesso ao vhost "
                f"{cfg.vhost!r} ({erro}). Confira RABBITMQ_USER / RABBITMQ_PASSWORD."
            ) from erro
        except ChannelClosedByBroker as erro:
            if erro.reply_code == 406:
                raise ErroFatal(
                    f"a exchange/fila já existe no RabbitMQ com parâmetros diferentes dos esperados "
                    f"({erro.reply_text}). Apague {QUEUE_NAME!r} / {EXCHANGE_NAME!r} no painel "
                    "(http://localhost:15672) ou recrie o broker com 'docker compose down -v'."
                ) from erro
            log.warning("Canal fechado pelo RabbitMQ: %s. Reconectando em %ss.", erro, espera_reconexao)
            time.sleep(espera_reconexao)
        except AMQPConnectionError as erro:
            detalhe = " ".join(str(parte) for parte in erro.args if parte) or type(erro).__name__
            log.warning(
                "Sem conexão com o RabbitMQ em %s:%s (%s). Nova tentativa em %ss.",
                cfg.host, cfg.port, detalhe, espera_reconexao,
            )
            time.sleep(espera_reconexao)
