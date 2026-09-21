"""Taxonomia única de falha de transporte HTTP contra o Protheus.

Os três gateways que falam HTTP com o ERP — solicitação de OP sob demanda,
consulta de modelo do produto e envio ao WSPCP — classificam a mesma exceção
de rede com os mesmos códigos. Manter uma cópia por gateway já produziu três
definições idênticas; o código devolvido aqui vira campo persistido e texto
lido pelo operador, então precisa de uma fonte de verdade só.
"""

from __future__ import annotations

import httpx


def transport_failure_kind(exc: Exception) -> str:
    """Código estável da falha de transporte, sem expor a exceção crua."""

    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "conexao_recusada"
    if isinstance(exc, httpx.NetworkError):
        return "falha_de_rede"
    return "falha_de_transporte"


__all__ = ["transport_failure_kind"]
