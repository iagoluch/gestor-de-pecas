"""DEMO explícita: transportes hostis não atravessam a composição local."""

from contextlib import contextmanager, ExitStack
from dataclasses import replace
from datetime import datetime
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from backend.api.config import ANDON_DEMO_DATABASE, WebSettings
from backend.api.main import _default_database_factory, create_app
from mes.integrations.notifications.telegram import telegram_outbound_allowed
from mes.integrations.totvs.on_demand_gateway import build_order_provisioning_service
from mes.services.telegram_cut import build_cut_plan_notifier
from tests.test_web_api import ApiFakeDatabase


DEMO_ENV = {
    "GESTOR_ANDON_DEMO_MODE": "1",
    "GESTOR_WEB_ENV": "development",
    "GESTOR_SIMULATION_MODE": "1",
    "GESTOR_SIMULATION_NOW": "2026-10-06T08:00:00",
    "GESTOR_EXPECTED_DATABASE": ANDON_DEMO_DATABASE,
    "TEST_DATABASE_URL": f"postgresql://demo@127.0.0.1:1/{ANDON_DEMO_DATABASE}",
    "DATABASE_URL": "",
    # Sentinelas não são credenciais; qualquer construção de transporte falha.
    "GESTOR_TOTVS_OP_PULL_ENDPOINT": "https://external.invalid/orders",
    "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://external.invalid/models",
    "GESTOR_TOTVS_OUTBOUND_ENDPOINT": "https://external.invalid/outbound",
    "GESTOR_TOTVS_OUTBOX_ENABLED": "1",
    "SIGMANEST_ODBC_DSN": "external-sentinel",
}


def hostile_settings():
    return WebSettings(
        environment="development", session_secret="demo-isolation-test-secret-32-bytes-long",
        serve_static=False, allowed_hosts=("testserver",),
        andon_demo_mode=True, simulation_mode=True,
        simulation_reference_time=datetime(2026, 10, 6, 8),
        ai_enabled=True, ai_api_key="sentinel",
        telegram_enabled=True, telegram_bot_token="sentinel",
        telegram_bot_polling_enabled=True, telegram_digest_enabled=True,
        telegram_factory_chat_id="sentinel", telegram_sector_chat_ids={"Corte": "sentinel"},
        totvs_enabled=True, totvs_soap_enabled=True, totvs_outbox_worker_enabled=True,
        totvs_op_pull_enabled=True, sigmanest_sync_enabled=True,
        report_automation_enabled=True, dev_observatory_enabled=True,
        dev_observatory_real_dsn="postgresql://sentinel@external.invalid/real",
    )


class DemoDatabase(ApiFakeDatabase):
    def __init__(self, actual_name=ANDON_DEMO_DATABASE):
        super().__init__()
        self.safe_target = {"dbname": ANDON_DEMO_DATABASE}
        self.actual_name = actual_name
        self.commands = []

    @contextmanager
    def connection(self):
        database = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query, _params=None):
                database.commands.append(query)

            def fetchone(self):
                return {"dbname": database.actual_name, "ok": 1}

        yield SimpleNamespace(cursor=Cursor)


class AndonDemoIsolationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, DEMO_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_profile_normalizes_injected_and_environment_settings(self):
        normalized = hostile_settings().isolated_andon_demo()
        flags = (
            "ai_enabled", "telegram_enabled", "telegram_bot_polling_enabled",
            "telegram_digest_enabled", "totvs_enabled", "totvs_soap_enabled",
            "totvs_outbox_worker_enabled", "totvs_op_pull_enabled",
            "sigmanest_sync_enabled", "report_automation_enabled", "dev_observatory_enabled",
        )
        for field in flags:
            self.assertFalse(getattr(normalized, field), field)
        self.assertEqual(normalized.ai_api_key, "")
        self.assertEqual(normalized.telegram_bot_token, "")
        self.assertEqual(normalized.dev_observatory_real_dsn, "")
        self.assertNotEqual(normalized.session_cookie_name, "gestor_session")
        self.assertNotEqual(normalized.csrf_cookie_name, "gestor_csrf")
        loaded = WebSettings.from_env({**DEMO_ENV, "GESTOR_TOTVS_SOAP_ENABLED": "1", "GESTOR_TOTVS_ENABLED": "1"})
        self.assertTrue(loaded.andon_demo_mode)
        self.assertFalse(loaded.totvs_soap_enabled)

    def test_generic_simulation_profile_is_unchanged(self):
        regular = replace(hostile_settings(), andon_demo_mode=False)
        self.assertIs(regular.isolated_andon_demo(), regular)
        self.assertTrue(telegram_outbound_allowed(regular))

    def test_shift_scheduler_still_starts_outside_explicit_demo(self):
        for simulation_mode in (False, True):
            with self.subTest(simulation_mode=simulation_mode):
                settings = WebSettings(
                    environment="development", session_secret="scheduler-test-secret-32-bytes-long",
                    serve_static=False, dev_observatory_enabled=False,
                    simulation_mode=simulation_mode,
                    simulation_reference_time=datetime(2026, 10, 6, 8) if simulation_mode else None,
                )
                with patch("backend.api.main._shift_boundary_loop", new_callable=AsyncMock) as shift:
                    app = create_app(settings=settings, database_factory=DemoDatabase)
                    with TestClient(app):
                        shift.assert_called_once_with(app)

    def test_invalid_profile_or_dsn_fails_before_database_factory(self):
        factory = Mock(side_effect=AssertionError("database must not open"))
        for settings in (
            replace(hostile_settings(), environment="production"),
            replace(hostile_settings(), simulation_mode=False),
            replace(hostile_settings(), simulation_reference_time=None),
        ):
            with self.subTest(settings=settings.environment), self.assertRaises(RuntimeError):
                create_app(settings=settings, database_factory=factory)
        for variable, value in (
            ("GESTOR_EXPECTED_DATABASE", "gestor_pecas_test"),
            ("TEST_DATABASE_URL", "postgresql://demo@127.0.0.1:1/gestor_pecas"),
        ):
            with patch.dict(os.environ, {variable: value}), self.assertRaises(RuntimeError):
                create_app(settings=hostile_settings(), database_factory=factory)
        factory.assert_not_called()

    def test_actual_database_identity_fails_closed_at_startup(self):
        database = DemoDatabase(actual_name="gestor_pecas")
        app = create_app(settings=hostile_settings(), database_factory=lambda: database)
        with self.assertRaises(RuntimeError), TestClient(app):
            pass
        self.assertEqual(database.commands, ["SELECT current_database() AS dbname"])

    def test_default_factory_checks_server_before_migrations_and_disables_enqueue(self):
        for actual, accepted in ((ANDON_DEMO_DATABASE, True), ("gestor_pecas", False)):
            with self.subTest(actual=actual):
                database = DemoDatabase(actual_name=actual)
                with patch("app.database.Database", return_value=database) as constructor, patch(
                    "app.database.migrations.apply_migrations"
                ) as migrations:
                    if accepted:
                        _default_database_factory(andon_demo_mode=True)
                        migrations.assert_called_once()
                    else:
                        with self.assertRaises(RuntimeError):
                            _default_database_factory(andon_demo_mode=True)
                        migrations.assert_not_called()
                    self.assertFalse(constructor.call_args.kwargs["auto_migrate"])
                    self.assertFalse(constructor.call_args.kwargs["totvs_outbox_config"].enabled)
                    self.assertIn("SELECT current_database() AS dbname", database.commands)

    def test_order_pull_ignores_hostile_env_and_injected_gateways(self):
        database = DemoDatabase()
        with patch(
            "mes.integrations.totvs.on_demand_gateway.ProtheusOnDemandRequestGateway.from_env",
            side_effect=AssertionError("remote order gateway"),
        ):
            service = build_order_provisioning_service(
                database, hostile_settings(), gateway=Mock(), ingestion_service=Mock(),
            )
            self.assertFalse(service.available)
            self.assertFalse(service.provision("ABSENT-DEMO").requested)
        self.assertFalse(telegram_outbound_allowed(hostile_settings()))
        self.assertIsNone(build_cut_plan_notifier(database, hostile_settings()))

    def test_http_and_lifespan_never_construct_external_transports(self):
        database = DemoDatabase()
        database.criar_usuario("Demo Manager", "test-password", "gestor")
        database.criar_usuario("Demo Cut", "test-password", "operador_corte")
        database.criar_usuario("Demo Operator", "test-password", "operador_dobra")
        database.registrar_chamada = Mock(return_value={"id": 1, "contato_telegram_chat_id": "sentinel"})
        database.marcar_chamada_telegram = Mock(return_value=None)
        external = (
            "OpenAICompatibleProvider", "SigmaNestSqlServerGateway", "TelegramProvider", "ReadOnlyDatabaseManager",
            "_totvs_outbox_worker_loop", "_sigmanest_sync_loop", "_report_scheduler_loop",
            "_telegram_bot_loop", "_telegram_digest_loop", "_internal_alert_dispatch_loop",
            "_dev_observatory_loop",
            "_shift_boundary_loop",
        )
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(
                f"backend.api.main.{name}", side_effect=AssertionError(f"external: {name}")
            )) for name in external]
            stack.enter_context(patch(
                "backend.api.dependencies.messaging.TelegramProvider", side_effect=AssertionError("telegram")
            ))
            deliver_chamada = stack.enter_context(patch(
                "backend.api.routers.chamadas.deliver_chamada", side_effect=AssertionError("telegram call")
            ))
            stack.enter_context(patch(
                "mes.integrations.totvs.on_demand_gateway.ProtheusOnDemandRequestGateway.from_env",
                side_effect=AssertionError("order pull"),
            ))
            app = create_app(settings=hostile_settings(), database_factory=lambda: database)
            with TestClient(app) as client:
                self.assertIsNone(app.state.sigmanest_refresh)
                self.assertIsNone(app.state.sigmanest_gateway_factory)
                self.assertIsNone(app.state.totvs_service_factory)
                self.assertIsNone(app.state.ai_provider)
                self.assertIsNone(app.state.dev_observatory_real)
                self.assertEqual(client.get("/PcfIntegService").status_code, 503)
                self.assertEqual(client.post("/PcfIntegService", content=b"hostile").status_code, 503)
                self.assertEqual(client.get("/api/v1/dev-observatory/health").status_code, 404)
                for username, action, payload, expected in (
                    ("Demo Cut", "/api/v1/cutting/sync?resource=Laser%20Ensis%203015", None, 503),
                    ("Demo Operator", "/api/v1/operator/operations/ABSENT-DEMO/sync", None, 503),
                    ("Demo Manager", "/api/v1/reports/artifacts/00000000-0000-0000-0000-000000000001/send", {"destination_id": 1}, 409),
                    ("Demo Manager", "/api/v1/ai/conversations/1/messages", {"content": "demo"}, 503),
                ):
                    login = client.post("/api/v1/auth/login", json={"username": username, "password": "test-password"})
                    self.assertEqual(login.status_code, 200, login.text)
                    csrf = client.cookies.get("gestor_andon_demo_csrf")
                    self.assertTrue(csrf)
                    response = client.post(action, json=payload, headers={"X-CSRF-Token": csrf})
                    self.assertEqual(response.status_code, expected, response.text)
                chamada = client.post("/api/v1/chamadas", json={
                    "contato_id": 1, "motivo": "Manutenção", "comentario": "DEMO local",
                    "solicitante_nome_manual": "Demo", "solicitante_email": "demo@example.invalid",
                }, headers={"X-CSRF-Token": csrf})
                self.assertEqual(chamada.status_code, 200, chamada.text)
                self.assertFalse(chamada.json()["telegram_agendado"])
                deliver_chamada.assert_not_called()
            for external_mock in mocks:
                external_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
