"""Auditoria 14/10/2026, parte B: tetos de stream, filtro de segredos,
lista permitida do Dev Observatory, freio do botão de chamada, XLSX e OpenAPI."""

from __future__ import annotations

import asyncio
import gc
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openpyxl import Workbook

from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.errors import AppError
from backend.api.main import create_app
from backend.api.rate_limit import SlidingWindowLimiter, StreamSlots, hold_while_streaming
from backend.api.realtime import RealtimeBroker
from backend.api.report_workbook.kit import Card, Column, ReportSheet
from backend.api.routers import dev_observatory as dev_observatory_router
from backend.api.schemas.auth import SessionUser
from backend.observability.classification import sanitize
from backend.observability.quick_fixes import event_context, scrub
from tests.test_dev_observatory import ApiFakeDatabase


SECRET = "test-secret-that-is-long-enough-for-session-signatures-123456"


def _settings(**overrides):
    base = dict(
        environment="test",
        session_secret=SECRET,
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
        serve_static=False,
    )
    base.update(overrides)
    return WebSettings(**base)


def _gestor():
    return SessionUser(
        id=7, name="Gestor", role="gestor",
        management_access=True, andon_access=True, operator_access=False,
    )


class _Facade:
    def consulta_operacional(self, *_args, **_kwargs):
        return {"resources": []}


# --------------------------------------------------------------------------
# Mecanismo comum dos tetos
# --------------------------------------------------------------------------
class RateLimitPrimitivesTests(unittest.TestCase):
    def test_slots_respeitam_teto_por_usuario_e_global(self):
        slots = StreamSlots(total=3, per_user=2)
        a1, a2 = slots.try_acquire(1), slots.try_acquire(1)
        self.assertIsNone(slots.try_acquire(1))
        b1 = slots.try_acquire(2)
        self.assertIsNone(slots.try_acquire(3))
        a1.release()
        a1.release()  # idempotente: não devolve vaga em dobro
        self.assertEqual(slots.in_use, 2)
        self.assertIsNotNone(slots.try_acquire(1))
        for lease in (a2, b1):
            lease.release()

    def test_janela_deslizante_libera_depois_do_minuto(self):
        agora = [0.0]
        limiter = SlidingWindowLimiter(limit=2, window_seconds=60, clock=lambda: agora[0])
        self.assertTrue(limiter.hit("posto"))
        self.assertTrue(limiter.hit("posto"))
        self.assertFalse(limiter.hit("posto"))
        self.assertTrue(limiter.hit("outro"))
        agora[0] = 60.0
        self.assertTrue(limiter.hit("posto"))

    def test_vaga_volta_mesmo_se_o_stream_nunca_comecar(self):
        slots = StreamSlots(total=1)

        async def corpo():
            yield "x"

        stream = hold_while_streaming(slots.try_acquire(), corpo())
        self.assertEqual(slots.in_use, 1)
        del stream
        gc.collect()
        self.assertEqual(slots.in_use, 0)


# --------------------------------------------------------------------------
# SEC-01 — /operations/stream
# --------------------------------------------------------------------------
class OperationsStreamTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            settings=_settings(operations_stream_per_user=1), database_factory=lambda: object()
        )
        self.app.dependency_overrides[get_database] = lambda: object()
        self.app.dependency_overrides[require_management_user] = _gestor
        self.app.dependency_overrides[get_frontend_facade] = _Facade
        self.client = TestClient(self.app)

    def test_sessao_revogada_encerra_o_stream_sem_mandar_dado(self):
        revogada = AppError("session_revoked", "A sessão foi invalidada.", status_code=401)
        with patch("backend.api.routers.operations.get_current_user", side_effect=revogada):
            resposta = self.client.get("/api/v1/operations/stream")
        self.assertEqual(resposta.status_code, 200)
        self.assertIn("session_revoked", resposta.text)
        self.assertNotIn("event: snapshot", resposta.text)
        self.assertEqual(self.app.state.operations_stream_slots.in_use, 0)

    def test_usuario_rebaixado_perde_o_stream(self):
        operador = SessionUser(
            id=7, name="Ex-gestor", role="operador_dobra",
            management_access=False, andon_access=False, operator_access=True,
        )
        with patch("backend.api.routers.operations.get_current_user", return_value=operador):
            resposta = self.client.get("/api/v1/operations/stream")
        self.assertIn("management_access_denied", resposta.text)
        self.assertNotIn("event: snapshot", resposta.text)

    def test_teto_por_usuario_responde_429(self):
        ocupada = self.app.state.operations_stream_slots.try_acquire(7)
        try:
            resposta = self.client.get("/api/v1/operations/stream")
        finally:
            ocupada.release()
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(resposta.json()["code"], "operations_stream_limit_reached")

    def test_padroes_configuraveis_por_ambiente(self):
        settings = WebSettings.from_env({
            "GESTOR_WEB_SESSION_SECRET": SECRET,
            "GESTOR_WEB_OPERATIONS_STREAM_PER_USER": "5",
            "GESTOR_WEB_EVENTS_STREAM_TOTAL": "50",
            "GESTOR_CHAMADA_LIMIT_PER_SESSION_PER_MINUTE": "4",
        })
        self.assertEqual(settings.operations_stream_per_user, 5)
        self.assertEqual(settings.operations_stream_total, 20)
        self.assertEqual(settings.events_stream_total, 50)
        self.assertEqual(settings.chamada_limit_per_session_per_minute, 4)
        self.assertEqual(settings.chamada_limit_per_account_per_minute, 30)


# --------------------------------------------------------------------------
# SEC-09 — /system/events
# --------------------------------------------------------------------------
class StreamCancelTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelamento_sobe_e_a_vaga_volta(self):
        slots = StreamSlots(total=1)

        async def corpo():
            yield "x"
            await asyncio.sleep(3600)
            yield "nunca"

        stream = hold_while_streaming(slots.try_acquire(), corpo())

        async def consumir():
            async for _ in stream:
                pass

        tarefa = asyncio.create_task(consumir())
        await asyncio.sleep(0.01)
        tarefa.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await tarefa
        self.assertEqual(slots.in_use, 0)


class RealtimeLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_teto_global_de_assinantes(self):
        broker = RealtimeBroker(StreamSlots(total=1))
        primeiro = broker.open_stream()
        self.assertIsNotNone(primeiro)
        self.assertIsNone(broker.open_stream())
        await anext(primeiro)
        await primeiro.aclose()
        segundo = broker.open_stream()
        self.assertIsNotNone(segundo)
        await anext(segundo)
        await segundo.aclose()
        await asyncio.sleep(0)


class SystemEventsLimitTests(unittest.TestCase):
    def test_rota_responde_429_quando_cheia(self):
        app = create_app(settings=_settings(events_stream_total=1), database_factory=lambda: object())
        app.dependency_overrides[get_current_user] = _gestor
        ocupada = app.state.realtime._slots.try_acquire()
        try:
            resposta = TestClient(app).get("/api/v1/system/events")
        finally:
            ocupada.release()
        self.assertEqual(resposta.status_code, 429)
        self.assertEqual(resposta.json()["code"], "realtime_limit_reached")


# --------------------------------------------------------------------------
# SEC-02 + B5 — filtro de segredos que vai para a IA
# --------------------------------------------------------------------------
class SecretScrubTests(unittest.TestCase):
    def test_string_de_conexao_pyodbc(self):
        texto = scrub(
            "pyodbc.InterfaceError: ('28000', 'DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=10.0.0.5,1433;DATABASE=SigmaNEST;UID=sigma_ro;PWD={S3nh@;Forte!};"
            "TrustServerCertificate=yes')"
        )
        self.assertNotIn("S3nh@", texto)
        self.assertNotIn("Forte!", texto)
        self.assertNotIn("sigma_ro", texto)
        self.assertIn("DATABASE=SigmaNEST", texto)
        self.assertIn("PWD=<omitido>", texto)
        self.assertNotIn("abc123", scrub("SERVER=srv;UID=leitor;PWD=abc123;DATABASE=x"))

    def test_conninfo_e_url_do_psycopg(self):
        conninfo = scrub("host=localhost port=5432 dbname=gestor_pecas user=gestor password=Sup3rSecret")
        self.assertNotIn("Sup3rSecret", conninfo)
        self.assertIn("dbname=gestor_pecas", conninfo)
        url = scrub("could not connect postgresql://gestor:P@ss:w0rd@db.local:5432/gestor_pecas")
        self.assertNotIn("P@ss", url)
        self.assertNotIn("w0rd", url)
        self.assertIn("postgresql://<omitido>@db.local:5432/gestor_pecas", url)

    def test_chaves_com_prefixo_e_texto_comum_preservado(self):
        texto = scrub("{'db_password': 'xyz'} csrf_token=abc guid=123 OP-1 LASER1")
        self.assertNotIn("xyz", texto)
        self.assertNotIn("abc", texto)
        self.assertIn("guid=123 OP-1 LASER1", texto)

    def test_event_context_aplica_os_dois_filtros(self):
        texto = event_context({
            "error_message": "falha em postgresql://gestor:segredo1@db/x",
            "details": {"database_url": "postgresql://u:segredo2@h/x", "op": "OP-9"},
            "traceback": "psycopg.OperationalError: password=segredo3",
        })
        for segredo in ("segredo1", "segredo2", "segredo3"):
            self.assertNotIn(segredo, texto)
        self.assertIn("OP-9", texto)

    def test_sanitize_por_conteudo_do_nome_sem_esconder_campo_inofensivo(self):
        limpo = sanitize({
            "db_password": "x", "sigmanest_dsn": "d",
            "GESTOR_AI_API_KEY": "k", "refresh_token": "t", "client_secret": "s",
            "access_token": "a", "Authorization": "Bearer z", "cookie": "c",
            "session_version": 3, "recurso": "LASER1", "op": "OP-1", "path": "/api/v1",
            "motivo": "Manutenção", "session": "abc",
            "total_tokens": 812, "max_tokens": 1024, "prompt_tokens": 500,
            "completion_tokens": 312, "callback_url": "https://totvs.local/rest/op",
            "database_url": "postgresql://gestor:Segr3do@db.local:5432/gestor_pecas",
        })
        for chave in ("db_password", "sigmanest_dsn", "GESTOR_AI_API_KEY", "refresh_token",
                      "client_secret", "access_token", "Authorization", "cookie", "session"):
            self.assertEqual(limpo[chave], "<omitido>", chave)
        self.assertEqual(limpo["session_version"], 3)
        self.assertEqual(limpo["recurso"], "LASER1")
        self.assertEqual(limpo["path"], "/api/v1")
        self.assertEqual(limpo["motivo"], "Manutenção")
        # Contagem de tokens da IA é número, não segredo.
        self.assertEqual(
            (limpo["total_tokens"], limpo["max_tokens"], limpo["prompt_tokens"],
             limpo["completion_tokens"]),
            (812, 1024, 500, 312),
        )
        # Endereço fica visível; só a senha embutida nele some.
        self.assertEqual(limpo["callback_url"], "https://totvs.local/rest/op")
        self.assertEqual(limpo["database_url"], "postgresql://<omitido>@db.local:5432/gestor_pecas")


# --------------------------------------------------------------------------
# SEC-03 + A4 — lista permitida de ambientes
# --------------------------------------------------------------------------
class DevelopmentEnvironmentAllowlistTests(unittest.TestCase):
    def test_encerrar_sessao_so_em_test_ou_development(self):
        for nome, esperado in (
            ("test", True), ("development", True),
            ("production", False), ("prod", False), ("real", False),
            ("homologacao", False), ("producao", False), ("qualquer", False),
        ):
            with self.subTest(ambiente=nome):
                settings = _settings(environment=nome)
                self.assertIs(dev_observatory_router._terminate_allowed(settings), esperado)

    def test_documentacao_da_api_some_fora_de_test_e_development(self):
        for nome, esperado in (("test", 200), ("development", 200), ("production", 404), ("prod", 404)):
            with self.subTest(ambiente=nome):
                app = create_app(settings=_settings(environment=nome), database_factory=lambda: object())
                client = TestClient(app)
                self.assertEqual(client.get("/api/openapi.json").status_code, esperado)
                self.assertEqual(client.get("/api/docs").status_code, esperado)


# --------------------------------------------------------------------------
# SEC-10 — caminho da pasta de relatórios
# --------------------------------------------------------------------------
class DevObservatoryReportDirTests(unittest.TestCase):
    def test_status_e_relatorios_mostram_so_o_nome_da_pasta(self):
        with tempfile.TemporaryDirectory() as temp:
            pasta = Path(temp) / "dev_reports"
            pasta.mkdir()
            app = create_app(
                settings=_settings(
                    dev_observatory_enabled=True,
                    dev_observatory_report_dir=str(pasta),
                    dev_observatory_login_username="devobs",
                    dev_observatory_login_password="senha-do-observatorio",
                    dev_observatory_session_secret="devobs-secret-that-is-long-enough-for-signatures-123456",
                ),
                database_factory=ApiFakeDatabase,
            )
            with TestClient(app) as client:
                login = client.post(
                    "/api/v1/dev-observatory/login",
                    json={"username": "devobs", "password": "senha-do-observatorio"},
                )
                self.assertEqual(login.status_code, 200, login.text)
                status = client.get("/api/v1/dev-observatory/status").json()
                relatorios = client.get("/api/v1/dev-observatory/reports").json()
        self.assertEqual(status["report_dir"], "dev_reports")
        self.assertEqual(relatorios["directory"], "dev_reports")


# --------------------------------------------------------------------------
# SEC-08 — textos de moldura da planilha
# --------------------------------------------------------------------------
class WorkbookFramingTextTests(unittest.TestCase):
    def test_moldura_nao_vira_formula(self):
        ws = Workbook().active
        sheet = ReportSheet(ws)
        sheet.header("Relatório", {}, generated_at=datetime(2026, 10, 14, 8, 0), subtitle="=HYPERLINK(1)")
        sheet.kpis([Card(label="Peças", value=1, context="+SUM(A1)")])
        sheet.notice("-cmd|' /C calc'!A0")
        sheet.facts([("@rotulo", "fato")])
        sheet.table([Column("recurso", "Recurso"), Column("qtd", "Qtd", kind="int")],
                    [{"recurso": "LASER1", "qtd": 2}], totals={"recurso": "=1+1", "qtd": 2})
        textos = [cell.value for row in ws.iter_rows() for cell in row if isinstance(cell.value, str)]
        perigosos = [t for t in textos if t.startswith(("=", "+", "-", "@"))]
        self.assertEqual(perigosos, [])
        self.assertIn("'=HYPERLINK(1)", textos)
        self.assertIn("'=1+1", textos)


if __name__ == "__main__":
    unittest.main()
