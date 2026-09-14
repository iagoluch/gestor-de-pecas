"""Fronteira neutra entre a execução e o provisionamento de OP.

A Tela do Operador precisa de uma coisa só: "a OP que o operador digitou está
disponível?". Ela não pode saber de qual ERP a OP vem, por qual protocolo, nem
se houve sincronização. Essa é a mesma fronteira canônica da Etapa 3 — a camada
de execução não conhece a origem do planejamento — e é o motivo de este módulo
existir em vez de o router falar direto com a integração corporativa.

O provedor é injetado. Sem provedor, o serviço responde apenas o que já existe
localmente e informa indisponibilidade: nada é inventado para preencher a
lacuna.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


STATUS_LOCAL = "local"
STATUS_PROVISIONADA = "sincronizada"
STATUS_NAO_ENCONTRADA = "nao_encontrada"
STATUS_SEM_ROTEIRO = "sem_roteiro"
STATUS_INDISPONIVEL = "indisponivel"

DEFAULT_UNAVAILABLE_MESSAGE = "Não foi possível consultar o planejamento no momento."


@dataclass(frozen=True)
class OrderProvisioningResult:
    op: str
    status: str
    found: bool
    message: str
    requested: bool = False
    idempotent: bool = False
    elapsed_seconds: float = 0.0


class PlanningOrderProvider(Protocol):
    """Quem sabe buscar uma OP ausente. Só o adaptador conhece o ERP."""

    @property
    def available(self) -> bool:
        ...

    def lookup_local(self, op_number: str) -> dict | None:
        ...

    def sync_production_order_on_demand(self, op_number: str):
        ...


class OrderProvisioningService:
    def __init__(
        self,
        provider: PlanningOrderProvider | None = None,
        *,
        message_for=None,
        unavailable_message: str = DEFAULT_UNAVAILABLE_MESSAGE,
    ):
        self.provider = provider
        self._message_for = message_for
        self.unavailable_message = unavailable_message

    @property
    def available(self) -> bool:
        return bool(self.provider is not None and getattr(self.provider, "available", False))

    def provision(self, op_number: str) -> OrderProvisioningResult:
        code = str(op_number or "").strip().upper()
        if not self.available:
            return OrderProvisioningResult(
                op=code,
                status=STATUS_INDISPONIVEL,
                found=False,
                message=self.unavailable_message,
            )
        outcome = self.provider.sync_production_order_on_demand(op_number)
        message = (
            self._message_for(outcome.status)
            if callable(self._message_for)
            else self.unavailable_message
        )
        return OrderProvisioningResult(
            op=outcome.op,
            status=outcome.status,
            found=bool(outcome.found),
            message=message,
            requested=bool(outcome.requested),
            idempotent=bool(outcome.idempotent),
            elapsed_seconds=float(outcome.elapsed_seconds),
        )


__all__ = [
    "DEFAULT_UNAVAILABLE_MESSAGE",
    "OrderProvisioningResult",
    "OrderProvisioningService",
    "PlanningOrderProvider",
    "STATUS_INDISPONIVEL",
    "STATUS_LOCAL",
    "STATUS_NAO_ENCONTRADA",
    "STATUS_PROVISIONADA",
    "STATUS_SEM_ROTEIRO",
]
