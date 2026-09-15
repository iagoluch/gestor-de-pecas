"""Mapeamento do DTO TOTVS para o catálogo canônico de planejamento."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation

from app.core.quality import is_quality_inspection_signature
from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.models import (
    MappedProductionOperation,
    MappedProductionOrder,
    ProductionOrderMessage,
    TotvsActivityClassification,
    TotvsActivityTreatment,
    TotvsMappingResult,
)
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver


def _optional_int(value: str | None, field: str) -> int | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise TotvsContractError(f"{field} deve ser inteiro quando preenchido.") from exc
    if parsed != parsed.to_integral_value():
        raise TotvsContractError(f"{field} deve ser inteiro quando preenchido.")
    return int(parsed)


def _activity_value(value: str | None) -> str:
    return str(value or "").strip() or "<vazio>"


def _normalized_activity_value(value: str | None) -> str:
    return str(value or "").strip().casefold()


def _activity_diagnostic(
    activity,
    label: str,
    classification: TotvsActivityClassification,
    reason: str,
) -> str:
    return (
        f"activity_{label} [{classification.value}]: "
        f"{reason}; ActivityCode={_activity_value(activity.activity_code)}; "
        f"WorkCenterCode={_activity_value(activity.work_center_code)}; "
        f"MachineCode={_activity_value(activity.machine_code)}; "
        "etapa preservada somente no XML/inbox"
    )


def _pending_warning(activity, label: str, reason: str) -> str:
    return _activity_diagnostic(
        activity,
        label,
        TotvsActivityClassification.PENDING_DECISION,
        reason,
    )


class TotvsProductionOrderMapper:
    def __init__(
        self,
        resolver: TotvsResourceResolver | None = None,
        *,
        default_branch_id: str | None = None,
    ):
        self.resolver = resolver or TotvsResourceResolver()
        self.default_branch_id = str(default_branch_id or "").strip() or None

    def map(self, message: ProductionOrderMessage) -> TotvsMappingResult:
        # Piloto roda em filial única; quando o TOTVS não informa BranchId no
        # envelope, assume a filial configurada em vez de gravar vazio. Aplicado
        # uma única vez aqui para que cabeçalho, operações e marco terminal
        # herdem o mesmo valor sem duplicar a regra em cada ponto de uso.
        if not str(message.metadata.branch_id or "").strip() and self.default_branch_id:
            message = replace(
                message, metadata=replace(message.metadata, branch_id=self.default_branch_id)
            )
        source = message.production_order
        external_id = message.external_id
        if not external_id:
            raise TotvsContractError("Identificador corporativo da OP ausente.")
        if source.quantity <= 0 or source.quantity != source.quantity.to_integral_value():
            raise TotvsContractError(
                "Quantity deve ser um inteiro positivo para o catálogo atual do Gestor."
            )

        order = MappedProductionOrder(
            codigo_op=source.number,
            produto_codigo=source.item_code,
            produto_descricao=source.item_description,
            quantidade=int(source.quantity),
            unidade=source.unit_of_measure_code,
            status_pcp=source.status_order_type,
            filial=message.metadata.branch_id,
            local_estoque=source.warehouse_code,
            roteiro=source.script_code,
            data_liberacao=source.release_order_date,
            inicio_planejado=source.start_order_date_time,
            fim_planejado=source.end_order_date_time,
            prioridade=_optional_int(source.priority, "Priority"),
            totvs_unique_id=external_id,
            totvs_company_id=message.metadata.company_id,
            totvs_branch_id=message.metadata.branch_id,
            totvs_generated_on=message.metadata.generated_on,
            totvs_source_application=message.metadata.source_application,
        )

        operations = []
        treatments = []
        warnings = []
        seen_activity_ids = set()
        for order_index, activity in enumerate(source.activities, start=1):
            activity_id = str(activity.activity_id or "").strip()
            label = activity_id or f"posição_{order_index}"
            if not activity_id:
                reason = "ActivityID ausente; etapa não projetada"
                warnings.append(_pending_warning(activity, label, reason))
                treatments.append(
                    self._treatment(
                        activity,
                        classification=TotvsActivityClassification.PENDING_DECISION,
                        reason=reason,
                    )
                )
                continue
            if activity_id in seen_activity_ids:
                raise TotvsContractError(
                    f"ActivityID duplicado na mesma ProductionOrder: {activity_id}."
                )
            seen_activity_ids.add(activity_id)

            special = self._special_treatment(activity)
            if special:
                classification, reason = special
                warnings.append(
                    _activity_diagnostic(
                        activity,
                        label,
                        classification,
                        reason,
                    )
                )
                treatments.append(
                    self._treatment(
                        activity,
                        classification=classification,
                        reason=reason,
                    )
                )
                if classification is TotvsActivityClassification.TERMINAL_CONFIRMED:
                    terminal = self._metadata_operation(
                        activity,
                        source=source,
                        message=message,
                        activity_id=activity_id,
                        order_index=order_index,
                        marco_terminal=True,
                    )
                    if terminal is not None:
                        operations.append(terminal)
                elif classification is TotvsActivityClassification.QUALITY_INSPECTION:
                    inspection = self._metadata_operation(
                        activity,
                        source=source,
                        message=message,
                        activity_id=activity_id,
                        order_index=order_index,
                        inspecao_qualidade=True,
                    )
                    if inspection is not None:
                        operations.append(inspection)
                continue

            sector = self.resolver.resolve_sector(activity)
            if not sector:
                reason = (
                    "setor não mapeado para "
                    f"{activity.activity_description or '<vazio>'}"
                )
                warnings.append(_pending_warning(activity, label, reason))
                treatments.append(
                    self._treatment(
                        activity,
                        classification=TotvsActivityClassification.PENDING_DECISION,
                        reason=reason,
                    )
                )
                continue
            resource = self.resolver.resolve_resource(activity, sector=sector)
            if not resource:
                reason = (
                    "recurso não mapeado para "
                    f"{activity.machine_code or activity.work_center_code or '<vazio>'}"
                )
                warnings.append(_pending_warning(activity, label, reason))
                treatments.append(
                    self._treatment(
                        activity,
                        sector=sector,
                        classification=TotvsActivityClassification.PENDING_DECISION,
                        reason=reason,
                    )
                )
                continue
            operation_code = str(activity.activity_code or "").strip()
            description = str(activity.activity_description or "").strip()
            if not operation_code or not description:
                reason = "código/descrição operacional ausente; etapa não projetada"
                warnings.append(_pending_warning(activity, label, reason))
                treatments.append(
                    self._treatment(
                        activity,
                        sector=sector,
                        resource=resource,
                        classification=TotvsActivityClassification.PENDING_DECISION,
                        reason=reason,
                    )
                )
                continue
            operations.append(
                MappedProductionOperation(
                    codigo_op=source.number,
                    produto_codigo=source.item_code,
                    produto_descricao=source.item_description,
                    numero_operacao=operation_code,
                    codigo_recurso=resource,
                    descricao_operacao=description,
                    tipo_setor=sector,
                    filial=message.metadata.branch_id,
                    tipo=activity.activity_type,
                    roteiro=activity.script_code or source.script_code,
                    ordem=order_index,
                    totvs_activity_id=activity_id,
                    totvs_work_center_code=activity.work_center_code,
                    totvs_machine_code=activity.machine_code,
                )
            )
            treatments.append(
                self._treatment(
                    activity,
                    sector=sector,
                    resource=resource,
                    classification=TotvsActivityClassification.POINTABLE_CONFIRMED,
                    reason="setor e recurso resolvidos pelo mapeamento canônico exato",
                )
            )
        return TotvsMappingResult(
            order=order,
            operations=tuple(operations),
            activity_treatments=tuple(treatments),
            warnings=tuple(warnings),
            activities_parsed=len(source.activities),
        )

    @staticmethod
    def _metadata_operation(
        activity,
        *,
        source,
        message,
        activity_id: str,
        order_index: int,
        marco_terminal: bool = False,
        inspecao_qualidade: bool = False,
    ) -> MappedProductionOperation | None:
        """Preserva uma etapa não-bancada como metadado do roteiro.

        Duas etapas usam esta forma e nenhuma delas é um posto do operador:

        * o **marco terminal**, que guarda exatamente o que o TOTVS enviou —
          ``ActivityCode``, ``MachineCode`` e ordem — porque é ele que o
          Protheus exige para efetivar a produção (``A680UltOper`` →
          ``A680GeraD3`` → SD3 → ``C2_QUJE``/``C2_DATRF``);
        * a **operação de inspeção da Qualidade**, que precisa do mesmo
          ``ActivityID``/recurso reais para que o apontamento e o outbound
          canônicos existam quando o fluxo chegar nela.

        Não há setor nem recurso do Gestor: nada é inventado e a linha é
        gravada inativa, invisível para o roteiro do posto.
        """

        operation_code = str(activity.activity_code or "").strip()
        machine_code = str(activity.machine_code or "").strip()
        if not operation_code or not machine_code:
            return None
        return MappedProductionOperation(
            codigo_op=source.number,
            produto_codigo=source.item_code,
            produto_descricao=source.item_description,
            numero_operacao=operation_code,
            codigo_recurso=machine_code,
            descricao_operacao=str(activity.activity_description or "").strip(),
            tipo_setor=None,
            filial=message.metadata.branch_id,
            tipo=activity.activity_type,
            roteiro=activity.script_code or source.script_code,
            ordem=order_index,
            totvs_activity_id=activity_id,
            totvs_work_center_code=activity.work_center_code,
            totvs_machine_code=activity.machine_code,
            marco_terminal=marco_terminal,
            inspecao_qualidade=inspecao_qualidade,
        )

    @staticmethod
    def _special_treatment(
        activity,
    ) -> tuple[TotvsActivityClassification, str] | None:
        """Classifica somente assinaturas industriais aprovadas e exatas."""

        signature = (
            _normalized_activity_value(activity.activity_code),
            _normalized_activity_value(activity.activity_description),
            _normalized_activity_value(activity.work_center_code),
            _normalized_activity_value(activity.machine_code),
        )
        if signature == ("01", "impressao op", "pcp", "pcp"):
            return (
                TotvsActivityClassification.AUTOMATIC_SATISFIED,
                "etapa automática/não manual considerada satisfeita por padrão; "
                "não libera tarefa nem cria apontamento fictício",
            )
        if is_quality_inspection_signature(*signature[1:]):
            return (
                TotvsActivityClassification.QUALITY_INSPECTION,
                "operação de inspeção da Qualidade confirmada; projetada como "
                "metadado do roteiro (inativa) e executada pela aba Qualidade, "
                "nunca pelo roteiro do posto",
            )
        if signature == ("99", "finalizada", "almox4", "almox4"):
            return (
                TotvsActivityClassification.TERMINAL_CONFIRMED,
                "marco terminal confirmado; a presença no ProductionOrder não "
                "finaliza a OP durante a ingestão",
            )
        return None

    @staticmethod
    def _treatment(
        activity,
        *,
        classification: TotvsActivityClassification,
        reason: str,
        sector: str | None = None,
        resource: str | None = None,
    ) -> TotvsActivityTreatment:
        return TotvsActivityTreatment(
            activity_id=activity.activity_id,
            activity_code=activity.activity_code,
            activity_description=activity.activity_description,
            work_center_code=activity.work_center_code,
            machine_code=activity.machine_code,
            sector=sector,
            resource_code=resource,
            classification=classification,
            reason=reason,
            decision_source={
                TotvsActivityClassification.POINTABLE_CONFIRMED: (
                    "regra funcional/Manufatura e cadastro/alias canônico exato"
                ),
                TotvsActivityClassification.POINTABLE_MAINTENANCE: (
                    "regra funcional/Manufatura: etapa confirmada, porém Em manutenção"
                ),
                TotvsActivityClassification.QUALITY_INSPECTION: (
                    "regra funcional/Manufatura: operação de inspeção da Qualidade"
                ),
                TotvsActivityClassification.AUTOMATIC_SATISFIED: (
                    "regra funcional/Manufatura: IMPRESSAO OP não manual satisfeita"
                ),
                TotvsActivityClassification.TERMINAL_CONFIRMED: (
                    "regra funcional/Manufatura: FINALIZADA é marco terminal"
                ),
                TotvsActivityClassification.NON_POINTABLE_CONFIRMED: (
                    "regra funcional/Manufatura de etapa não apontável"
                ),
                TotvsActivityClassification.PENDING_DECISION: (
                    "payload TOTVS preservado; sem equivalência industrial aprovada"
                ),
            }[classification],
        )
