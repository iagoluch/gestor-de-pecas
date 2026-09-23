"""Contratos do Dev Observatory.

O que precisa ficar provado aqui:

* a ferramenta tem login próprio, independente da tabela `usuarios` e da
  sessão principal do Gestor de Peças — nenhum dos dois afeta o outro;
* o funil de erros existente alimenta a classificação certa: recusa de negócio
  vira ``EXPECTED_BLOCK`` e exceção não tratada vira ``REAL_ERROR`` com stack;
* as janelas de turno vêm do domínio, não de constantes novas;
* o relatório do turno é gravado em disco e é idempotente;
* a conexão de observação do REAL nasce com sessão somente leitura.
"""

from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from app.database.schema import SCHEMA_VERSION
from backend.api.config import WebSettings
from backend.api.main import create_app
from backend.api.routers import dev_observatory as dev_observatory_router
from backend.observability.classification import (
    EXPECTED_BLOCK,
    EXPECTED_VALIDATION,
    OK,
    PERFORMANCE_ERROR,
    REAL_ERROR,
    TECHNICAL_ERROR,
    classify_http,
    sanitize,
)
from backend.observability.readonly_db import READ_ONLY_OPTION, read_only_config
from backend.observability.shift_report import shift_windows_for_date
from mes.domain.manufacturing_rules import OFFICIAL_WORK_WINDOW, OVERTIME_WINDOWS
from tests.fakes import FakeDatabase


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, _query, _params=None):
        return None

    def fetchone(self):
        return {"ok": 1}


class _Connection:
    def cursor(self):
        return _Cursor()


class ApiFakeDatabase(FakeDatabase):
    safe_target = {"dbname": "gestor_pecas_test", "host": "127.0.0.1", "port": "15432"}

    @contextmanager
    def connection(self):
        yield _Connection()


class ClassificationTests(unittest.TestCase):
    def test_recusa_de_negocio_e_bloqueio_esperado(self):
        classification, _ = classify_http(status=409, error_code="operacao_ja_finalizada")
        self.assertEqual(classification, EXPECTED_BLOCK)

    def test_validacao_de_contrato_nao_e_bloqueio_de_negocio(self):
        classification, _ = classify_http(status=422, error_code="validation_error")
        self.assertEqual(classification, EXPECTED_VALIDATION)
        classification, _ = classify_http(status=400, error_code="http_error")
        self.assertEqual(classification, EXPECTED_VALIDATION)

    def test_excecao_nao_tratada_e_erro_real(self):
        classification, severity = classify_http(status=500, unhandled=True)
        self.assertEqual(classification, REAL_ERROR)
        self.assertEqual(severity, "CRITICAL")

    def test_indisponibilidade_e_erro_tecnico(self):
        classification, _ = classify_http(status=503, error_code="database_unavailable")
        self.assertEqual(classification, TECHNICAL_ERROR)

    def test_sucesso_lento_vira_performance(self):
        classification, _ = classify_http(status=200, latency_ms=50)
        self.assertEqual(classification, OK)
        classification, _ = classify_http(status=200, latency_ms=9000)
        self.assertEqual(classification, PERFORMANCE_ERROR)

    def test_segredos_nunca_sao_persistidos(self):
        limpo = sanitize({"senha": "x", "cookie": "y", "op": "OP-1", "lista": [{"token": "z"}]})
        self.assertEqual(limpo["senha"], "<omitido>")
        self.assertEqual(limpo["cookie"], "<omitido>")
        self.assertEqual(limpo["op"], "OP-1")
        self.assertEqual(limpo["lista"][0]["token"], "<omitido>")


class ShiftWindowTests(unittest.TestCase):
    def test_janelas_vem_do_dominio(self):
        windows = {window.key: window for window in shift_windows_for_date(date(2026, 9, 13))}
        self.assertEqual(set(windows), {"he_manha", "turno", "he_noite"})
        official_start, official_end = OFFICIAL_WORK_WINDOW
        self.assertEqual(windows["turno"].start.time(), official_start)
        self.assertEqual(windows["turno"].end.time(), official_end)
        self.assertEqual(windows["he_manha"].start.time(), OVERTIME_WINDOWS[0][0])
        self.assertEqual(windows["he_noite"].end.time(), OVERTIME_WINDOWS[1][1])
        self.assertEqual(windows["turno"].directory_name, "2026-09-13_turno")


class ReadOnlyConfigTests(unittest.TestCase):
    def test_dsn_de_observacao_forca_sessao_somente_leitura(self):
        config = read_only_config("postgresql://u:p@127.0.0.1:15432/gestor_pecas")
        values = conninfo_to_dict(config.dsn)
        self.assertIn(READ_ONLY_OPTION, values["options"])
        self.assertEqual(values["application_name"], "gestor_dev_observatory")
        self.assertEqual(values["dbname"], "gestor_pecas")

    def test_opcoes_existentes_sao_preservadas(self):
        config = read_only_config(
            "postgresql://u:p@127.0.0.1:15432/gestor_pecas?options=-c%20statement_timeout%3D5000"
        )
        options = conninfo_to_dict(config.dsn)["options"]
        self.assertIn("statement_timeout", options)
        self.assertIn(READ_ONLY_OPTION, options)


class DevObservatoryApiTests(unittest.TestCase):
    def setUp(self):
        # O freio de tentativa de senha vive no módulo do roteador e sobrevive
        # entre testes: sem zerar, as recusas somadas de um teste travariam o
        # login do próximo.
        dev_observatory_router._login_failures.clear()
        self._temp = tempfile.TemporaryDirectory()
        self.report_dir = Path(self._temp.name)
        self.db = ApiFakeDatabase()
        self.db.criar_usuario("Admin Web", "senha-admin", "admin")
        self.db.criar_usuario("Gestor Web", "senha-segura", "gestor")
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
            session_ttl_seconds=3600,
            # Sem o mount do SPA: a rota do observatório e a rota de falha do
            # teste precisam ser resolvidas pelo router, não pelo catch-all "/".
            serve_static=False,
            dev_observatory_enabled=True,
            dev_observatory_report_dir=str(self.report_dir),
            # Sem DSN de REAL: o teste não depende de um PostgreSQL de produção.
            dev_observatory_real_dsn="",
            # Login próprio do observatório: nada aqui vem da tabela `usuarios`.
            dev_observatory_login_username="devobs",
            dev_observatory_login_password="senha-do-observatorio",
            dev_observatory_session_secret="devobs-secret-that-is-long-enough-for-signatures-123456",
        )
        self.app = create_app(settings=settings, database_factory=lambda: self.db)

        @self.app.get("/api/v1/_falha_proposital")
        def _falha_proposital():
            raise ValueError("defeito proposital para o teste do observatório")

        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self):
        self.client.close()
        self._temp.cleanup()

    def _login(self, username, password):
        response = self.client.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _login_dev_observatory(self, username="devobs", password="senha-do-observatorio"):
        response = self.client.post(
            "/api/v1/dev-observatory/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def _dev_csrf(self):
        return {
            "X-CSRF-Token": self.client.cookies.get("gestor_devobs_csrf"),
        }

    # ------------------------------------------------------------------
    def test_login_e_independente_da_tabela_usuarios(self):
        """O ponto central desta rodada: logar como admin do Gestor de Peças
        não abre o observatório, e vice-versa — as duas sessões não se tocam."""

        self.assertEqual(self.client.get("/api/v1/dev-observatory/status").status_code, 401)

        # Admin do sistema principal, sozinho, não é suficiente.
        self._login("Admin Web", "senha-admin")
        ainda_negado = self.client.get("/api/v1/dev-observatory/status")
        self.assertEqual(ainda_negado.status_code, 401)
        self.client.cookies.clear()

        # Senha errada não entra.
        errado = self.client.post(
            "/api/v1/dev-observatory/login",
            json={"username": "devobs", "password": "senha-errada"},
        )
        self.assertEqual(errado.status_code, 401)
        self.assertEqual(errado.json()["code"], "dev_observatory_invalid_credentials")

        # Credencial própria do observatório entra.
        self._login_dev_observatory()
        permitido = self.client.get("/api/v1/dev-observatory/status")
        self.assertEqual(permitido.status_code, 200, permitido.text)
        payload = permitido.json()
        self.assertIn("environments", payload)
        self.assertFalse(payload["environments"]["real"]["configured"])
        self.assertIn("nenhuma", payload["write_policy"]["database_writes"])

    def test_logout_do_observatorio_nao_derruba_a_sessao_principal(self):
        self._login("Gestor Web", "senha-segura")
        self._login_dev_observatory()

        saida = self.client.post("/api/v1/dev-observatory/logout")
        self.assertEqual(saida.status_code, 204)
        self.assertEqual(self.client.get("/api/v1/dev-observatory/status").status_code, 401)
        # A sessão do Gestor de Peças continua de pé.
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)

    def test_login_trava_depois_de_tentativas_seguidas_e_aceita_senha_nao_ascii(self):
        """Atrás desta única credencial estão stack trace, catálogo do
        PostgreSQL e leitura do REAL; o Gestor é publicado por hostname
        externo. Adivinhação ilimitada de senha não pode existir aqui."""

        maximo = dev_observatory_router.LOGIN_MAX_FAILURES
        for tentativa in range(maximo):
            recusa = self.client.post(
                "/api/v1/dev-observatory/login",
                json={"username": "devobs", "password": f"errada-{tentativa}"},
            )
            self.assertEqual(recusa.status_code, 401, recusa.text)

        travado = self.client.post(
            "/api/v1/dev-observatory/login",
            json={"username": "devobs", "password": "errada-de-novo"},
        )
        self.assertEqual(travado.status_code, 429)
        self.assertEqual(travado.json()["code"], "dev_observatory_login_blocked")

        # Durante o bloqueio nem a senha correta passa: é o freio, não um
        # oráculo de senha certa.
        self.assertEqual(
            self.client.post(
                "/api/v1/dev-observatory/login",
                json={"username": "devobs", "password": "senha-do-observatorio"},
            ).status_code,
            429,
        )

        # Senha fora do ASCII recusa com 401 — antes derrubava o endpoint com
        # 500, porque `secrets.compare_digest` não compara `str` acentuada.
        dev_observatory_router._login_failures.clear()
        acentuada = self.client.post(
            "/api/v1/dev-observatory/login",
            json={"username": "devobs", "password": "senhá-com-acento"},
        )
        self.assertEqual(acentuada.status_code, 401, acentuada.text)

        # E o sucesso zera o contador acumulado.
        self._login_dev_observatory()
        self.assertEqual(dev_observatory_router._login_failures, {})

    def test_pagina_mostra_login_proprio_para_quem_nao_entrou(self):
        anonimo = self.client.get("/dev-observatory")
        self.assertEqual(anonimo.status_code, 401)
        self.assertIn("text/html", anonimo.headers["content-type"])
        self.assertIn("Login próprio", anonimo.text)

        # Estar logado no Gestor de Peças (mesmo como admin) não troca a página.
        self._login("Admin Web", "senha-admin")
        ainda_login = self.client.get("/dev-observatory")
        self.assertEqual(ainda_login.status_code, 401)
        self.client.cookies.clear()

        self._login_dev_observatory()
        pagina = self.client.get("/dev-observatory")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("Dev Observatory", pagina.text)
        self.assertEqual(self.client.get("/dev-observatory/app.js").status_code, 200)
        self.assertEqual(self.client.get("/dev-observatory/app.css").status_code, 200)

    def test_captura_classifica_bloqueio_esperado_e_erro_real(self):
        # Duas sessões coexistindo, cada uma com seu cookie: a gerencial só
        # para gerar tráfego real a capturar, e a do observatório para lê-lo.
        self._login("Gestor Web", "senha-segura")
        self._login_dev_observatory()
        # Recusa decidida pelo domínio (AppError) -> bloqueio esperado.
        recusa = self.client.get("/api/v1/management/kpis/kpi-inexistente/explanation")
        self.assertEqual(recusa.status_code, 404)
        # Exceção não tratada -> erro real, com stack trace preservado.
        falha = self.client.get("/api/v1/_falha_proposital")
        self.assertEqual(falha.status_code, 500)

        eventos = self.client.get("/api/v1/dev-observatory/events?limit=50").json()
        por_classe = {}
        for item in eventos["items"]:
            por_classe.setdefault(item["classification"], []).append(item)

        self.assertIn(EXPECTED_BLOCK, por_classe)
        self.assertTrue(
            any(item["error_code"] == "unknown_management_kpi" for item in por_classe[EXPECTED_BLOCK])
        )
        self.assertIn(REAL_ERROR, por_classe)
        erro = por_classe[REAL_ERROR][0]
        self.assertEqual(erro["route"], "/api/v1/_falha_proposital")
        self.assertEqual(erro["exception"], "ValueError")
        self.assertIn("defeito proposital", erro["traceback"])
        self.assertGreaterEqual(eventos["summary"]["defects"], 1)

    def test_viewport_usa_a_projecao_canonica(self):
        self._login_dev_observatory()
        resposta = self.client.get("/api/v1/dev-observatory/viewports?env=test")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        payload = resposta.json()
        self.assertEqual(payload["source"], "FrontendBackendFacade.consulta_operacional(vinculo_operacional)")
        self.assertFalse(payload["read_only"])
        self.assertIn("items", payload)

    def test_real_sem_dsn_recusa_sem_derrubar_a_ferramenta(self):
        self._login_dev_observatory()
        resposta = self.client.get("/api/v1/dev-observatory/viewports?env=real")
        self.assertEqual(resposta.status_code, 503)
        self.assertEqual(resposta.json()["code"], "dev_observatory_real_unavailable")

    def test_relatorio_de_turno_e_gravado_e_idempotente(self):
        self._login_dev_observatory()
        self.client.get("/api/v1/management/kpis/kpi-inexistente/explanation")
        self.client.get("/api/v1/_falha_proposital")

        janelas = self.client.get("/api/v1/dev-observatory/shifts").json()
        self.assertEqual(len(janelas["windows"]), 3)

        hoje = date.today().isoformat()
        sem_csrf = self.client.post(
            "/api/v1/dev-observatory/reports",
            json={"day": hoje, "shift": "turno"},
        )
        self.assertEqual(sem_csrf.status_code, 403, sem_csrf.text)
        self.assertEqual(sem_csrf.json()["code"], "csrf_validation_failed")

        gerado = self.client.post(
            "/api/v1/dev-observatory/reports",
            headers=self._dev_csrf(),
            json={"day": hoje, "shift": "turno"},
        )
        self.assertEqual(gerado.status_code, 200, gerado.text)
        destino = self.report_dir / f"{hoje}_turno"
        self.assertTrue((destino / "report.md").is_file())
        self.assertTrue((destino / "report.json").is_file())

        conteudo = (destino / "report.md").read_text(encoding="utf-8")
        self.assertIn("Relatório de turno", conteudo)
        self.assertIn("Recomendações", conteudo)
        self.assertIn("Bloqueios esperados", conteudo)

        dados = json.loads((destino / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(dados["environment"]["database"], "gestor_pecas_test")
        self.assertIn("classifications", dados["summary"])

        repetido = self.client.post(
            "/api/v1/dev-observatory/reports",
            headers=self._dev_csrf(),
            json={"day": hoje, "shift": "turno"},
        )
        self.assertEqual(repetido.status_code, 409)
        self.assertEqual(repetido.json()["code"], "report_already_generated")

        forcado = self.client.post(
            "/api/v1/dev-observatory/reports",
            headers=self._dev_csrf(),
            json={"day": hoje, "shift": "turno", "force": True},
        )
        self.assertEqual(forcado.status_code, 200, forcado.text)

        listagem = self.client.get("/api/v1/dev-observatory/reports").json()
        self.assertTrue(any(item["name"] == f"{hoje}_turno" for item in listagem["items"]))
        markdown = self.client.get(f"/api/v1/dev-observatory/reports/{hoje}_turno")
        self.assertEqual(markdown.status_code, 200)
        self.assertIn("Relatório de turno", markdown.text)

    def test_relatorio_recusa_travessia_de_diretorio(self):
        self._login_dev_observatory()
        self.assertEqual(
            self.client.get("/api/v1/dev-observatory/reports/nao_existe").status_code, 404
        )
        # ``\`` não é separador de caminho em URL, então o nome chega inteiro ao
        # endpoint e é o guarda de caminho que precisa recusá-lo no Windows.
        escapando = self.client.get("/api/v1/dev-observatory/reports/..%5C..%5C.env")
        self.assertEqual(escapando.status_code, 404)
        self.assertEqual(escapando.json()["code"], "report_not_found")

    def test_schema_version_permanece_intacto(self):
        # Guarda contra uma regressão óbvia: o observatório não migra banco.
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
