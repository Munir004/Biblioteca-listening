import json

import pytest

from consumer import processar_mensagem
from email_service import ErroConfiguracaoSmtp, ErroEmailPermanente, ErroEmailTemporario

VALIDA = json.dumps(
    {
        "emprestimoId": 1,
        "nomeLivro": "Dom Casmurro",
        "nomeCliente": "Maria",
        "emailCliente": "maria@exemplo.com",
        "dataEmprestimo": "2026-10-02",
    }
).encode()


class CanalFalso:
    def __init__(self):
        self.chamadas = []

    def basic_ack(self, delivery_tag):
        self.chamadas.append(("ack", delivery_tag))

    def basic_nack(self, delivery_tag, requeue):
        self.chamadas.append(("nack", delivery_tag, requeue))

    def basic_reject(self, delivery_tag, requeue):
        self.chamadas.append(("reject", delivery_tag, requeue))


class EmailFalso:
    def __init__(self, erro=None):
        self.erro = erro
        self.enviados = []

    def enviar_confirmacao_emprestimo(self, msg):
        if self.erro:
            raise self.erro
        self.enviados.append(msg)


def rodar(corpo, email):
    canal, esperas = CanalFalso(), []
    processar_mensagem(canal, 42, corpo, email, atraso_retry=3, dormir=esperas.append)
    return canal, esperas


def test_sucesso_envia_email_e_da_ack():
    email = EmailFalso()
    canal, esperas = rodar(VALIDA, email)
    assert canal.chamadas == [("ack", 42)]
    assert len(email.enviados) == 1 and email.enviados[0].email_cliente == "maria@exemplo.com"
    assert esperas == []


def test_mensagem_invalida_e_descartada_sem_tentar_enviar():
    email = EmailFalso()
    canal, _ = rodar(b"isto nao e json", email)
    assert canal.chamadas == [("reject", 42, False)]
    assert email.enviados == []


def test_email_impossivel_de_entregar_e_descartado():
    canal, _ = rodar(VALIDA, EmailFalso(ErroEmailPermanente("destinatário não existe")))
    assert canal.chamadas == [("reject", 42, False)]


def test_smtp_fora_do_ar_devolve_para_a_fila_e_espera():
    canal, esperas = rodar(VALIDA, EmailFalso(ErroEmailTemporario("timeout")))
    assert canal.chamadas == [("nack", 42, True)]
    assert esperas == [3]


def test_smtp_mal_configurado_nao_confirma_nem_descarta():
    canal = CanalFalso()
    with pytest.raises(ErroConfiguracaoSmtp):
        processar_mensagem(canal, 42, VALIDA, EmailFalso(ErroConfiguracaoSmtp("senha")), 3, lambda s: None)
    assert canal.chamadas == []
