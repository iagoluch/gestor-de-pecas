"""Transporte da solicitação de OP ao Protheus. Só transporta e reporta.

Este adaptador implementa ``ProductionOrderRequestGateway`` para a rotina de
solicitação de OP publicada no Protheus. **Ela não existe hoje** no ambiente
TESTE: a descoberta da Etapa 6.1 provou que nenhum mecanismo suportado do
Protheus devolve/envia um ``ProductionOrder`` sob demanda (ver
``docs/INTEGRACAO_TOTVS_OP_SOB_DEMANDA_ETAPA61.md``). Enquanto a rotina não for
publicada pela TI/TOTVS, ``from_env`` devolve ``None`` e o Gestor apenas informa
indisponibilidade ao operador — sem inventar OP e sem caminho alternativo.

O contrato abaixo é exatamente o especificado para a TI:

    POST <endpoint>
    Content-Type: application/json
    {"companyId": "01", "branchId": "010004", "number": "A9716901001"}

    200 + text/xml   → TOTVSMessage/ProductionOrder (modo ``inline``)
    200 + JSON       → {"status": "accepted"}       (modo ``push``)
    404 + JSON       → {"status": "notFound"}       (OP inexistente no ERP)
    demais/rede      → indisponibilidade transitória

Nenhuma decisão de negócio mora aqui: classificar, esperar e persistir é do
caso de uso; interpretar o ``ProductionOrder`` é do pipeline canônico.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time

import httpx

from mes.integrations.totvs.errors import TotvsIntegrationError
from mes.integrations.totvs.on_demand import (
    DELIVERY_INLINE,
    DELIVERY_PUSH,
    STATUS_INDISPONIVEL,
    ProductionOrderOnDemandSyncService,
    ProductionOrderRequestResult,
    operator_message,
)
from mes.integrations.totvs.service import build_totvs_ingestion_service
from mes.services.order_provisioning import OrderProvisioningService


DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class OnDemandGatewayConfig:
    endpoint: str
    delivery: str = DELIVERY_PUSH
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True


def _transport_failure_kind(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "conexao_recusada"
    if isinstance(exc, httpx.NetworkError):
        return "falha_de_rede"
    return "falha_de_transporte"


class ProtheusOnDemandRequestGateway:
    def __init__(self, config: OnDemandGatewayConfig, *, transport=None):
        self.config = config
        self._transport = transport

    def request_production_order(
        self, *, company_id: str | None, branch_id: str | None, number: str
    ) -> ProductionOrderRequestResult:
        payload = {
            "companyId": str(company_id or "").strip(),
            "branchId": str(branch_id or "").strip(),
            # A OP pode ser alfanumérica e nunca é convertida para número.
            "number": str(number or "").strip(),
        }
        auth = None
        if self.config.username:
            auth = (self.config.username, self.config.password or "")
        # O operador aguarda esta chamada na tela: uma única tentativa a mais,
        # sem o backoff longo da outbox, absorve uma queda breve de rede sem
        # travar o posto por minutos.
        attempts = 2
        last_exc: httpx.HTTPError | None = None
        for attempt in range(attempts):
            try:
                with httpx.Client(
                    timeout=self.config.timeout_seconds,
                    verify=self.config.verify_tls,
                    transport=self._transport,
                ) as client:
                    response = client.post(
                        self.config.endpoint,
                        json=payload,
                        headers={"Accept": "application/xml, application/json"},
                        auth=auth,
                    )
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    time.sleep(0.5)
        else:
            kind = _transport_failure_kind(last_exc)
            return ProductionOrderRequestResult(
                unavailable_reason=kind, detail=str(last_exc)[:300]
            )

        if response.status_code == 404:
            return ProductionOrderRequestResult(not_found=True, detail=self._reason(response))
        if response.status_code >= 400:
            return ProductionOrderRequestResult(
                unavailable_reason=f"http_{response.status_code}",
                detail=self._reason(response),
            )

        body = response.text or ""
        content_type = str(response.headers.get("content-type") or "").casefold()
        looks_like_message = "xml" in content_type or body.lstrip().startswith(
            ("<?xml", "<TOTVSMessage")
        )
        if looks_like_message:
            return ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=body
            )
        # Uma resposta JSON pode ainda ser uma negativa funcional com HTTP 200.
        if self._json_status(response) in {"notfound", "not_found"}:
            return ProductionOrderRequestResult(not_found=True, detail=self._reason(response))
        if self.config.delivery == DELIVERY_INLINE:
            return ProductionOrderRequestResult(
                unavailable_reason="resposta_sem_production_order",
                detail=self._reason(response),
            )
        return ProductionOrderRequestResult(accepted=True, delivery=DELIVERY_PUSH)

    @staticmethod
    def _json_status(response: httpx.Response) -> str:
        try:
            data = response.json()
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("status") or "").strip().casefold().replace("-", "_")

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        return (response.text or "")[:300]

    @classmethod
    def from_env(cls, env=None, *, transport=None) -> "ProtheusOnDemandRequestGateway | None":
        """Sem endpoint configurado não há gateway — e não há improviso."""

        environ = env if env is not None else os.environ
        endpoint = str(environ.get("GESTOR_TOTVS_OP_PULL_ENDPOINT") or "").strip()
        if not endpoint:
            return None
        delivery = (
            str(environ.get("GESTOR_TOTVS_OP_PULL_MODE") or DELIVERY_PUSH).strip().casefold()
        )
        if delivery not in {DELIVERY_INLINE, DELIVERY_PUSH}:
            raise TotvsIntegrationError(
                "GESTOR_TOTVS_OP_PULL_MODE deve ser 'inline' ou 'push'.",
                code="totvs_pull_config_invalida",
            )
        raw_timeout = str(
            environ.get("GESTOR_TOTVS_OP_PULL_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS
        ).strip()
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise TotvsIntegrationError(
                "GESTOR_TOTVS_OP_PULL_TIMEOUT_SECONDS deve ser numérico.",
                code="totvs_pull_config_invalida",
            ) from exc
        if timeout <= 0:
            raise TotvsIntegrationError(
                "GESTOR_TOTVS_OP_PULL_TIMEOUT_SECONDS deve ser maior que zero.",
                code="totvs_pull_config_invalida",
            )
        verify_raw = str(environ.get("GESTOR_TOTVS_OP_PULL_VERIFY_TLS") or "1").strip()
        return cls(
            OnDemandGatewayConfig(
                endpoint=endpoint,
                delivery=delivery,
                timeout_seconds=timeout,
                username=str(environ.get("GESTOR_TOTVS_OP_PULL_USERNAME") or "").strip() or None,
                password=environ.get("GESTOR_TOTVS_OP_PULL_PASSWORD") or None,
                verify_tls=verify_raw not in {"0", "false", "False", "no"},
            ),
            transport=transport,
        )


def build_on_demand_sync_service(
    repository,
    settings,
    *,
    ingestion_service=None,
    gateway=None,
    env=None,
    now_func=None,
    sleep_func=None,
) -> ProductionOrderOnDemandSyncService:
    """Monta o caso de uso com o pipeline canônico e a porta de solicitação.

    O mesmo código serve TESTE e um piloto REAL: o que muda é o ``.env``. Sem
    ``GESTOR_TOTVS_OP_PULL_ENDPOINT`` o gateway é ``None`` e o serviço responde
    apenas o lookup local — nada é inventado para preencher a lacuna.
    """

    if gateway is None:
        gateway = ProtheusOnDemandRequestGateway.from_env(env)
    # Sem gateway não existe busca remota, e montar o pipeline de ingestão só
    # para descartá-lo custaria uma consulta de catálogo por requisição.
    if ingestion_service is None and gateway is not None:
        ingestion_service = build_totvs_ingestion_service(repository, settings)
    return ProductionOrderOnDemandSyncService(
        repository,
        ingestion_service=ingestion_service,
        gateway=gateway,
        company_id=getattr(settings, "totvs_op_pull_company_id", "") or None,
        branch_id=getattr(settings, "totvs_op_pull_branch_id", "") or None,
        timeout_seconds=float(getattr(settings, "totvs_op_pull_timeout_seconds", 25)),
        poll_interval_seconds=(
            float(getattr(settings, "totvs_op_pull_poll_interval_ms", 500)) / 1000.0
        ),
        negative_ttl_seconds=int(
            getattr(settings, "totvs_op_pull_negative_ttl_seconds", 60)
        ),
        now_func=now_func,
        sleep_func=sleep_func,
    )


def build_order_provisioning_service(
    repository,
    settings,
    **kwargs,
) -> OrderProvisioningService:
    """Entrega à execução uma fronteira neutra, sem nome de ERP no caminho."""

    return OrderProvisioningService(
        build_on_demand_sync_service(repository, settings, **kwargs),
        message_for=operator_message,
        unavailable_message=operator_message(STATUS_INDISPONIVEL),
    )


__all__ = [
    "OnDemandGatewayConfig",
    "ProtheusOnDemandRequestGateway",
    "build_on_demand_sync_service",
    "build_order_provisioning_service",
]
