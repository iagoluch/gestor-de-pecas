"""Estado seguro enquanto o mecanismo corporativo ainda não foi definido."""

from mes.contracts.corporate import CorporateIntegrationStatus


class PendingCorporateIntegration:
    """Adaptador nulo: não abre conexão externa e não inventa planejamento."""

    def status(self) -> CorporateIntegrationStatus:
        return CorporateIntegrationStatus(
            provider="pending_totvs_definition",
            configured=False,
            planning_read_enabled=False,
            execution_write_enabled=False,
            reason="Mecanismo de integração Protheus/TOTVS pendente de definição pela TI.",
        )

    def list_planning_changes(self, *, changed_after=None, cursor=None):
        raise RuntimeError(
            "Integração Protheus/TOTVS ainda não configurada; nenhum dado externo foi consultado."
        )


def totvs_production_order_status(settings) -> CorporateIntegrationStatus:
    """Expõe capacidade efetiva sem abrir conexão nem chamar o TOTVS."""

    enabled = bool(getattr(settings, "totvs_enabled", False))
    soap_enabled = bool(getattr(settings, "totvs_soap_enabled", False))
    if not enabled:
        reason = "Integração TOTVS ProductionOrder V1 desabilitada por configuração."
    elif soap_enabled:
        reason = "Recepção SOAP ProductionOrder V1 habilitada e configurada."
    else:
        reason = (
            "Ingestão ProductionOrder V1 habilitada para importação controlada; "
            "receptor SOAP desabilitado."
        )
    return CorporateIntegrationStatus(
        provider="totvs_production_order_push_v1",
        configured=enabled,
        planning_read_enabled=enabled,
        execution_write_enabled=False,
        reason=reason,
    )
