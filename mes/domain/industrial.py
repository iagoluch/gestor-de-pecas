"""Tipos semânticos do MES que não dependem de códigos legados do PC Factory."""

from enum import Enum


class EventCategory(str, Enum):
    QUEUE = "fila"
    PRODUCTION = "producao"
    DOWNTIME = "parada"
    SETUP = "setup"
    REWORK = "retrabalho"
    ACTIVITY_WITHOUT_OP = "atividade_sem_op"
    OUT_OF_SHIFT = "fora_turno"
    UNKNOWN = "desconhecido"


PHYSICAL_STATE_VALUES = tuple(category.value for category in EventCategory)


class ShiftWindowKind(str, Enum):
    """Natureza de calendário de um instante, independente de recurso.

    ``turno`` é a janela oficial. ``hora_extra_planejada`` é uma janela fora do
    turno normal que a Manufatura planejou (cadastro de calendário). O restante
    é ``fora_turno``: não é disponibilidade e não é parada de máquina.
    """

    OFFICIAL_SHIFT = "turno"
    PLANNED_OVERTIME = "hora_extra_planejada"
    OUT_OF_SHIFT = "fora_turno"


class StopClassification(str, Enum):
    """Classificação central de parada: planejada ou não planejada.

    A cor apresentada e o efeito sobre o OEE derivam desta classificação; nenhum
    componente de apresentação deve recriar o mapeamento por nome de motivo.
    """

    PLANNED = "planejada"
    UNPLANNED = "nao_planejada"


class QuantityKind(str, Enum):
    GOOD = "boa"
    SCRAP = "refugo"
    REWORK = "retrabalho"


class AllocationStrategy(str, Enum):
    EQUAL = "igualitario"
    QUANTITY = "quantidade"
    STANDARD_TIME = "tempo_padrao"
    PROPORTIONAL = "proporcional"
    MANUAL = "manual"


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "aviso"
    ERROR = "erro"
    CRITICAL = "critico"


class DataAvailability(str, Enum):
    AVAILABLE = "disponivel"
    PARTIAL = "parcial"
    NO_RECORDS = "sem_registros"
    INSUFFICIENT_DATA = "dados_insuficientes"
    NOT_CONFIGURED = "nao_configurado"
    NOT_APPLICABLE = "nao_aplicavel"
