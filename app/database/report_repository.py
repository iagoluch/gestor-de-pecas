"""Persistência técnica de artifacts, automações e entregas de relatórios."""

from __future__ import annotations

from psycopg.types.json import Jsonb


class ReportRepositoryMixin:
    def registrar_relatorio_gerado(self, **values):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO generated_reports (
                    id, created_by, report_type, period_start, period_end, filters,
                    filename, storage_path, status, source, size_bytes,
                    worksheet_count, row_count, generation_ms, created_at,
                    expires_at, idempotency_key, generation_metadata
                ) VALUES (
                    %(id)s, %(created_by)s, %(report_type)s, %(period_start)s,
                    %(period_end)s, %(filters)s, %(filename)s, %(storage_path)s,
                    %(status)s, %(source)s, %(size_bytes)s, %(worksheet_count)s,
                    %(row_count)s, %(generation_ms)s, %(created_at)s,
                    %(expires_at)s, %(idempotency_key)s, %(generation_metadata)s
                )
                RETURNING *
                """,
                {
                    "id": values["report_id"],
                    **{key: values.get(key) for key in (
                        "created_by", "report_type", "period_start", "period_end",
                        "filename", "storage_path", "status", "source", "size_bytes",
                        "worksheet_count", "row_count", "generation_ms", "created_at",
                        "expires_at", "idempotency_key",
                    )},
                    "filters": Jsonb(dict(values.get("filters") or {})),
                    "generation_metadata": Jsonb(dict(values.get("generation_metadata") or {})),
                },
            )
            return dict(cursor.fetchone())

    def reservar_relatorio_gerado(self, **values):
        """Reserva a chave de idempotência antes de gerar o arquivo.

        A corrida é resolvida pelo próprio PostgreSQL: a constraint
        ``uq_generated_reports_idempotency`` garante que apenas uma sessão sai
        daqui com a reserva. Quem perde recebe ``None`` e deve aguardar o
        vencedor em vez de gerar um segundo artifact.

        Uma reserva anterior só é retomada quando o relatório falhou, expirou ou
        já venceu — nunca quando está pronto e válido, e nunca quando outra
        sessão está gerando neste instante.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO generated_reports (
                    id, created_by, report_type, period_start, period_end, filters,
                    filename, storage_path, status, source, created_at, expires_at,
                    idempotency_key, generation_metadata
                ) VALUES (
                    %(id)s, %(created_by)s, %(report_type)s, %(period_start)s,
                    %(period_end)s, %(filters)s, %(filename)s, %(storage_path)s,
                    'gerando', %(source)s, %(created_at)s, %(expires_at)s,
                    %(idempotency_key)s, %(generation_metadata)s
                )
                ON CONFLICT (created_by, idempotency_key) DO UPDATE SET
                    id = EXCLUDED.id,
                    report_type = EXCLUDED.report_type,
                    period_start = EXCLUDED.period_start,
                    period_end = EXCLUDED.period_end,
                    filters = EXCLUDED.filters,
                    filename = EXCLUDED.filename,
                    storage_path = EXCLUDED.storage_path,
                    status = 'gerando',
                    source = EXCLUDED.source,
                    size_bytes = 0,
                    worksheet_count = 0,
                    row_count = 0,
                    generation_ms = 0,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at,
                    generation_metadata = EXCLUDED.generation_metadata
                WHERE generated_reports.status IN ('falhou', 'expirado')
                   OR (
                        generated_reports.expires_at IS NOT NULL
                        AND generated_reports.expires_at <= EXCLUDED.created_at
                      )
                RETURNING *
                """,
                {
                    "id": values["report_id"],
                    **{key: values.get(key) for key in (
                        "created_by", "report_type", "period_start", "period_end",
                        "filename", "storage_path", "source", "created_at",
                        "expires_at", "idempotency_key",
                    )},
                    "filters": Jsonb(dict(values.get("filters") or {})),
                    "generation_metadata": Jsonb(dict(values.get("generation_metadata") or {})),
                },
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def concluir_relatorio_gerado(self, report_id, **values):
        """Fecha a reserva com os números reais do arquivo produzido."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE generated_reports SET
                    status = 'pronto',
                    size_bytes = %(size_bytes)s,
                    worksheet_count = %(worksheet_count)s,
                    row_count = %(row_count)s,
                    generation_ms = %(generation_ms)s,
                    generation_metadata = %(generation_metadata)s
                WHERE id = %(id)s
                RETURNING *
                """,
                {
                    "id": str(report_id),
                    **{key: values.get(key) for key in (
                        "size_bytes", "worksheet_count", "row_count", "generation_ms",
                    )},
                    "generation_metadata": Jsonb(dict(values.get("generation_metadata") or {})),
                },
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def falhar_relatorio_gerado(self, report_id):
        """Marca a reserva como falha, liberando a chave para nova tentativa."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE generated_reports SET status = 'falhou' WHERE id = %s RETURNING *",
                (str(report_id),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def obter_relatorio_gerado(self, report_id, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM generated_reports WHERE id = %s AND created_by = %s",
                (str(report_id), int(user_id)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def obter_relatorio_por_idempotencia(self, user_id, idempotency_key):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM generated_reports
                WHERE created_by = %s AND idempotency_key = %s
                ORDER BY created_at DESC LIMIT 1
                """,
                (int(user_id), str(idempotency_key)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def registrar_download_relatorio(self, report_id, user_id, downloaded_at):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE generated_reports
                SET download_count = download_count + 1, last_downloaded_at = %s
                WHERE id = %s AND created_by = %s
                RETURNING *
                """,
                (downloaded_at, str(report_id), int(user_id)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def criar_agendamento_relatorio(self, **values):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO report_schedules (
                    created_by, name, report_type, frequency, filters, run_time,
                    timezone, enabled, destination_id, created_at, updated_at
                ) VALUES (
                    %(created_by)s, %(name)s, %(report_type)s, %(frequency)s,
                    %(filters)s, %(run_time)s, %(timezone)s, %(enabled)s,
                    %(destination_id)s, %(created_at)s, %(created_at)s
                ) RETURNING *
                """,
                {
                    **values,
                    "filters": Jsonb(dict(values.get("filters") or {})),
                },
            )
            return dict(cursor.fetchone())

    def listar_agendamentos_relatorio(self, user_id=None, *, enabled_only=False):
        query = "SELECT * FROM report_schedules WHERE TRUE"
        params = []
        if user_id is not None:
            query += " AND created_by = %s"
            params.append(int(user_id))
        if enabled_only:
            query += " AND enabled IS TRUE"
        query += " ORDER BY id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def excluir_agendamento_relatorio(self, schedule_id, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM report_schedules WHERE id = %s AND created_by = %s RETURNING id",
                (int(schedule_id), int(user_id)),
            )
            return cursor.fetchone() is not None

    def listar_destinos_mensagem(self, user_id, *, provider="telegram"):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, provider, label, destination_ref, enabled, created_at
                FROM messaging_destinations
                WHERE user_id = %s AND provider = %s AND enabled IS TRUE
                ORDER BY id
                """,
                (int(user_id), str(provider)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def obter_destino_mensagem(self, destination_id, user_id, *, provider="telegram"):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, provider, label, destination_ref, enabled, created_at
                FROM messaging_destinations
                WHERE id = %s AND user_id = %s AND provider = %s AND enabled IS TRUE
                """,
                (int(destination_id), int(user_id), str(provider)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def registrar_entrega_relatorio(self, **values):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO report_deliveries (
                    report_id, requested_by, destination_id, status, attempt,
                    error_code, requested_at, completed_at, idempotency_key
                ) VALUES (
                    %(report_id)s, %(requested_by)s, %(destination_id)s,
                    %(status)s, %(attempt)s, %(error_code)s, %(requested_at)s,
                    %(completed_at)s, %(idempotency_key)s
                )
                ON CONFLICT (idempotency_key) DO UPDATE
                SET status = EXCLUDED.status,
                    attempt = GREATEST(report_deliveries.attempt, EXCLUDED.attempt),
                    error_code = EXCLUDED.error_code,
                    completed_at = EXCLUDED.completed_at
                RETURNING *
                """,
                values,
            )
            return dict(cursor.fetchone())

    def obter_entrega_relatorio_por_idempotencia(self, idempotency_key):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM report_deliveries WHERE idempotency_key = %s",
                (str(idempotency_key),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


__all__ = ["ReportRepositoryMixin"]
