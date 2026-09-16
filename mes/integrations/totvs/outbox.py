"""Domínio puro da outbox transacional do outbound TOTVS.

Este módulo não conhece PostgreSQL, HTTP, FastAPI ou a Tela do Operador. Ele
define apenas:

* os estados possíveis de uma mensagem lógica;
* a classificação de uma tentativa de entrega em transitória, permanente,
  funcional ou bem-sucedida;
* o backoff determinístico usado para calcular ``next_attempt_at``.

O transporte é assumido como *at least once*: o mesmo ``idempotency_key`` pode
chegar mais de uma vez ao WSPCP. A aproximação de "efeito uma única vez" vem da
chave determinística e do próprio Protheus (``A680OPTOT`` recusa reapontar uma
operação já totalizada). Não existe garantia de *exactly once* e este código
não a promete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class OutboxStatus(str, Enum):
    """Estados mínimos exigidos pela Etapa 6."""

    PENDING = "PENDING"
    SENDING = "SENDING"
    RETRY = "RETRY"
    SENT = "SENT"
    ERROR = "ERROR"


ACTIVE_STATUSES = (OutboxStatus.PENDING, OutboxStatus.SENDING, OutboxStatus.RETRY)
TERMINAL_STATUSES = (OutboxStatus.SENT, OutboxStatus.ERROR)


class DeliveryClass(str, Enum):
    """Como uma tentativa deve ser interpretada pela política de retry."""

    # Entregue e aceito pelo Protheus (ou já processado antes).
    SUCCESS = "success"
    # Falha de transporte/indisponibilidade: repetir com backoff.
    TRANSIENT = "transient"
    # Credencial/endpoint/configuração: repetir poucas vezes e parar.
    AUTHENTICATION = "authentication"
    # HTTP respondeu algo fora do contrato SOAP conhecido.
    PROTOCOL = "protocol"
    # ACK HTTP 200 com ProcessingInformation/Status=ERROR: rejeição de negócio.
    FUNCTIONAL = "functional"


# Backoff previsível pedido na Etapa 6: 1, 2, 5, 10, 30 e 60 minutos. O último
# degrau se repete até o limite de tentativas.
BACKOFF_SECONDS: tuple[int, ...] = (60, 120, 300, 600, 1800, 3600)

# Limite padrão de tentativas para falhas transitórias. Com o backoff acima,
# doze tentativas cobrem aproximadamente oito horas de indisponibilidade.
DEFAULT_MAX_ATTEMPTS = 12

# Falha de autenticação/configuração não é corrigida por insistência: poucas
# tentativas espaçadas e então ERROR explicitamente identificado.
DEFAULT_MAX_AUTHENTICATION_ATTEMPTS = 3

# HTTP que comprovadamente indica indisponibilidade temporária do serviço.
TRANSIENT_HTTP_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509})

# HTTP que indica credencial errada, não indisponibilidade.
AUTHENTICATION_HTTP_STATUS = frozenset({401, 403, 407})

# Marcas do SOAP Fault observado no TESTE quando a credencial não passa. O
# WSPCP responde HTTP 500, e não 401/403, então o texto do Fault é o único
# sinal disponível para não tratar credencial errada como indisponibilidade.
_AUTHENTICATION_FAULT_MARKS = (
    "AUTHENTICATION",
    "NOT AUTHORIZED",
    "UNAUTHORIZED",
)


def backoff_delay_seconds(attempts: int) -> int:
    """Atraso do próximo envio a partir do número de tentativas já feitas."""

    index = max(0, int(attempts or 0) - 1)
    if index >= len(BACKOFF_SECONDS):
        return BACKOFF_SECONDS[-1]
    return BACKOFF_SECONDS[index]


def next_attempt_at(now: datetime, attempts: int) -> datetime:
    """``next_attempt_at`` persistido no banco, em hora local do Gestor."""

    return (now + timedelta(seconds=backoff_delay_seconds(attempts))).replace(microsecond=0)


@dataclass(frozen=True)
class DeliveryAttempt:
    """Resultado bruto de uma tentativa, antes de virar política de retry."""

    succeeded: bool = False
    http_status: int | None = None
    ack_status: str | None = None
    already_processed: bool = False
    internal_id: str | None = None
    transport_failure: str | None = None
    soap_fault: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: str | None = None


@dataclass(frozen=True)
class DeliveryDecision:
    """O que a outbox deve gravar depois de uma tentativa."""

    delivery_class: DeliveryClass
    status: OutboxStatus
    retryable: bool
    error_code: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is OutboxStatus.SENT


def _looks_like_authentication(text: str | None) -> bool:
    marker = str(text or "").upper()
    return any(mark in marker for mark in _AUTHENTICATION_FAULT_MARKS)


# Marca observada no TESTE em 16/09/2026, em 3 ocorrências (duas delas sem
# nenhuma chamada concorrente): o WSPCP recusa com ACK HTTP 200/Status=ERROR
# uma colisão de chave única na tabela interna dele mesmo (SMO010, gerador de
# ID de apontamento). Não é rejeição de dado/negócio — é o próprio TOTVS
# tropeçando no ID que ele gera; reenviar com uma nova tentativa tende a
# receber um ID diferente e ter sucesso, diferente de "sem saldo" ou "sem
# empenho", que reenviar nunca resolve.
_TRANSIENT_DUPLICATE_KEY_MARKS = ("SMO010", "DUPLICATE KEY")


def _looks_like_transient_duplicate_key(text: str | None) -> bool:
    marker = str(text or "").upper()
    return any(mark in marker for mark in _TRANSIENT_DUPLICATE_KEY_MARKS)


def classify_attempt(
    attempt: DeliveryAttempt,
    *,
    attempts: int,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_authentication_attempts: int = DEFAULT_MAX_AUTHENTICATION_ATTEMPTS,
) -> DeliveryDecision:
    """Traduz uma tentativa em estado final da outbox.

    A ordem das verificações reflete o que foi comprovado no TESTE:

    1. sucesso, ou duplicidade já reconhecida pelo Protheus;
    2. ACK HTTP 200 com ``Status=ERROR`` é rejeição funcional determinística e
       **não** é reenviado em laço;
    3. credencial/publicação erradas param cedo, com código próprio;
    4. timeout, rede e 5xx de indisponibilidade repetem com backoff.
    """

    if attempt.succeeded:
        return DeliveryDecision(
            delivery_class=DeliveryClass.SUCCESS,
            status=OutboxStatus.SENT,
            retryable=False,
        )

    ack_status = str(attempt.ack_status or "").strip().upper()
    if ack_status and ack_status != "OK":
        if _looks_like_transient_duplicate_key(attempt.error_message):
            # Falha técnica do próprio WSPCP (colisão de ID interno), não
            # rejeição de dado: repete com o mesmo backoff de indisponibilidade
            # em vez de travar em ERROR exigindo reprocessamento manual.
            exhausted = int(attempts) >= int(max_attempts)
            return DeliveryDecision(
                delivery_class=DeliveryClass.TRANSIENT,
                status=OutboxStatus.ERROR if exhausted else OutboxStatus.RETRY,
                retryable=not exhausted,
                error_code=attempt.error_code or "totvs_colisao_id_interno",
                error_message=attempt.error_message,
            )
        # Rejeição de negócio do Protheus (A680OPTOT, quantidade inválida,
        # falta de saldo, OP/recurso/operação inválidos). Reenviar não muda o
        # resultado; a correção é humana ou de dado.
        return DeliveryDecision(
            delivery_class=DeliveryClass.FUNCTIONAL,
            status=OutboxStatus.ERROR,
            retryable=False,
            error_code=attempt.error_code or "ack_funcional_error",
            error_message=attempt.error_message,
        )

    http_status = attempt.http_status
    authentication = (
        (http_status in AUTHENTICATION_HTTP_STATUS)
        or _looks_like_authentication(attempt.soap_fault)
        or _looks_like_authentication(attempt.error_message)
    )
    if authentication:
        exhausted = int(attempts) >= int(max_authentication_attempts)
        return DeliveryDecision(
            delivery_class=DeliveryClass.AUTHENTICATION,
            status=OutboxStatus.ERROR if exhausted else OutboxStatus.RETRY,
            retryable=not exhausted,
            error_code=attempt.error_code or "autenticacao_ou_configuracao",
            error_message=attempt.error_message,
        )

    if attempt.transport_failure or (http_status in TRANSIENT_HTTP_STATUS):
        exhausted = int(attempts) >= int(max_attempts)
        return DeliveryDecision(
            delivery_class=DeliveryClass.TRANSIENT,
            status=OutboxStatus.ERROR if exhausted else OutboxStatus.RETRY,
            retryable=not exhausted,
            # A causa do retry é o transporte ou o próprio HTTP; um código de
            # parsing seria mais preciso sobre o corpo e menos sobre a falha.
            error_code=attempt.transport_failure
            or (f"http_{http_status}" if http_status else None)
            or attempt.error_code
            or "falha_transitoria",
            error_message=attempt.error_message,
        )

    if http_status is not None and 400 <= http_status < 500:
        # 400/404/405/415: publicação, rota ou content-type errados. Isso é
        # configuração, não indisponibilidade.
        exhausted = int(attempts) >= int(max_authentication_attempts)
        return DeliveryDecision(
            delivery_class=DeliveryClass.AUTHENTICATION,
            status=OutboxStatus.ERROR if exhausted else OutboxStatus.RETRY,
            retryable=not exhausted,
            error_code=f"http_{http_status}",
            error_message=attempt.error_message,
        )

    # HTTP 200 sem ACK legível: o Protheus pode ter processado. Não inventamos
    # nova identidade; repetimos poucas vezes com a MESMA chave e paramos.
    exhausted = int(attempts) >= int(max_authentication_attempts)
    return DeliveryDecision(
        delivery_class=DeliveryClass.PROTOCOL,
        status=OutboxStatus.ERROR if exhausted else OutboxStatus.RETRY,
        retryable=not exhausted,
        error_code=attempt.error_code or "resposta_fora_do_contrato",
        error_message=attempt.error_message,
    )


@dataclass(frozen=True)
class OutboxEnqueueRequest:
    """Item gravado na MESMA transação do fato canônico.

    ``payload_xml`` é a mensagem exata que será transmitida. Ela é montada no
    instante do fato e nunca reconstruída a partir do estado atual, para que um
    retry às 15:00 represente o evento das 10:00.

    Quando o contrato não pode ser montado por falta de parâmetro homologado
    (código de refugo, motivo de parada) ou por divergência de recurso, o item
    é gravado como ``ERROR`` bloqueado, com ``payload_xml`` nulo. Nada se perde
    e nada é inventado: depois de configurado o parâmetro, o reprocessamento
    monta o payload a partir do MESMO fato canônico imutável.
    """

    event_type: str
    aggregate_type: str
    aggregate_id: str
    idempotency_key: str
    transaction: str
    production_order: str
    operation_code: str | None = None
    canonical_event_id: int | None = None
    payload_xml: str | None = None
    payload_context: dict = field(default_factory=dict)
    status: OutboxStatus = OutboxStatus.PENDING
    error_code: str | None = None
    error_message: str | None = None

    @property
    def blocked(self) -> bool:
        return self.payload_xml is None


__all__ = [
    "ACTIVE_STATUSES",
    "AUTHENTICATION_HTTP_STATUS",
    "BACKOFF_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_AUTHENTICATION_ATTEMPTS",
    "DeliveryAttempt",
    "DeliveryClass",
    "DeliveryDecision",
    "OutboxEnqueueRequest",
    "OutboxStatus",
    "TERMINAL_STATUSES",
    "TRANSIENT_HTTP_STATUS",
    "backoff_delay_seconds",
    "classify_attempt",
    "next_attempt_at",
]
