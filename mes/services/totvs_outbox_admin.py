"""Serviço administrativo da outbox TOTVS: observabilidade e reprocessamento.

Não existe UI nova nesta etapa. O acesso se dá por este serviço, consumido pelo
script ``scripts/totvs_outbox_admin.py``. Nenhum método aqui altera fato
produtivo, quantidade, estado do operador ou regra industrial.
"""

from __future__ import annotations

from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.outbound_enqueue import (
    AGGREGATE_PRODUCTION_ORDER,
    EVENT_PRODUCTION_APPOINTMENT_TERMINAL,
    EVENT_PRODUCTION_APPOINTMENT_ZERO,
    EVENT_STOP_REPORT,
    OutboundEnqueueConfig,
    load_outbound_enqueue_config,
)
from mes.integrations.totvs.outbound_mapper import (
    build_production_appointment_xml,
    build_stop_report_xml,
    map_production_appointment,
    map_stop_report,
    map_terminal_production_appointment,
)
from mes.integrations.totvs.outbox import OutboxStatus


class TotvsOutboxAdminService:
    def __init__(self, database, *, config: OutboundEnqueueConfig | None = None):
        self.database = database
        self.config = (
            config
            if config is not None
            else getattr(database, "totvs_outbox_config", None)
            or load_outbound_enqueue_config()
        )

    # ------------------------------------------------------------------
    def metrics(self) -> dict:
        return self.database.metricas_outbound_totvs()

    def list_items(self, *, status=None, production_order=None, limit: int = 50):
        return self.database.listar_itens_outbound_totvs(
            status=status, production_order=production_order, limit=limit
        )

    def attempts(self, outbox_id: int):
        return self.database.listar_tentativas_outbound_totvs(outbox_id)

    # ------------------------------------------------------------------
    def reprocess(self, outbox_id: int, *, operador: str | None = None) -> dict:
        """Devolve um item ``ERROR`` à fila preservando a identidade lógica.

        Dois caminhos, ambos sem inventar dado novo:

        * item com payload — volta a ``PENDING`` com a MESMA
          ``idempotency_key``, o MESMO XML e todo o histórico de tentativas;
        * item bloqueado, que nunca teve payload por falta de parâmetro
          homologado — o contrato é remontado a partir do MESMO fato canônico
          imutável, agora que a configuração existe. O fato não muda; o que
          mudou foi o cadastro TOTVS conhecido pelo Gestor.
        """

        item = self.database.buscar_item_outbound_totvs(int(outbox_id))
        if item is None:
            return {"ok": False, "code": "item_inexistente", "id": int(outbox_id)}
        if str(item["status"]) != OutboxStatus.ERROR.value:
            return {
                "ok": False,
                "code": "item_nao_esta_em_erro",
                "id": item["id"],
                "status": item["status"],
            }
        if item["payload_xml"]:
            atualizado = self.database.reprocessar_item_outbound_totvs(
                item["id"], operador=operador
            )
            return {
                "ok": atualizado is not None,
                "code": "reenfileirado",
                "id": item["id"],
                "idempotency_key": item["idempotency_key"],
                "item": atualizado,
            }
        return self._rebuild_blocked(item)

    def _rebuild_blocked(self, item: dict) -> dict:
        try:
            message, context = self._build_message_for(item)
        except TotvsContractError as exc:
            return {
                "ok": False,
                "code": getattr(exc, "code", "invalid_totvs_contract"),
                "id": item["id"],
                "message": str(exc),
            }
        atualizado = self.database.preencher_payload_outbound_totvs(
            item["id"],
            payload_xml=message.xml,
            idempotency_key=message.idempotency_key,
            payload_context={**dict(item.get("payload_context") or {}), **context},
        )
        return {
            "ok": atualizado is not None,
            "code": "payload_reconstruido",
            "id": item["id"],
            "idempotency_key": message.idempotency_key,
            "item": atualizado,
        }

    def _build_message_for(self, item: dict):
        if str(item["aggregate_type"]) == AGGREGATE_PRODUCTION_ORDER:
            milestone = self.database.buscar_marco_terminal_outbound_totvs(
                str(item["production_order"])
            )
            if milestone is None:
                raise TotvsContractError(
                    f"OP {item['production_order']} não possui marco terminal recebido do TOTVS."
                )
            if str(item["event_type"]) != EVENT_PRODUCTION_APPOINTMENT_TERMINAL:
                raise TotvsContractError(
                    f"Evento {item['event_type']} não é remontável a partir da OP."
                )
            contract = map_terminal_production_appointment(milestone)
            return build_production_appointment_xml(contract), {
                "reconstruido": True,
                "terminal_operation": milestone.terminal_operation,
            }

        evento_id = item.get("canonical_event_id")
        if evento_id is None:
            raise TotvsContractError(
                "Item bloqueado sem evento canônico associado; nada a remontar."
            )
        evento = self.database.buscar_evento_canonico_outbound_totvs(int(evento_id))
        if evento is None:
            raise TotvsContractError(
                f"Evento canônico {evento_id} não encontrado; nada a remontar."
            )
        if str(item["event_type"]) == EVENT_STOP_REPORT:
            code = self.config.resolve_stop_reason_code(evento)
            if not code:
                raise TotvsContractError(
                    "StopReasonCode continua sem código TOTVS configurado; "
                    "configure o cadastro SX5 grupo 44 antes de reprocessar."
                )
            contract = map_stop_report(evento, stop_reason_code=code)
            return build_stop_report_xml(contract), {
                "reconstruido": True,
                "stop_reason_code": code,
            }

        waste_code = (
            self.config.resolve_waste_code(evento) if evento.scrap_quantity else None
        )
        if evento.scrap_quantity and not waste_code:
            raise TotvsContractError(
                "WasteCode continua sem código TOTVS configurado; configure o "
                "Cadastro de Motivo Refugo antes de reprocessar."
            )
        contract = map_production_appointment(
            evento,
            waste_code=waste_code,
            allow_zero_quantity=str(item["event_type"]) == EVENT_PRODUCTION_APPOINTMENT_ZERO,
        )
        return build_production_appointment_xml(contract), {
            "reconstruido": True,
            "waste_code": waste_code,
        }


__all__ = ["TotvsOutboxAdminService"]
