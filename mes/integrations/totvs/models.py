"""DTOs neutros do contrato TOTVSMessage/ProductionOrder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class TotvsMessageMetadata:
    uuid: str | None
    message_type: str | None
    transaction: str
    standard_version: str | None
    source_application: str | None
    company_id: str | None
    branch_id: str | None
    user_id: str | None
    generated_on: datetime | None
    context_name: str | None
    delivery_type: str | None
    message_version: str | None = None
    schema_location: str | None = None
    product_name: str | None = None
    product_version: str | None = None


@dataclass(frozen=True)
class TotvsBusinessEvent:
    entity: str
    event: str
    internal_id: str | None


@dataclass(frozen=True)
class TotvsActivityOrder:
    production_order_number: str | None
    activity_id: str | None
    activity_code: str | None
    activity_description: str | None
    split: str | None
    item_code: str | None
    item_description: str | None
    activity_type: str | None
    work_center_code: str | None
    work_center_description: str | None
    unit_time_type: str | None
    time_resource: Decimal | None
    time_machine: Decimal | None
    time_setup: Decimal | None
    script_code: str | None
    resource_quantity: Decimal | None
    production_quantity: Decimal | None
    activity_quantity: Decimal | None
    unit_activity_code: str | None
    machine_code: str | None
    start_plan_date_time: datetime | None
    end_plan_date_time: datetime | None
    is_activity_start: bool | None
    is_activity_end: bool | None
    time_mod: Decimal | None
    time_ind_mes: Decimal | None


@dataclass(frozen=True)
class TotvsMaterialOrder:
    material_id: str | None
    material_code: str | None
    material_description: str | None
    activity_code: str | None
    warehouse_code: str | None
    material_date: date | None
    material_quantity: Decimal | None
    request_type: str | None


@dataclass(frozen=True)
class TotvsProductionOrder:
    number: str
    production_order_unique_id: str | None
    item_code: str
    item_description: str
    order_type: str | None
    quantity: Decimal
    report_quantity: Decimal | None
    unit_of_measure_code: str | None
    warehouse_code: str | None
    status_order_type: str | None
    report_order_type: str | None
    release_order_date: datetime | None
    start_order_date_time: datetime | None
    end_order_date_time: datetime | None
    script_code: str | None
    priority: str | None
    activities: tuple[TotvsActivityOrder, ...]
    materials: tuple[TotvsMaterialOrder, ...]


@dataclass(frozen=True)
class ProductionOrderMessage:
    metadata: TotvsMessageMetadata
    event: TotvsBusinessEvent
    production_order: TotvsProductionOrder
    raw_xml: str

    @property
    def external_id(self) -> str:
        return (
            self.production_order.production_order_unique_id
            or self.event.internal_id
            or ""
        )


@dataclass(frozen=True)
class TotvsWhoIsMessage:
    """Diagnóstico WhoIs recebido do PCPA109; não carrega dados de negócio."""

    metadata: TotvsMessageMetadata
    identification: tuple[tuple[str, str], ...]
    raw_xml: str

    @property
    def product_name(self) -> str | None:
        return self.metadata.product_name

    @property
    def product_version(self) -> str | None:
        return self.metadata.product_version


@dataclass(frozen=True)
class MappedProductionOrder:
    codigo_op: str
    produto_codigo: str
    produto_descricao: str
    quantidade: int
    unidade: str | None
    status_pcp: str | None
    filial: str | None
    local_estoque: str | None
    roteiro: str | None
    data_liberacao: datetime | None
    inicio_planejado: datetime | None
    fim_planejado: datetime | None
    prioridade: int | None
    totvs_unique_id: str
    totvs_company_id: str | None
    totvs_branch_id: str | None
    totvs_generated_on: datetime | None
    totvs_source_application: str | None


@dataclass(frozen=True)
class MappedProductionOperation:
    codigo_op: str
    produto_codigo: str
    produto_descricao: str
    numero_operacao: str
    codigo_recurso: str
    descricao_operacao: str
    # O marco terminal do roteiro não pertence a nenhum setor do operador.
    tipo_setor: str | None
    filial: str | None
    tipo: str | None
    roteiro: str | None
    ordem: int
    totvs_activity_id: str
    totvs_work_center_code: str | None
    totvs_machine_code: str | None
    # Quando verdadeiro a linha existe apenas como metadado do roteiro TOTVS,
    # necessária ao outbound. Ela é gravada inativa e nunca chega à Tela do
    # Operador, que já filtra ativo IS TRUE.
    marco_terminal: bool = False
    # Operação de inspeção da Qualidade. Também é gravada inativa: ela não é
    # uma etapa de bancada e não pode aparecer no roteiro do posto, mas precisa
    # existir para que a aba Qualidade e o outbound canônico tenham a operação,
    # o recurso e o ``ActivityID`` reais do TOTVS.
    inspecao_qualidade: bool = False


class TotvsActivityClassification(str, Enum):
    """Tratamento semântico explícito de cada ActivityOrder recebida."""

    POINTABLE_CONFIRMED = "APONTÁVEL CONFIRMADO"
    POINTABLE_MAINTENANCE = "APONTÁVEL EM MANUTENÇÃO"
    QUALITY_INSPECTION = "INSPEÇÃO DE QUALIDADE CONFIRMADA"
    AUTOMATIC_SATISFIED = "AUTOMÁTICA/NÃO MANUAL SATISFEITA"
    TERMINAL_CONFIRMED = "ETAPA TERMINAL CONFIRMADA"
    NON_POINTABLE_CONFIRMED = "NÃO APONTÁVEL CONFIRMADO"
    PENDING_DECISION = "PENDENTE DE DECISÃO"


@dataclass(frozen=True)
class TotvsActivityTreatment:
    activity_id: str | None
    activity_code: str | None
    activity_description: str | None
    work_center_code: str | None
    machine_code: str | None
    sector: str | None
    resource_code: str | None
    classification: TotvsActivityClassification
    reason: str
    decision_source: str


@dataclass(frozen=True)
class TotvsMappingResult:
    order: MappedProductionOrder
    operations: tuple[MappedProductionOperation, ...]
    activity_treatments: tuple[TotvsActivityTreatment, ...]
    warnings: tuple[str, ...]
    activities_parsed: int


@dataclass(frozen=True)
class TotvsIngestionResult:
    message_id: int
    payload_hash: str
    transaction: str | None
    external_id: str | None
    status: str
    action: str
    activities_parsed: int
    activities_projected: int
    warnings: tuple[str, ...]
    idempotent: bool = False


@dataclass(frozen=True)
class TotvsDiagnosticResult:
    """Resultado de mensagem somente leitura registrada apenas na inbox."""

    message_id: int
    payload_hash: str
    transaction: str
    status: str
    action: str
    response_xml: str
    idempotent: bool = False


@dataclass(frozen=True)
class TotvsMessageOutcome:
    """Resultado neutro para o transporte SOAP decidir o receiveMessageResult."""

    transaction: str
    soap_result: str | None = None
    ingestion: TotvsIngestionResult | None = None
    diagnostic: TotvsDiagnosticResult | None = None

