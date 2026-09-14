"""Porta neutra para a futura integração de planejamento corporativo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class CorporateIntegrationStatus:
    provider: str
    configured: bool
    planning_read_enabled: bool
    execution_write_enabled: bool
    reason: str


@runtime_checkable
class CorporatePlanningGateway(Protocol):
    """Contrato a ser implementado somente depois da definição da TI.

    O contrato não assume tabela, view, procedure, API, chave ou permissão de
    escrita do Protheus/TOTVS. O Gestor continua dono apenas da execução real.
    """

    def status(self) -> CorporateIntegrationStatus:
        ...

    def list_planning_changes(
        self,
        *,
        changed_after: datetime | None = None,
        cursor: str | None = None,
    ) -> Sequence[Mapping[str, Any]]:
        ...


@runtime_checkable
class CorporateMessageIngestion(Protocol):
    """Porta push para mensagens corporativas, sem forçá-la na abstração pull."""

    def status(self) -> CorporateIntegrationStatus:
        ...

    def ingest(self, payload: str | bytes) -> Any:
        ...
