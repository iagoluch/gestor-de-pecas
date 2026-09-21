"""Transporte da consulta de MODELO do produto ao Protheus. Só transporta.

Espelha ``on_demand_gateway.py``: este adaptador fala com o ``GPB1MODL``
(``docs/INTEGRACAO_TOTVS_MODELO_PRODUTO_SOB_DEMANDA.md``), homologado em
15/09/2026 no ambiente TOTVS TESTE. Sem endpoint configurado, ``from_env``
devolve ``None`` e quem chama trata a ausência como "modelo indisponível" —
sem inventar valor.

Contrato:

    POST <endpoint>
    Content-Type: application/json
    {"companyId": "01", "branchId": "010004", "productCode": "SSM014007071"}

    200 + JSON  → {"productCode": "...", "modelo": "..."}  (``modelo`` pode vir vazio)
    404 + JSON  → {"status": "notFound"}                   (produto inexistente no ERP)
    demais/rede → indisponibilidade transitória

Nenhuma decisão de negócio mora aqui: interpretar ausência de modelo e
decidir o texto exibido ao usuário é de quem chama.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

import httpx

from mes.integrations.totvs.transport import transport_failure_kind


DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ProductModelRequestResult:
    accepted: bool = False
    modelo: str | None = None
    not_found: bool = False
    unavailable_reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class ProductModelGatewayConfig:
    endpoint: str
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    username: str | None = None
    password: str | None = None
    verify_tls: bool = True


class ProtheusProductModelGateway:
    def __init__(self, config: ProductModelGatewayConfig, *, transport=None):
        self.config = config
        self._transport = transport

    def request_product_model(
        self, *, company_id: str | None, branch_id: str | None, product_code: str
    ) -> ProductModelRequestResult:
        payload = {
            "companyId": str(company_id or "").strip(),
            "branchId": str(branch_id or "").strip(),
            "productCode": str(product_code or "").strip(),
        }
        auth = None
        if self.config.username:
            auth = (self.config.username, self.config.password or "")
        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_tls,
                transport=self._transport,
            ) as client:
                response = client.post(
                    self.config.endpoint,
                    json=payload,
                    headers={"Accept": "application/json"},
                    auth=auth,
                )
        except httpx.HTTPError as exc:
            kind = transport_failure_kind(exc)
            return ProductModelRequestResult(unavailable_reason=kind, detail=str(exc)[:300])

        if response.status_code == 404:
            return ProductModelRequestResult(not_found=True, detail=self._reason(response))
        if response.status_code >= 400:
            return ProductModelRequestResult(
                unavailable_reason=f"http_{response.status_code}",
                detail=self._reason(response),
            )

        data = self._json(response)
        if data is None:
            return ProductModelRequestResult(
                unavailable_reason="resposta_sem_json", detail=self._reason(response)
            )
        # productCode ausente na resposta e um contrato quebrado, nao "sem modelo".
        if "productCode" not in data:
            return ProductModelRequestResult(
                unavailable_reason="resposta_fora_do_contrato", detail=self._reason(response)
            )
        modelo = data.get("modelo")
        return ProductModelRequestResult(accepted=True, modelo=str(modelo) if modelo else "")

    @staticmethod
    def _json(response: httpx.Response) -> dict | None:
        try:
            data = response.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _reason(response: httpx.Response) -> str:
        return (response.text or "")[:300]

    @classmethod
    def from_env(cls, env=None, *, transport=None) -> "ProtheusProductModelGateway | None":
        """Sem endpoint configurado não há gateway — e não há improviso."""

        environ = env if env is not None else os.environ
        endpoint = str(environ.get("GESTOR_TOTVS_MODEL_PULL_ENDPOINT") or "").strip()
        if not endpoint:
            return None
        raw_timeout = str(
            environ.get("GESTOR_TOTVS_MODEL_PULL_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS
        ).strip()
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = DEFAULT_TIMEOUT_SECONDS
        if timeout <= 0:
            timeout = DEFAULT_TIMEOUT_SECONDS
        verify_raw = str(environ.get("GESTOR_TOTVS_MODEL_PULL_VERIFY_TLS") or "1").strip()
        # Mesma credencial REST das demais publicações GESTORPECAS*, salvo
        # override explícito para este endpoint.
        username = (
            str(environ.get("GESTOR_TOTVS_MODEL_PULL_USERNAME") or "").strip()
            or str(environ.get("GESTOR_TOTVS_OP_PULL_USERNAME") or "").strip()
            or None
        )
        password = (
            environ.get("GESTOR_TOTVS_MODEL_PULL_PASSWORD")
            or environ.get("GESTOR_TOTVS_OP_PULL_PASSWORD")
            or None
        )
        return cls(
            ProductModelGatewayConfig(
                endpoint=endpoint,
                timeout_seconds=timeout,
                username=username,
                password=password,
                verify_tls=verify_raw not in {"0", "false", "False", "no"},
            ),
            transport=transport,
        )


__all__ = [
    "ProductModelGatewayConfig",
    "ProductModelRequestResult",
    "ProtheusProductModelGateway",
]
