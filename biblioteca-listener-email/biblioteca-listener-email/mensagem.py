"""Leitura e validação da mensagem publicada pela aplicação Spring.

Formato (classe EmprestimoMensagem.java), serializado como JSON:

    {
      "emprestimoId":   1,
      "nomeLivro":      "Dom Casmurro",
      "nomeCliente":    "Maria Silva",
      "emailCliente":   "maria@exemplo.com",
      "dataEmprestimo": "2026-10-02"
    }
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

log = logging.getLogger("listener.mensagem")

# Validação simples e suficiente para o trabalho: algo@dominio.ext, sem espaços.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MensagemInvalida(Exception):
    """A mensagem não pode ser processada (JSON quebrado, campo faltando...).

    Reenviar a mesma mensagem não resolveria, então ela não volta para a fila.
    """


@dataclass(frozen=True)
class EmprestimoMensagem:
    emprestimo_id: int
    nome_livro: str
    nome_cliente: str
    email_cliente: str
    data_emprestimo: date | None

    @classmethod
    def de_json(cls, corpo: bytes) -> "EmprestimoMensagem":
        try:
            dados = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            raise MensagemInvalida(f"o corpo não é um JSON válido ({erro})") from erro

        if not isinstance(dados, dict):
            raise MensagemInvalida("o JSON precisa ser um objeto { ... }")

        emprestimo_id = _ler_id(dados.get("emprestimoId"))
        nome_livro = _ler_texto(dados, "nomeLivro")
        nome_cliente = _ler_texto(dados, "nomeCliente")
        email = _ler_texto(dados, "emailCliente")
        if not _EMAIL.match(email):
            raise MensagemInvalida(f"emailCliente inválido: {email!r}")

        # A data só enfeita o e-mail: se faltar ou vier num formato inesperado,
        # o e-mail ainda faz sentido, então não descartamos a mensagem por isso.
        data = _ler_data(dados.get("dataEmprestimo"))
        if data is None:
            log.warning(
                "dataEmprestimo ausente ou em formato desconhecido (%r); "
                "o e-mail será enviado sem a data.",
                dados.get("dataEmprestimo"),
            )

        return cls(emprestimo_id, nome_livro, nome_cliente, email, data)


def _ler_texto(dados: dict[str, Any], campo: str) -> str:
    valor = dados.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise MensagemInvalida(f"campo obrigatório ausente ou vazio: {campo}")
    return valor.strip()


def _ler_id(valor: Any) -> int:
    if isinstance(valor, bool):
        raise MensagemInvalida(f"emprestimoId inválido: {valor!r}")
    if isinstance(valor, int):
        return valor
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    raise MensagemInvalida(f"emprestimoId ausente ou inválido: {valor!r}")


def _ler_data(valor: Any) -> date | None:
    """Aceita "2026-10-02" (padrão do Jackson 3) e também [2026, 10, 2] (Jackson antigo)."""
    try:
        if isinstance(valor, str):
            return date.fromisoformat(valor.strip()[:10])
        if (
            isinstance(valor, list)
            and len(valor) == 3
            and all(isinstance(parte, int) for parte in valor)
        ):
            return date(*valor)
    except ValueError:
        return None
    return None
