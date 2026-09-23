import tempfile
import unittest
from datetime import datetime, time, timezone
from pathlib import Path

from backend.api.report_workbook import build_report_workbook
from mes.contracts import MessagingError, ReportRequest
from mes.services.industrial_reports import IndustrialReportService
from mes.services.report_messaging import ReportMessagingService
from mes.services.report_scheduler import ReportScheduler, closed_report_period
from tests.fakes import FakeDatabase
from tests.test_intelligence_reports import CanonicalReportFacade


NOW = datetime(2026, 8, 26, 10, 30)


class FakeMessagingProvider:
    def __init__(self, failures=0):
        self.failures = failures
        self.calls = []

    async def send_document(self, **values):
        self.calls.append(values)
        if len(self.calls) <= self.failures:
            raise MessagingError(
                "telegram_timeout",
                "Tempo esgotado.",
                status_code=504,
                retryable=True,
            )
        return {"message_id": len(self.calls), "provider": "telegram"}


class ReportAutomationMessagingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = FakeDatabase()
        self.report_service = IndustrialReportService(
            CanonicalReportFacade(),
            self.database,
            artifact_dir=self.temp.name,
            workbook_builder=build_report_workbook,
            now_func=lambda: NOW,
        )
        self.database.messaging_destinations.append({
            "id": 1,
            "user_id": 7,
            "provider": "telegram",
            "label": "Gestão",
            "destination_ref": "-1000000000000",
            "enabled": True,
            "created_at": NOW,
        })

    def tearDown(self):
        self.temp.cleanup()

    def add_schedule(self, frequency="diario", destination_id=None):
        return self.database.criar_agendamento_relatorio(
            created_by=7,
            name="Relatório fechado",
            report_type="paradas",
            frequency=frequency,
            filters={"setor": "Usinagem"},
            run_time=time(6, 0),
            timezone="America/Sao_Paulo",
            enabled=True,
            destination_id=destination_id,
            created_at=NOW,
        )

    def test_periodos_automaticos_usam_somente_janelas_fechadas(self):
        local = datetime(2026, 8, 26, 9, 0)
        self.assertEqual(
            closed_report_period("diario", local),
            (datetime(2026, 8, 25), datetime(2026, 8, 26)),
        )
        self.assertEqual(
            closed_report_period("semanal", local),
            (datetime(2026, 8, 17), datetime(2026, 8, 24)),
        )
        self.assertEqual(
            closed_report_period("mensal", local),
            (datetime(2026, 7, 1), datetime(2026, 8, 1)),
        )
        self.assertEqual(
            closed_report_period("quinzenal", local),
            (datetime(2026, 8, 1), datetime(2026, 8, 16)),
        )

    async def test_restart_e_multiplos_ciclos_nao_duplicam_arquivo_nem_envio(self):
        self.add_schedule(destination_id=1)
        provider = FakeMessagingProvider()
        messaging = ReportMessagingService(
            self.database,
            self.report_service,
            provider=provider,
            enabled=True,
            configured=True,
            now_func=lambda: NOW,
        )
        first_runner = ReportScheduler(
            self.database, self.report_service, messaging_service=messaging
        )
        second_runner = ReportScheduler(
            self.database, self.report_service, messaging_service=messaging
        )
        instant = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        first = await first_runner.run_due(instant)
        second = await second_runner.run_due(instant)
        self.assertEqual(first[0]["status"], "gerado")
        self.assertEqual(second[0]["artifact"]["id"], first[0]["artifact"]["id"])
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(Path(provider.calls[0]["path"]).is_file())

    async def test_falha_de_envio_preserva_artifact_e_retry_reaproveita_o_mesmo(self):
        self.add_schedule(destination_id=1)
        provider = FakeMessagingProvider(failures=1)
        messaging = ReportMessagingService(
            self.database,
            self.report_service,
            provider=provider,
            enabled=True,
            configured=True,
            now_func=lambda: NOW,
        )
        scheduler = ReportScheduler(
            self.database, self.report_service, messaging_service=messaging
        )
        instant = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        failed = await scheduler.run_due(instant)
        self.assertEqual(failed[0]["status"], "falhou")
        self.assertEqual(len(self.database.generated_reports), 1)
        report_id = self.database.generated_reports[0]["id"]
        self.assertTrue(self.report_service.get(report_id, user_id=7)[1].is_file())
        succeeded = await scheduler.run_due(instant)
        self.assertEqual(succeeded[0]["delivery"]["status"], "enviado")
        self.assertEqual(len(self.database.generated_reports), 1)
        self.assertEqual(self.database.report_deliveries[0]["attempt"], 2)

    async def test_envio_desativado_nao_chama_provider(self):
        artifact = self.report_service.generate(
            ReportRequest("ops", datetime(2026, 8, 25), datetime(2026, 8, 26)),
            created_by=7,
            source="manual",
        )
        provider = FakeMessagingProvider()
        messaging = ReportMessagingService(
            self.database,
            self.report_service,
            provider=provider,
            enabled=False,
            configured=False,
        )
        with self.assertRaisesRegex(MessagingError, "desativado"):
            await messaging.send_report(
                artifact["id"], user_id=7, destination_id=1
            )
        self.assertEqual(provider.calls, [])

    async def test_destino_de_outro_usuario_e_ocultado(self):
        artifact = self.report_service.generate(
            ReportRequest("ops", datetime(2026, 8, 25), datetime(2026, 8, 26)),
            created_by=7,
            source="manual",
        )
        messaging = ReportMessagingService(
            self.database,
            self.report_service,
            provider=FakeMessagingProvider(),
            enabled=True,
            configured=True,
        )
        with self.assertRaisesRegex(MessagingError, "Destino não encontrado"):
            await messaging.send_report(
                artifact["id"], user_id=7, destination_id=999
            )

    async def test_cada_frequencia_gera_exatamente_um_artifact_e_o_ciclo_repetido_nao_duplica(self):
        """Item 10: diario, semanal e mensal produzem um artifact cada; repetir o
        ciclo e reiniciar o processo nao geram artifact nem envio adicional."""

        for frequencia in ("diario", "semanal", "mensal"):
            with self.subTest(frequencia=frequencia):
                self.database.generated_reports.clear()
                self.database.report_deliveries.clear()
                self.database.report_schedules.clear()
                self.add_schedule(frequency=frequencia, destination_id=1)

                provider = FakeMessagingProvider()
                messaging = ReportMessagingService(
                    self.database,
                    self.report_service,
                    provider=provider,
                    enabled=True,
                    configured=True,
                    now_func=lambda: NOW,
                )
                instante = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

                primeiro = await ReportScheduler(
                    self.database, self.report_service, messaging_service=messaging
                ).run_due(instante)
                self.assertEqual(len(primeiro), 1)
                self.assertEqual(primeiro[0]["status"], "gerado")
                self.assertEqual(len(self.database.generated_reports), 1)
                self.assertEqual(len(provider.calls), 1)
                artifact_id = primeiro[0]["artifact"]["id"]

                # Mesmo ciclo executado de novo.
                repetido = await ReportScheduler(
                    self.database, self.report_service, messaging_service=messaging
                ).run_due(instante)
                self.assertEqual(repetido[0]["artifact"]["id"], artifact_id)
                self.assertEqual(len(self.database.generated_reports), 1)
                self.assertEqual(len(provider.calls), 1)

                # Reinicio do processo: nova instancia, nenhum reenvio apos sucesso.
                apos_reinicio = await ReportScheduler(
                    self.database, self.report_service, messaging_service=messaging
                ).run_due(instante)
                self.assertEqual(apos_reinicio[0]["artifact"]["id"], artifact_id)
                self.assertEqual(len(self.database.generated_reports), 1)
                self.assertEqual(len(provider.calls), 1)
                entregas = [d for d in self.database.report_deliveries if d["status"] == "enviado"]
                self.assertEqual(len(entregas), 1)
                self.assertEqual(entregas[0]["attempt"], 1)

    def test_automacao_permanece_desabilitada_por_padrao(self):
        """Item 10: apos os testes a automacao continua desligada no default."""

        from backend.api.config import WebSettings

        padrao = WebSettings.from_env({
            "GESTOR_WEB_SESSION_SECRET": "segredo-de-teste-com-tamanho-suficiente-para-assinar-1234",
        })
        self.assertFalse(padrao.report_automation_enabled)
        self.assertFalse(padrao.telegram_enabled)
        self.assertFalse(padrao.ai_enabled)


if __name__ == "__main__":
    unittest.main()
