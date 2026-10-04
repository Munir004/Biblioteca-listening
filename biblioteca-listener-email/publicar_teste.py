
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import pika
from pika.exceptions import AMQPConnectionError, ChannelClosedByBroker, NackError, UnroutableError

from config import EXCHANGE_NAME, ROUTING_KEY, carregar_rabbit


def montar_corpo(args: argparse.Namespace, numero: int) -> bytes:
    if args.invalida:
        return "isto não é um JSON".encode("utf-8")
    hoje = date.today()
    mensagem = {
        "emprestimoId": args.emprestimo_id + numero,
        "nomeLivro": args.livro,
        "nomeCliente": args.cliente,
        "emailCliente": args.email,
        "dataEmprestimo": [hoje.year, hoje.month, hoje.day] if args.data_como_array else hoje.isoformat(),
    }
    return json.dumps(mensagem, ensure_ascii=False).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Publica mensagens de teste de empréstimo.")
    ap.add_argument("--email", default=os.getenv("EMAIL_TESTE", "cliente@exemplo.com"))
    ap.add_argument("--cliente", default="Maria Silva")
    ap.add_argument("--livro", default="Dom Casmurro")
    ap.add_argument("--id", dest="emprestimo_id", type=int, default=1, help="id do primeiro empréstimo")
    ap.add_argument("--quantidade", type=int, default=1)
    ap.add_argument("--data-como-array", action="store_true")
    ap.add_argument("--invalida", action="store_true")
    args = ap.parse_args()

    cfg = carregar_rabbit()

    propriedades = pika.BasicProperties(
        content_type="application/json",
        content_encoding="UTF-8",
        delivery_mode=2,  
        headers={"__TypeId__": "school.sptech.biblioteca.dto.EmprestimoMensagem"},
    )

    try:
        conexao = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=cfg.host, port=cfg.port, virtual_host=cfg.vhost,
                credentials=pika.PlainCredentials(cfg.usuario, cfg.senha),
            )
        )
    except AMQPConnectionError as erro:
        print(f"Não consegui conectar ao RabbitMQ em {cfg.host}:{cfg.port}: {erro or type(erro).__name__}")
        return 1

    try:
        canal = conexao.channel()
        canal.confirm_delivery()  
        for numero in range(args.quantidade):
            canal.basic_publish(
                exchange=EXCHANGE_NAME,
                routing_key=ROUTING_KEY,
                body=montar_corpo(args, numero),
                properties=propriedades,
                mandatory=True,
            )
            print(f"mensagem {numero + 1}/{args.quantidade} publicada em {EXCHANGE_NAME!r} (chave {ROUTING_KEY!r})")
    except UnroutableError:
        print("A exchange existe, mas NENHUMA fila está ligada a ela: a mensagem foi perdida.\n"
              "Suba o listener (python main.py) — ele cria a fila — e tente de novo.")
        return 1
    except ChannelClosedByBroker as erro:
        if erro.reply_code == 404:
            print(f"A exchange {EXCHANGE_NAME!r} ainda não existe. Suba o listener (ele cria exchange e fila) "
                  "ou a aplicação Spring e tente de novo.")
        else:
            print(f"O RabbitMQ fechou o canal: {erro}")
        return 1
    except NackError:
        print("O RabbitMQ não aceitou a mensagem (nack).")
        return 1
    finally:
        if conexao.is_open:
            conexao.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
