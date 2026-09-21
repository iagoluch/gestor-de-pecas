"""Regras industriais aprovadas para o Gestor de Peças.

Este módulo representa decisões funcionais validadas com a Manufatura. Dados
ou comportamentos observados em PCFactory/MES/Management View são apenas
referência e não podem sobrescrever estas regras.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .industrial import EventCategory, ShiftWindowKind, StopClassification
from .operator_state_machine import OperatorState, operator_status_for_state


#: Status de apontamento que significam execução em curso no recurso.
#: Uma OP nesses estados é trabalho acontecendo agora: nenhuma leitura de
#: ausência de demanda, ociosidade ou fora de turno pode escondê-la.
EXECUTING_APPOINTMENT_STATUSES = frozenset(
    operator_status_for_state(state)
    for state in (
        OperatorState.PRODUCTION,
        OperatorState.SETUP,
        OperatorState.REWORK,
    )
)
#: Apontamentos abertos no recurso: execução mais a parada manual/programada,
#: que mantém a OP vinculada ao posto aguardando retomada.
OPEN_APPOINTMENT_STATUSES = EXECUTING_APPOINTMENT_STATUSES | {
    operator_status_for_state(OperatorState.STOPPED),
}


# Horários de interrupção automática definidos com a Manufatura.
SHIFT_END_BOUNDARIES = (time(17, 30), time(21, 30))
SHIFT_END_REASON = "Fim de turno — interrupção programada automática"
SHIFT_END_INTERRUPTION_TYPE = "fim_turno"
SHIFT_START_NO_DEMAND_REASON = "Retorno do turno — recurso sem demanda"
SHIFT_START_NO_DEMAND_TYPE = "retorno_turno_sem_demanda"
AUTOMATIC_BREAKS = (
    (time(12, 10), time(12, 52), "Almoço"),
    (time(15, 30), time(15, 45), "Café"),
)
AUTOMATIC_BREAK_INTERRUPTION_TYPE = "intervalo_programado"
OFFICIAL_WORK_WINDOW = (time(8, 0), time(17, 30))
OVERTIME_WINDOWS = ((time(6, 0), time(8, 0)), (time(17, 30), time(21, 30)))
SYSTEM_OPERATOR = "SISTEMA"


# Classificação central de parada.
#
# A fonte é o catálogo `catalogo_status_recursos` (origem do sistema corporativo,
# arquivo `TBLResourceStatus.xls`). O Gestor não inventa nomes de motivo: apenas
# acrescenta a classificação PLANEJADA/NÃO_PLANEJADA sobre o cadastro existente.
#
# `0002 — PARADA PROGRAMADA` reúne os motivos planejados (FORA DE TURNO, PAUSA
# PARA CAFÉ, INTERVALO, REUNIÃO, LIMPEZA, MANUTENÇÃO PREVENTIVA...). Todo o
# resto — inclusive `0001 — PRODUÇÃO/Falta de Apontamento` e
# `0006 — PARADA NÃO PLANEJADA/AGUARDANDO OP` — é não planejado.
PLANNED_STOP_GROUP_CODES = ("0002",)

# Cor derivada da classificação. Um único mapa, consumido pela apresentação;
# nenhum componente deve decidir cor por nome de motivo ou por grupo.
STOP_CLASSIFICATION_COLORS = {
    StopClassification.PLANNED: "amarelo",
    StopClassification.UNPLANNED: "vermelho",
}
STOP_CLASSIFICATION_UI_TOKENS = {
    StopClassification.PLANNED: "warning",
    StopClassification.UNPLANNED: "danger",
}

# Condições que a Manufatura classificou explicitamente como NÃO planejadas,
# mesmo quando o motivo chega sem código de catálogo. Os aliases cobrem o nome
# de negócio usado no Gestor e o nome equivalente do catálogo PCFactory.
NO_APPOINTMENT_STOP_REASON = "Sem apontamento"
RESOURCE_WITHOUT_OP_STOP_REASON = "Recurso s/op"
FORCED_UNPLANNED_STOP_REASONS = frozenset({
    "sem apontamento",
    "falta de apontamento",
    "recurso s/op",
    "recurso s/ op",
    "recurso sem op",
    "aguardando op",
})


# Atividade sem OP — trabalho real do posto que não pertence a nenhuma OP.
#
# Corte e Destaque trabalham por tarefa/nesting e têm rotina diária própria
# (organização de chapas, sucata, conferência): o que o operador inicia sem OP
# nesses setores é a atividade diária do posto. Nos demais setores a atividade
# sem OP não tem tipo específico. Quem decide é o setor, nunca o operador.
DAILY_ACTIVITY_KIND = "diaria"
DAILY_ACTIVITY_SECTORS = frozenset({"corte", "destaque"})
ACTIVITY_WITHOUT_OP_LABELS = {DAILY_ACTIVITY_KIND: "Atividade diária"}
DEFAULT_ACTIVITY_WITHOUT_OP_LABEL = "Atividade s/OP"


# Falha de equipamento — taxonomia usada por MTBF/MTTR.
#
# O Gestor não classifica falha por nome de motivo. A única classificação
# confiável já existente é o grupo do catálogo `catalogo_status_recursos`
# (origem `TBLResourceStatus.xls`): o grupo `0003 — MANUTENÇÃO` reúne
# exclusivamente manutenção CORRETIVA. Manutenção preventiva vive no grupo
# `0002 — PARADA PROGRAMADA` e, corretamente, não é falha.
#
# Falta de material, refeição, setup, espera e paradas programadas continuam
# fora: são perdas operacionais, não quebra de equipamento.
EQUIPMENT_FAILURE_STOP_GROUP = "0003"

# A classificação da máquina vem do campo ``MachineName`` do SigmaNEST e é
# deliberadamente exata. Só a Laser libera o Destaque; Plasma permanece no
# histórico do Corte, mas nunca entra na fila de Destaque.
SIGMANEST_LASER_MACHINE = "AMADA_ENSIS"
SIGMANEST_PLASMA_MACHINE = "MESSER_XPR_300"


@dataclass(frozen=True)
class ManufacturingRules:
    """Políticas canônicas compartilhadas por todos os casos de uso Web."""

    shift_end_boundaries: tuple[time, ...] = SHIFT_END_BOUNDARIES
    automatic_breaks: tuple[tuple[time, time, str], ...] = AUTOMATIC_BREAKS
    official_work_window: tuple[time, time] = OFFICIAL_WORK_WINDOW
    overtime_windows: tuple[tuple[time, time], ...] = OVERTIME_WINDOWS

    @staticmethod
    def attended_quantity(good_quantity: int, scrap_quantity: int = 0) -> int:
        """Quantidade que atende o lote: peças boas + refugo.

        Retrabalho continua pendente e não participa desta soma. As grandezas
        permanecem separadas na persistência e nos contratos de integração.
        """

        good = max(0, int(good_quantity or 0))
        scrap = max(0, int(scrap_quantity or 0))
        return good + scrap

    @classmethod
    def quantity_remaining(
        cls,
        planned_quantity: int,
        good_quantity: int,
        scrap_quantity: int = 0,
    ) -> int:
        """Saldo canônico: planejado - (boas + refugo)."""

        planned = max(0, int(planned_quantity or 0))
        return max(0, planned - cls.attended_quantity(good_quantity, scrap_quantity))

    @classmethod
    def good_quantity_remaining(
        cls,
        planned_quantity: int,
        good_quantity: int,
        scrap_quantity: int = 0,
    ) -> int:
        """Alias compatível do saldo; novos consumidores usam ``quantity_remaining``."""

        return cls.quantity_remaining(planned_quantity, good_quantity, scrap_quantity)

    @classmethod
    def operation_is_complete(
        cls,
        planned_quantity: int,
        good_quantity: int,
        scrap_quantity: int = 0,
    ) -> bool:
        """Boas + refugo atendem o planejado; retrabalho não completa a OP."""

        planned = max(0, int(planned_quantity or 0))
        return planned > 0 and cls.attended_quantity(good_quantity, scrap_quantity) >= planned

    @staticmethod
    def cut_releases_highlight(machine_name: str) -> bool:
        """Decide por identidade exata se um plano de Corte vai ao Destaque."""

        return str(machine_name or "").strip().upper() == SIGMANEST_LASER_MACHINE

    @staticmethod
    def is_productive(category: EventCategory | str) -> bool:
        """Classificação produtiva aprovada pela Manufatura.

        Produção, Setup e Atividade sem OP são produtivos. Parada, Retrabalho,
        Fila, Recurso sem demanda e Fora de turno não são produtivos.
        """

        category = EventCategory(category)
        return category in {
            EventCategory.PRODUCTION,
            EventCategory.SETUP,
            EventCategory.ACTIVITY_WITHOUT_OP,
        }

    @staticmethod
    def activity_kind_for_sector(sector: str | None) -> str | None:
        """Tipo da atividade sem OP a gravar para o setor informado."""

        key = str(sector or "").strip().casefold()
        return DAILY_ACTIVITY_KIND if key in DAILY_ACTIVITY_SECTORS else None

    @staticmethod
    def activity_display_label(activity_kind: str | None) -> str:
        """Rótulo da atividade sem OP, único para Andon, tela e relatório."""

        key = str(activity_kind or "").strip().casefold()
        return ACTIVITY_WITHOUT_OP_LABELS.get(key, DEFAULT_ACTIVITY_WITHOUT_OP_LABEL)

    # ------------------------------------------------------------------
    # Calendário operacional
    # ------------------------------------------------------------------

    @classmethod
    def shift_window_kind(
        cls,
        timestamp: datetime,
        *,
        planned_overtime_windows=None,
    ) -> ShiftWindowKind:
        """Classifica um instante em turno / hora extra planejada / fora de turno.

        ``planned_overtime_windows`` é o que a Manufatura planejou para o dia,
        vindo do cadastro de calendário (exceções ``disponivel_extra``). Quando
        vazio, toda a faixa 17:30→08:00 permanece fora de turno.

        A janela oficial é fechada nas duas pontas: 08:00 é o início do turno e
        17:30 é o seu fim. O mesmo vale para as janelas de hora extra, cujo
        limite superior (ex.: 21:30) ainda pertence à janela planejada.
        """

        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp deve ser datetime")
        moment = timestamp.time()
        start, end = cls.official_work_window
        if _time_within(moment, start, end):
            return ShiftWindowKind.OFFICIAL_SHIFT
        for window_start, window_end in planned_overtime_windows or ():
            if _time_within(_as_time(moment), _as_time(window_start), _as_time(window_end)):
                return ShiftWindowKind.PLANNED_OVERTIME
        return ShiftWindowKind.OUT_OF_SHIFT

    @staticmethod
    def is_operational_window(kind: ShiftWindowKind | str) -> bool:
        """Turno e hora extra planejada compõem a janela operacional planejada."""

        return ShiftWindowKind(kind) in {
            ShiftWindowKind.OFFICIAL_SHIFT,
            ShiftWindowKind.PLANNED_OVERTIME,
        }

    @classmethod
    def counts_as_availability(cls, kind: ShiftWindowKind | str) -> bool:
        """Fora de turno nunca compõe disponibilidade nem parada de máquina."""

        return cls.is_operational_window(kind)

    @staticmethod
    def state_is_no_demand(*, category=None, interruption_type=None, operation=None) -> bool:
        """Decide se um estado físico persistido significa ausência de demanda.

        ``fila`` sem OP significa recurso sem demanda, independentemente da
        origem que criou o estado. Uma fila vinculada a OP continua fila: a
        presença da ordem é evidência de demanda e não pode ser apagada.

        Fonte única desta decisão. A análise usa esta função para derivar
        ``EventCategory.NO_DEMAND`` e o Andon usa ``resource_has_no_demand``,
        que delega o mesmo caso para cá.
        """

        value = (
            category.value if isinstance(category, EventCategory) else str(category or "")
        ).strip()
        if value == EventCategory.NO_DEMAND.value:
            return not str(operation or "").strip()
        return (
            value == EventCategory.QUEUE.value
            and not str(operation or "").strip()
        )

    @classmethod
    def resource_has_no_demand(
        cls,
        *,
        category=None,
        window_kind,
        active_operations=0,
        explicit_shift_return=False,
        operation=None,
    ) -> bool:
        """Decide se o recurso sem OP deve ser exibido como sem demanda.

        Este é o complemento explícito da regra já existente ``fora de turno
        sem hora extra não vira parada não planejada``: além de não contar como
        parada, o caso ganha nome próprio. Ausência de demanda **não** é parada
        (nem planejada nem não planejada) e **não** é ociosidade dentro do
        turno — são três leituras diferentes e o Andon precisa distingui-las.

        A decisão mora aqui, no domínio, e não na tela: a projeção do Andon e
        qualquer outro consumidor perguntam para esta função.
        """

        # Execução registrada vence qualquer leitura de ausência de demanda,
        # inclusive a do retorno do turno. O estado físico é a leitura do
        # último evento do recurso e pode estar defasado (Corte interrompido
        # sem encerrar o nesting, limite de turno recuperado retroativamente);
        # apontamento ativo é fato. Divergiram: o fato manda, senão uma OP em
        # execução sumiria do Andon.
        if int(active_operations or 0) > 0:
            return False
        if cls.state_is_no_demand(category=category, operation=operation):
            return True
        # Compatibilidade com o marcador criado na abertura do turno. A regra
        # principal já cobre qualquer fila sem OP, mesmo sem esse marcador.
        if explicit_shift_return:
            return cls.state_is_no_demand(
                category=category,
                interruption_type=SHIFT_START_NO_DEMAND_TYPE,
                operation=operation,
            )
        if cls.is_operational_window(window_kind):
            return False
        if category in (None, ""):
            return True
        try:
            return EventCategory(category) in {
                EventCategory.OUT_OF_SHIFT,
                EventCategory.QUEUE,
                EventCategory.NO_DEMAND,
                EventCategory.UNKNOWN,
            }
        except (TypeError, ValueError):
            return False

    @staticmethod
    def appointment_allowed_at(_timestamp: datetime) -> bool:
        """O relógio, sozinho, nunca bloqueia apontamento.

        18:00, 21:30, 01:00, 06:00 ou 07:30 são horários operacionalmente
        válidos. Fora de turno muda a contabilidade de disponibilidade, não a
        permissão de apontar. Bloqueios legítimos (primeira peça, qualidade,
        crachá, transição inválida) continuam nas suas próprias regras.
        """

        return True

    # ------------------------------------------------------------------
    # Classificação de parada
    # ------------------------------------------------------------------

    @classmethod
    def classify_stop(
        cls,
        *,
        category=None,
        status_row=None,
        status_group=None,
        reason=None,
        planned=None,
    ) -> StopClassification:
        """Classificação central PLANEJADA / NÃO_PLANEJADA de uma parada.

        Precedência: motivos que a Manufatura fixou como não planejados, depois
        fora de turno, depois a taxonomia explícita do catálogo (``planejado``),
        depois o grupo do catálogo e, por último, a marca de interrupção
        programada do próprio evento. Sem evidência de planejamento, a parada é
        não planejada — o sistema não esconde perda por omissão de cadastro.
        """

        if _normalized_reason(reason) in FORCED_UNPLANNED_STOP_REASONS:
            return StopClassification.UNPLANNED

        if category is not None:
            try:
                if EventCategory(category) is EventCategory.OUT_OF_SHIFT:
                    return StopClassification.PLANNED
            except (TypeError, ValueError):
                pass

        row = dict(status_row or {})
        if _normalized_reason(row.get("nome")) in FORCED_UNPLANNED_STOP_REASONS:
            return StopClassification.UNPLANNED
        if row.get("planejado") is not None:
            return (
                StopClassification.PLANNED
                if bool(row["planejado"])
                else StopClassification.UNPLANNED
            )

        group = str(
            status_group if status_group is not None else row.get("grupo_codigo") or ""
        ).strip()
        if group:
            return (
                StopClassification.PLANNED
                if group in PLANNED_STOP_GROUP_CODES
                else StopClassification.UNPLANNED
            )

        if planned is not None:
            return (
                StopClassification.PLANNED if planned else StopClassification.UNPLANNED
            )
        return StopClassification.UNPLANNED

    @staticmethod
    def stop_classification_color(classification: StopClassification | str) -> str:
        return STOP_CLASSIFICATION_COLORS[StopClassification(classification)]

    @staticmethod
    def stop_classification_ui_token(classification: StopClassification | str) -> str:
        return STOP_CLASSIFICATION_UI_TOKENS[StopClassification(classification)]

    @staticmethod
    def stop_affects_oee(classification: StopClassification | str) -> bool:
        """Parada planejada não afeta OEE; parada não planejada afeta."""

        return StopClassification(classification) is StopClassification.UNPLANNED

    @staticmethod
    def manual_stop_is_planned() -> bool:
        """Paradas lançadas manualmente pelo operador são não programadas."""

        return False

    @staticmethod
    def automatic_stop_is_planned() -> bool:
        """Interrupções automáticas do sistema são programadas."""

        return True

    @staticmethod
    def stop_reason_is_equipment_failure(status_row) -> bool:
        """Decide, pelo catálogo, se um motivo de parada é falha de equipamento.

        A decisão vem do grupo cadastrado, nunca do texto do motivo. Setup e
        retrabalho estão explicitamente fora mesmo que algum dia sejam
        cadastrados dentro do grupo de manutenção.
        """

        row = dict(status_row or {})
        if row.get("setup") or row.get("retrabalho"):
            return False
        grupo = str(row.get("grupo_codigo") or "").strip()
        return bool(grupo) and grupo == EQUIPMENT_FAILURE_STOP_GROUP


def _as_time(value) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    raise TypeError("janela de calendário deve usar datetime.time")


def _time_within(moment: time, start: time, end: time) -> bool:
    """Contém o instante na janela, tratando janelas que cruzam a meia-noite.

    As pontas são fechadas: o início e o fim da janela pertencem a ela.
    """

    if end == start:
        return moment == start
    if end > start:
        return start <= moment <= end
    return moment >= start or moment <= end


def _normalized_reason(value) -> str:
    text = " ".join(str(value or "").split()).strip().strip(".").casefold()
    for accented, plain in (
        ("á", "a"), ("à", "a"), ("ã", "a"), ("â", "a"),
        ("é", "e"), ("ê", "e"), ("í", "i"),
        ("ó", "o"), ("õ", "o"), ("ô", "o"),
        ("ú", "u"), ("ç", "c"),
    ):
        text = text.replace(accented, plain)
    return text


def planned_overtime_windows_from_intervals(intervals, *, reference_date=None):
    """Converte intervalos datados de hora extra em janelas ``time``.

    O cadastro de hora extra vive nas exceções ``disponivel_extra`` do
    calendário, que são datadas. A classificação de instante trabalha com
    horários; esta função faz a ponte sem criar um segundo cadastro.
    """

    windows = []
    for start, end in intervals or ():
        if not isinstance(start, datetime) or not isinstance(end, datetime):
            continue
        if end <= start:
            continue
        if reference_date is not None and not (
            start.date() == reference_date or (end - timedelta(microseconds=1)).date() == reference_date
        ):
            continue
        windows.append((start.time(), end.time()))
    return tuple(windows)
