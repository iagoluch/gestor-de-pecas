"""Persistência da outbox transacional do outbound TOTVS.

Separação explícita entre as duas fronteiras da Etapa 6:

* **ENQUEUE** — ``enfileirar_outbound_totvs_tx`` só existe com um ``cursor``
  recebido de fora. Ele é chamado de dentro da transação que grava o fato
  canônico, nunca abre conexão própria e nunca faz commit. Se o apontamento do
  operador for revertido, o item outbound é revertido junto.
* **DELIVERY** — reserva, conclusão, recuperação de lease e reprocessamento
  abrem transações curtas e independentes do request do operador.

Nenhum método aqui conhece SOAP, HTTP ou a Tela do Operador.
"""

from __future__ import annotations

from datetime import timedelta
import json
import logging

from psycopg.types.json import Jsonb

from mes.integrations.totvs.outbox import (
    DEFAULT_MAX_ATTEMPTS,
    OutboxEnqueueRequest,
    OutboxStatus,
    next_attempt_at,
)


logger = logging.getLogger(__name__)


OUTBOX_COLUMNS = """
    id, event_type, aggregate_type, aggregate_id, canonical_event_id,
    production_order, operation_code, idempotency_key, transaction,
    payload_xml, payload_context, status, attempts, max_attempts,
    next_attempt_at, created_at, updated_at, sent_at, last_attempt_at,
    lease_owner, lease_expires_at, last_http_status, last_ack_status,
    last_delivery_class, last_error_code, last_error_message, internal_id
"""

# ``UPDATE ... FROM`` precisa do alias no RETURNING: sem ele, ``id`` existe nas
# duas relações do plano e o PostgreSQL recusa a consulta.
OUTBOX_COLUMNS_ALIASED = ", ".join(
    f"o.{column.strip()}"
    for column in OUTBOX_COLUMNS.replace("\n", " ").split(",")
    if column.strip()
)

# Mensagens de erro do WSPCP podem trazer payload/segredo por acidente. Mantemos
# evidência suficiente para diagnóstico sem transformar a coluna em dump.
MAX_ERROR_MESSAGE_CHARS = 2000


def _truncate(value, limit: int = MAX_ERROR_MESSAGE_CHARS) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _status_value(status) -> str:
    return status.value if isinstance(status, OutboxStatus) else str(status)


def _as_context(value):
    if isinstance(value, (dict, list)):
        return value
    if value is None:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _outbox_row(row):
    if row is None:
        return None
    item = dict(row)
    item["payload_context"] = _as_context(item.get("payload_context"))
    return item


class TotvsOutboxRepositoryMixin:
    """Mixin da fachada ``Database`` com a fila durável do outbound TOTVS."""

    # ------------------------------------------------------------------
    # ENQUEUE — sempre dentro da transação do fato canônico
    # ------------------------------------------------------------------
    def enfileirar_outbound_totvs_tx(
        self,
        cursor,
        request: OutboxEnqueueRequest,
        *,
        now=None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ):
        """Grava um item usando o cursor da transação em curso.

        ``ON CONFLICT DO NOTHING`` sobre ``idempotency_key`` garante que a
        mesma mensagem lógica não seja duplicada — nem por reprocessamento do
        mesmo fato, nem por dois caminhos que concluam a mesma OP ao mesmo
        tempo. O conflito não aborta a transação do operador.
        """

        instante = (now or self._now()).replace(microsecond=0)
        status = _status_value(request.status)
        cursor.execute(
            f"""
            INSERT INTO totvs_outbox (
                event_type, aggregate_type, aggregate_id, canonical_event_id,
                production_order, operation_code, idempotency_key, transaction,
                payload_xml, payload_context, status, attempts, max_attempts,
                next_attempt_at, created_at, updated_at,
                last_error_code, last_error_message
            ) VALUES (
                %(event_type)s, %(aggregate_type)s, %(aggregate_id)s,
                %(canonical_event_id)s, %(production_order)s, %(operation_code)s,
                %(idempotency_key)s, %(transaction)s, %(payload_xml)s,
                %(payload_context)s, %(status)s, 0, %(max_attempts)s,
                %(now)s, %(now)s, %(now)s, %(error_code)s, %(error_message)s
            )
            ON CONFLICT ON CONSTRAINT uq_totvs_outbox_idempotency_key DO NOTHING
            RETURNING {OUTBOX_COLUMNS}
            """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
            {
                "event_type": str(request.event_type),
                "aggregate_type": str(request.aggregate_type),
                "aggregate_id": str(request.aggregate_id),
                "canonical_event_id": request.canonical_event_id,
                "production_order": str(request.production_order),
                "operation_code": request.operation_code,
                "idempotency_key": str(request.idempotency_key),
                "transaction": str(request.transaction),
                "payload_xml": request.payload_xml,
                "payload_context": Jsonb(dict(request.payload_context or {})),
                "status": status,
                "max_attempts": int(max_attempts),
                "now": instante,
                "error_code": request.error_code,
                "error_message": _truncate(request.error_message),
            },
        )
        return _outbox_row(cursor.fetchone())

    # ------------------------------------------------------------------
    # DELIVERY — transações curtas do worker
    # ------------------------------------------------------------------
    def recuperar_envios_abandonados_totvs(self, *, now=None, limit: int = 50):
        """Devolve à fila os ``SENDING`` cujo lease expirou.

        Cobre o worker/backend que morreu depois de reservar e possivelmente
        depois de postar. A identidade lógica é preservada: a MESMA
        ``idempotency_key`` volta para ``RETRY``, sem novo evento local. O
        transporte é assumido *at least once*.
        """

        instante = (now or self._now()).replace(microsecond=0)
        nota = (
            "Envio interrompido: o worker não concluiu a tentativa dentro do lease."
        )
        recuperados = []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT {OUTBOX_COLUMNS} FROM totvs_outbox
                WHERE status = 'SENDING' AND lease_expires_at <= %(now)s
                ORDER BY lease_expires_at, id
                LIMIT %(limit)s
                FOR UPDATE SKIP LOCKED
                """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                {"now": instante, "limit": int(limit)},
            )
            abandonados = [_outbox_row(row) for row in cursor.fetchall()]
            for item in abandonados:
                tentativas = max(1, int(item["attempts"] or 1))
                esgotado = tentativas >= int(item["max_attempts"] or DEFAULT_MAX_ATTEMPTS)
                destino = OutboxStatus.ERROR if esgotado else OutboxStatus.RETRY
                # O backoff usa a MESMA função de domínio do worker, para que
                # recuperação e retry normal tenham a mesma cadência.
                proximo = next_attempt_at(instante, tentativas)
                cursor.execute(
                    f"""
                    UPDATE totvs_outbox
                    SET status = %(status)s,
                        lease_owner = NULL,
                        lease_expires_at = NULL,
                        next_attempt_at = %(proximo)s,
                        last_error_code = 'lease_expirado',
                        last_error_message = %(nota)s,
                        last_delivery_class = 'transient',
                        updated_at = %(now)s
                    WHERE id = %(id)s
                    RETURNING {OUTBOX_COLUMNS}
                    """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                    {
                        "id": item["id"],
                        "status": destino.value,
                        "proximo": proximo,
                        "nota": nota,
                        "now": instante,
                    },
                )
                recuperados.append(_outbox_row(cursor.fetchone()))
                cursor.execute(
                    """
                    INSERT INTO totvs_outbox_attempts (
                        outbox_id, attempt_number, started_at, finished_at,
                        outcome, delivery_class, error_code, error_message, worker
                    ) VALUES (%s, %s, %s, %s, 'abandonado', 'transient',
                              'lease_expirado', %s, %s)
                    ON CONFLICT ON CONSTRAINT uq_totvs_outbox_attempt DO NOTHING
                    """,
                    (
                        item["id"],
                        tentativas,
                        item["last_attempt_at"] or instante,
                        instante,
                        nota,
                        item.get("lease_owner"),
                    ),
                )
        return recuperados

    def reservar_lote_outbound_totvs(
        self,
        *,
        worker: str,
        batch_size: int = 10,
        lease_seconds: int = 120,
        now=None,
    ):
        """Reserva um lote elegível com ``FOR UPDATE SKIP LOCKED``.

        Dois workers simultâneos nunca reservam a mesma linha: quem não
        conseguir o lock a pula, em vez de esperar. A transação é curta e
        fecha antes de qualquer chamada HTTP — a proteção durante o envio é o
        estado ``SENDING`` mais o lease, não um lock de banco aberto.
        """

        instante = (now or self._now()).replace(microsecond=0)
        expira = (instante + timedelta(seconds=int(lease_seconds))).replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                WITH elegiveis AS (
                    SELECT id FROM totvs_outbox
                    WHERE status IN ('PENDING', 'RETRY')
                      AND next_attempt_at <= %(now)s
                      AND payload_xml IS NOT NULL
                    ORDER BY next_attempt_at, id
                    LIMIT %(batch)s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE totvs_outbox o
                SET status = 'SENDING',
                    attempts = o.attempts + 1,
                    last_attempt_at = %(now)s,
                    lease_owner = %(worker)s,
                    lease_expires_at = %(expira)s,
                    updated_at = %(now)s
                FROM elegiveis e
                WHERE o.id = e.id
                RETURNING {OUTBOX_COLUMNS_ALIASED}
                """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                {
                    "now": instante,
                    "batch": max(1, int(batch_size)),
                    "worker": str(worker),
                    "expira": expira,
                },
            )
            return [_outbox_row(row) for row in cursor.fetchall()]

    def concluir_item_outbound_totvs(
        self,
        outbox_id: int,
        *,
        status,
        attempt_number: int,
        started_at,
        delivery_class: str | None = None,
        http_status: int | None = None,
        ack_status: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        internal_id: str | None = None,
        worker: str | None = None,
        now=None,
    ):
        """Persiste o resultado da tentativa e libera a reserva.

        ``next_attempt_at`` recebe o backoff crescente quando o item volta para
        ``RETRY``. ``idempotency_key`` e ``payload_xml`` nunca são tocados: a
        mensagem lógica continua a mesma.

        Só conclui enquanto a reserva ainda é deste worker (``SENDING`` com o
        mesmo ``lease_owner``). Se o lease expirou e o item já foi recuperado
        ou re-reservado por outro worker, devolve ``None`` sem gravar nada: o
        dono atual da reserva decide o desfecho e a entrega continua *at least
        once* com a mesma ``idempotency_key``.
        """

        instante = (now or self._now()).replace(microsecond=0)
        final = _status_value(status)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT attempts FROM totvs_outbox
                WHERE id = %(id)s
                  AND status = 'SENDING'
                  AND (%(worker)s::text IS NULL OR lease_owner = %(worker)s::text)
                FOR UPDATE
                """,
                {"id": int(outbox_id), "worker": worker},
            )
            current = cursor.fetchone()
            if current is None:
                logger.warning(
                    "Conclusão do item %s da outbox TOTVS descartada: a reserva "
                    "não pertence mais ao worker %s (lease expirado ou item "
                    "re-reservado).",
                    outbox_id,
                    worker,
                )
                return None
            tentativas = int(current["attempts"] or 0)
            proximo = (
                next_attempt_at(instante, tentativas)
                if final == OutboxStatus.RETRY.value
                else None
            )
            cursor.execute(
                f"""
                UPDATE totvs_outbox
                SET status = %(status)s,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    next_attempt_at = COALESCE(%(proximo)s, next_attempt_at),
                    sent_at = CASE WHEN %(status)s = 'SENT' THEN %(now)s ELSE sent_at END,
                    last_http_status = %(http_status)s,
                    last_ack_status = %(ack_status)s,
                    last_delivery_class = %(delivery_class)s,
                    last_error_code = %(error_code)s,
                    last_error_message = %(error_message)s,
                    internal_id = COALESCE(%(internal_id)s, internal_id),
                    updated_at = %(now)s
                WHERE id = %(id)s
                RETURNING {OUTBOX_COLUMNS}
                """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                {
                    "id": int(outbox_id),
                    "status": final,
                    "proximo": proximo,
                    "now": instante,
                    "http_status": http_status,
                    "ack_status": ack_status,
                    "delivery_class": delivery_class,
                    "error_code": error_code,
                    "error_message": _truncate(error_message),
                    "internal_id": internal_id,
                },
            )
            item = _outbox_row(cursor.fetchone())
            cursor.execute(
                """
                INSERT INTO totvs_outbox_attempts (
                    outbox_id, attempt_number, started_at, finished_at, outcome,
                    delivery_class, http_status, ack_status, error_code,
                    error_message, internal_id, worker
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT uq_totvs_outbox_attempt DO UPDATE SET
                    finished_at = EXCLUDED.finished_at,
                    outcome = EXCLUDED.outcome,
                    delivery_class = EXCLUDED.delivery_class,
                    http_status = EXCLUDED.http_status,
                    ack_status = EXCLUDED.ack_status,
                    error_code = EXCLUDED.error_code,
                    error_message = EXCLUDED.error_message,
                    internal_id = EXCLUDED.internal_id
                """,
                (
                    int(outbox_id),
                    max(1, int(attempt_number)),
                    started_at or instante,
                    instante,
                    final,
                    delivery_class,
                    http_status,
                    ack_status,
                    error_code,
                    _truncate(error_message),
                    internal_id,
                    worker,
                ),
            )
            return item

    def reprocessar_item_outbound_totvs(self, outbox_id: int, *, now=None, operador=None):
        """Move um item ``ERROR`` de volta para ``PENDING``.

        Mantém a mesma mensagem lógica: mesma ``idempotency_key``, mesmo
        ``payload_xml`` e todo o histórico de tentativas. Nada do payload é
        editado silenciosamente. Um item bloqueado (sem payload) permanece
        ``ERROR`` — ele precisa ser remontado a partir do fato canônico
        original, o que é responsabilidade do serviço de reprocessamento.
        """

        instante = (now or self._now()).replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE totvs_outbox
                SET status = 'PENDING',
                    next_attempt_at = %(now)s,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = NULL,
                    last_error_message = %(nota)s,
                    updated_at = %(now)s
                WHERE id = %(id)s AND status = 'ERROR' AND payload_xml IS NOT NULL
                RETURNING {OUTBOX_COLUMNS}
                """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                {
                    "id": int(outbox_id),
                    "now": instante,
                    "nota": _truncate(
                        f"Reprocessamento manual solicitado por {operador or 'ADMIN'}."
                    ),
                },
            )
            return _outbox_row(cursor.fetchone())

    def preencher_payload_outbound_totvs(
        self,
        outbox_id: int,
        *,
        payload_xml: str,
        idempotency_key: str,
        payload_context=None,
        now=None,
    ):
        """Completa um item que nasceu bloqueado, sem payload.

        Só se aplica a itens ``ERROR`` cujo ``payload_xml`` é nulo — aqueles
        que não puderam ser montados por falta de parâmetro homologado. O fato
        canônico é imutável; o que mudou foi a configuração. A chave lógica é
        substituída pela chave determinística real do contrato, mantendo uma
        única identidade por mensagem.
        """

        instante = (now or self._now()).replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE totvs_outbox
                SET payload_xml = %(payload)s,
                    idempotency_key = %(key)s,
                    payload_context = COALESCE(%(context)s, payload_context),
                    status = 'PENDING',
                    next_attempt_at = %(now)s,
                    lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = NULL,
                    last_error_message = NULL,
                    updated_at = %(now)s
                WHERE id = %(id)s AND status = 'ERROR' AND payload_xml IS NULL
                RETURNING {OUTBOX_COLUMNS}
                """,  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo, valores via %s
                {
                    "id": int(outbox_id),
                    "payload": str(payload_xml),
                    "key": str(idempotency_key),
                    "context": Jsonb(dict(payload_context)) if payload_context else None,
                    "now": instante,
                },
            )
            return _outbox_row(cursor.fetchone())

    # ------------------------------------------------------------------
    # Consulta e observabilidade
    # ------------------------------------------------------------------
    def buscar_item_outbound_totvs(self, outbox_id: int):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {OUTBOX_COLUMNS} FROM totvs_outbox WHERE id = %s",  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo
                (int(outbox_id),),
            )
            return _outbox_row(cursor.fetchone())

    def buscar_item_outbound_totvs_por_chave(self, idempotency_key: str, *, cursor=None):
        """Localiza a mensagem lógica pela chave determinística.

        Aceita o cursor da transação em curso porque o enqueue precisa
        confirmar, ainda dentro dela, que um ``ON CONFLICT DO NOTHING``
        realmente encontrou a obrigação já registrada — e não silenciou a
        ausência dela.
        """

        query = f"SELECT {OUTBOX_COLUMNS} FROM totvs_outbox WHERE idempotency_key = %s"  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo
        if cursor is not None:
            cursor.execute(query, (str(idempotency_key),))
            return _outbox_row(cursor.fetchone())
        with self.connection() as connection, connection.cursor() as own:
            own.execute(query, (str(idempotency_key),))
            return _outbox_row(own.fetchone())

    def listar_itens_outbound_totvs(
        self, *, status=None, production_order=None, limit: int = 100
    ):
        query = f"SELECT {OUTBOX_COLUMNS} FROM totvs_outbox WHERE TRUE"  # nosec B608 -- OUTBOX_COLUMNS é constante do módulo
        params: list = []
        if status:
            values = [status] if isinstance(status, (str, OutboxStatus)) else list(status)
            query += " AND status = ANY(%s)"
            params.append([_status_value(item) for item in values])
        if production_order:
            query += " AND UPPER(production_order) = UPPER(%s)"
            params.append(str(production_order).strip())
        query += " ORDER BY id DESC LIMIT %s"
        params.append(max(1, int(limit)))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [_outbox_row(row) for row in cursor.fetchall()]

    def listar_tentativas_outbound_totvs(self, outbox_id: int):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM totvs_outbox_attempts
                WHERE outbox_id = %s ORDER BY attempt_number
                """,
                (int(outbox_id),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def metricas_outbound_totvs(self, *, now=None):
        """Observabilidade mínima da fila, sem dashboard."""

        instante = (now or self._now()).replace(microsecond=0)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, COUNT(*) AS total, MAX(attempts) AS max_attempts
                FROM totvs_outbox GROUP BY status
                """
            )
            por_status = {
                str(row["status"]): {
                    "total": int(row["total"]),
                    "max_attempts": int(row["max_attempts"] or 0),
                }
                for row in cursor.fetchall()
            }
            cursor.execute(
                """
                SELECT id, created_at, next_attempt_at, event_type, production_order,
                       EXTRACT(EPOCH FROM (%s - created_at))::BIGINT AS idade_segundos
                FROM totvs_outbox
                WHERE status IN ('PENDING', 'RETRY', 'SENDING')
                ORDER BY created_at, id
                LIMIT 1
                """,
                (instante,),
            )
            mais_antigo = _outbox_row(cursor.fetchone())
            cursor.execute(
                """
                SELECT id, production_order, event_type, last_error_code,
                       last_error_message, last_delivery_class, updated_at
                FROM totvs_outbox
                WHERE last_error_code IS NOT NULL
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            )
            ultima_falha = _outbox_row(cursor.fetchone())
            cursor.execute(
                """
                SELECT id, production_order, event_type, internal_id, sent_at
                FROM totvs_outbox
                WHERE status = 'SENT'
                ORDER BY sent_at DESC, id DESC
                LIMIT 1
                """
            )
            ultima_entrega = _outbox_row(cursor.fetchone())
            cursor.execute("SELECT COUNT(*) AS total FROM totvs_outbox_attempts")
            tentativas = int(cursor.fetchone()["total"])
        contagem = {
            status.value: int(por_status.get(status.value, {}).get("total", 0))
            for status in OutboxStatus
        }
        return {
            "gerado_em": instante,
            "contagem": contagem,
            "pending": contagem[OutboxStatus.PENDING.value],
            "retry": contagem[OutboxStatus.RETRY.value],
            "sending": contagem[OutboxStatus.SENDING.value],
            "sent": contagem[OutboxStatus.SENT.value],
            "error": contagem[OutboxStatus.ERROR.value],
            "tentativas_registradas": tentativas,
            "max_tentativas_em_aberto": max(
                (
                    int(por_status.get(status.value, {}).get("max_attempts", 0))
                    for status in (
                        OutboxStatus.PENDING,
                        OutboxStatus.RETRY,
                        OutboxStatus.SENDING,
                    )
                ),
                default=0,
            ),
            "item_pendente_mais_antigo": mais_antigo,
            "ultima_falha": ultima_falha,
            "ultima_entrega_ok": ultima_entrega,
        }


__all__ = ["TotvsOutboxRepositoryMixin"]
