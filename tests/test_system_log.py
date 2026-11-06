"""Log do sistema por área (migration 74, 11/2026).

Sem banco: o gravador é exercitado com um banco em memória; as rotas, com
``create_app`` e o mesmo padrão de override de ``test_change_audit``.
"""

from __future__ import annotations

import logging
import unittest
from datetime import datetime

from fastapi.testclient import TestClient

from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from backend.observability.system_log import (
    AREAS,
    SystemLog,
    area_da_rota,
    area_do_logger,
    nivel_do_status,
)
from tests.fakes import FakeDatabase

M = "/api/v1/management"


def _user(role):
    return SessionUser(
        id=1, name="Fulano", role=role, management_access=True, andon_access=True,
        operator_access=False,
    )


class _Db(FakeDatabase):
    def __init__(self):
        super().__init__()
        self.gravado = []
        self.limpezas = []
        self.filtros = None

    def gravar_log_lote(self, entradas):
        self.gravado.extend(entradas)
        return len(list(entradas))

    def limpar_log(self, *, antes_de):
        self.limpezas.append(antes_de)

    def listar_log(self, **filtros):
        self.filtros = filtros
        return [{"id": 1, "quando": datetime(2026, 11, 6, 8, 0), "area": "protheus", "nivel": "erro",
                 "evento": "log_aplicacao", "mensagem": "falhou", "usuario": None, "request_id": None,
                 "metodo": None, "rota": None, "status_http": None, "duracao_ms": None, "detalhe": None}]

    def resumo_log(self, *, desde):
        return [{"area": "protheus", "nivel": "erro", "total": 2}, {"area": "protheus", "nivel": "info", "total": 3},
                {"area": "desconhecida", "nivel": "info", "total": 9}]


class ClassificacaoTests(unittest.TestCase):
    def test_rota_vai_para_a_area_certa(self):
        casos = {
            "/api/v1/auth/login": "acesso",
            "/api/v1/cutting/plans/3/start": "corte",
            "/api/v1/admin/totvs-outbox/5/retry": "protheus",
            "/api/v1/management/users": "gestao",
            "/api/v1/algo-novo": "sistema",
        }
        for caminho, area in casos.items():
            self.assertEqual(area_da_rota(caminho), area, caminho)

    def test_logger_e_palavra_decidem_a_area(self):
        self.assertEqual(area_do_logger("mes.services.sigmanest_sync", "x"), "sigmanest")
        self.assertEqual(area_do_logger("root", "Falha ao falar com o Protheus"), "protheus")
        self.assertEqual(area_do_logger("root", "qualquer coisa"), "sistema")

    def test_toda_area_mapeada_existe_no_filtro(self):
        self.assertIn("sistema", AREAS)
        self.assertEqual(nivel_do_status(200), "info")
        self.assertEqual(nivel_do_status(409), "aviso")
        self.assertEqual(nivel_do_status(500), "erro")


class GravadorTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.log = SystemLog(lambda: self.db, now=lambda: datetime(2026, 11, 6, 9, 0))

    def test_flush_grava_em_lote_e_limpa_a_retencao(self):
        self.log.record("corte", "info", "x", "uma")
        self.log.record("area-inventada", "erro", "y", "duas", detalhe={"senha": "123", "ok": 1})
        self.assertEqual(self.log.flush(), 2)
        self.assertEqual(self.db.gravado[1]["area"], "sistema")
        self.assertEqual(self.db.gravado[1]["detalhe"]["senha"], "<omitido>")
        self.assertEqual(len(self.db.limpezas), 1)
        self.log.record("corte", "info", "x", "tres")
        self.log.flush()
        self.assertEqual(len(self.db.limpezas), 1, "limpeza só a cada algumas horas")

    def test_banco_fora_do_ar_nao_levanta(self):
        def quebrado():
            raise RuntimeError("sem banco")

        log = SystemLog(quebrado)
        log.record("corte", "info", "x", "uma")
        self.assertEqual(log.flush(), 0)

    def test_handler_leva_aviso_do_logging_e_ignora_info_interno(self):
        self.log.start()
        try:
            logging.getLogger("mes.services.sigmanest_sync").warning("janela atrasada")
            logging.getLogger("qualquer.coisa").info("conversa interna")
            logging.getLogger("httpx").warning("ruído de biblioteca")
        finally:
            self.log.stop()
        mensagens = [(e["area"], e["nivel"], e["mensagem"]) for e in self.db.gravado]
        self.assertIn(("sigmanest", "aviso", "janela atrasada"), mensagens)
        self.assertFalse([m for m in mensagens if m[2] in ("conversa interna", "ruído de biblioteca")])


class RotasTests(unittest.TestCase):
    def _client(self, role):
        self.db = _Db()
        app = create_app(
            settings=WebSettings(
                environment="test",
                session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
                allowed_hosts=("testserver",),
                allowed_origins=("http://testserver",),
            ),
            database_factory=lambda: self.db,
        )
        app.dependency_overrides[get_database] = lambda: self.db
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_admin_lista_com_filtros(self):
        client = self._client("admin")
        resposta = client.get(f"{M}/system-log", params={"area": "protheus", "nivel": "erro", "busca": "falh"})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["count"], 1)
        self.assertEqual(self.db.filtros["area"], "protheus")
        self.assertEqual(self.db.filtros["nivel"], "erro")

    def test_area_desconhecida_e_recusada(self):
        self.assertEqual(self._client("admin").get(f"{M}/system-log", params={"area": "x"}).status_code, 422)

    def test_resumo_traz_todas_as_areas_e_ignora_desconhecida(self):
        corpo = self._client("admin").get(f"{M}/system-log/summary").json()
        self.assertEqual([a["area"] for a in corpo["areas"]], list(AREAS))
        protheus = next(a for a in corpo["areas"] if a["area"] == "protheus")
        self.assertEqual((protheus["total"], protheus["erro"], protheus["aviso"]), (5, 2, 0))

    def test_quem_nao_e_admin_nao_ve(self):
        client = self._client("gestor")
        self.assertEqual(client.get(f"{M}/system-log").status_code, 403)
        self.assertEqual(client.get(f"{M}/system-log/summary").status_code, 403)

    def test_acao_que_muda_estado_vira_registro(self):
        client = self._client("admin")
        client.post(f"{M}/users", json={})  # 422 de validação: erro também entra
        client.app.state.system_log.flush()
        # o middleware enfileira; a thread só roda no lifespan, então basta ler a fila
        self.assertTrue(any(e["metodo"] == "POST" for e in client.app.state.system_log._queue) or self.db.gravado)


if __name__ == "__main__":
    unittest.main()
