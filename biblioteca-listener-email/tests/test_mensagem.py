import json
from datetime import date

import pytest

from mensagem import EmprestimoMensagem, MensagemInvalida


def corpo(**mudancas):
    dados = {
        "emprestimoId": 7,
        "nomeLivro": "Dom Casmurro",
        "nomeCliente": "Maria Silva",
        "emailCliente": "maria@exemplo.com",
        "dataEmprestimo": "2026-10-02",
    }
    for chave, valor in mudancas.items():
        if valor is ...:
            dados.pop(chave)
        else:
            dados[chave] = valor
    return json.dumps(dados).encode("utf-8")


def test_mensagem_valida():
    msg = EmprestimoMensagem.de_json(corpo())
    assert msg.emprestimo_id == 7
    assert msg.nome_livro == "Dom Casmurro"
    assert msg.nome_cliente == "Maria Silva"
    assert msg.email_cliente == "maria@exemplo.com"
    assert msg.data_emprestimo == date(2026, 10, 2)


def test_data_no_formato_array_do_jackson_antigo():
    msg = EmprestimoMensagem.de_json(corpo(dataEmprestimo=[2026, 10, 2]))
    assert msg.data_emprestimo == date(2026, 10, 2)


@pytest.mark.parametrize("data", [..., None, "ontem", [2026, 13, 40], 123])
def test_data_ausente_ou_estranha_nao_invalida_a_mensagem(data):
    msg = EmprestimoMensagem.de_json(corpo(dataEmprestimo=data))
    assert msg.data_emprestimo is None


def test_campos_com_espacos_sao_aparados():
    msg = EmprestimoMensagem.de_json(corpo(nomeCliente="  Maria  "))
    assert msg.nome_cliente == "Maria"


@pytest.mark.parametrize("campo", ["emprestimoId", "nomeLivro", "nomeCliente", "emailCliente"])
def test_campo_obrigatorio_ausente(campo):
    with pytest.raises(MensagemInvalida):
        EmprestimoMensagem.de_json(corpo(**{campo: ...}))


@pytest.mark.parametrize("campo", ["nomeLivro", "nomeCliente", "emailCliente"])
@pytest.mark.parametrize("valor", ["", "   ", None, 5])
def test_texto_vazio_ou_de_tipo_errado(campo, valor):
    with pytest.raises(MensagemInvalida):
        EmprestimoMensagem.de_json(corpo(**{campo: valor}))


@pytest.mark.parametrize("email", ["maria", "maria@", "@exemplo.com", "maria@exemplo", "ma ria@exemplo.com"])
def test_email_invalido(email):
    with pytest.raises(MensagemInvalida):
        EmprestimoMensagem.de_json(corpo(emailCliente=email))


@pytest.mark.parametrize("valor", [None, True, "abc", 1.5, []])
def test_id_invalido(valor):
    with pytest.raises(MensagemInvalida):
        EmprestimoMensagem.de_json(corpo(emprestimoId=valor))


@pytest.mark.parametrize("bruto", [b"isto nao e json", b"", b"\xff\xfe", b"[1, 2]", b'"texto"', b"null"])
def test_corpo_que_nao_e_um_objeto_json(bruto):
    with pytest.raises(MensagemInvalida):
        EmprestimoMensagem.de_json(bruto)
