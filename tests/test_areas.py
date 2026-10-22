"""Áreas da fábrica na gestão: cada conta enxerga só as do seu setor (09/10/2026)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.core.areas import AREAS, areas_for_user
from backend.api.config import WebSettings
from backend.api.main import create_app
from tests.fakes import FakeDatabase


def _ids(nivel_atribuido, nivel_efetivo):
    return [area["id"] for area in areas_for_user(nivel_atribuido, nivel_efetivo)]


class AreasPorNivelTests(unittest.TestCase):
    def test_lider_ve_so_a_propria_area(self):
        self.assertEqual(_ids("lider_serra", "lider"), ["serra"])
        self.assertEqual(_ids("lider_dobra_corte", "lider"), ["dobra-corte"])

    def test_supervisor_ve_as_areas_do_seu_setor(self):
        self.assertEqual(_ids("supervisor_caldeiraria", "supervisor"), ["dobra-corte", "usinagem", "serra"])
        self.assertEqual(_ids("supervisor_almoxarifado_solda_pintura", "supervisor"), ["solda", "pintura"])

    def test_admin_e_gerente_veem_todas(self):
        self.assertEqual(_ids("admin", "admin"), list(AREAS))
        self.assertEqual(_ids("gerente_industrial", "gestor"), list(AREAS))

    def test_areas_sao_exclusivas_de_quem_trabalha_nelas(self):
        for nivel in ("diretoria", "qualidade", "manufatura", "gestor"):
            self.assertEqual(_ids(nivel, nivel), [])
            self.assertEqual(_ids(None, nivel), [])

    def test_nivel_personalizado_sem_mapa_nao_ve_areas(self):
        for nome, base in (("pcp", "gestor"), ("controladoria", "gestor"), ("projetos_adm", "supervisor")):
            self.assertEqual(_ids(nome, base), [])

    def test_quem_nao_e_da_gestao_nao_ve_areas(self):
        self.assertEqual(_ids("operador_serra", "operador_serra"), [])
        self.assertEqual(_ids(None, "andon"), [])

    def test_todo_id_mapeado_existe(self):
        from app.core.areas import AREAS_POR_NIVEL

        for ids in AREAS_POR_NIVEL.values():
            self.assertTrue(set(ids) <= set(AREAS))


class LoginDevolveAreasTests(unittest.TestCase):
    def test_login_e_sessao_trazem_as_areas_do_nivel_atribuido(self):
        db = FakeDatabase()
        db.custom_levels.append({"nome": "lider_serra", "rotulo": "Líder Serra", "nivel_base": "lider"})
        db.criar_usuario("murilo", "123456", "lider_serra")
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        app = create_app(settings=settings, database_factory=lambda: db)
        with TestClient(app) as client:
            resposta = client.post("/api/v1/auth/login", json={"username": "murilo", "password": "123456"})
            self.assertEqual(resposta.status_code, 200, resposta.text)
            corpo = resposta.json()
            self.assertEqual(corpo["role"], "lider")
            self.assertEqual([a["id"] for a in corpo["areas"]], ["serra"])
            self.assertEqual(corpo["areas"][0]["setores"], ["Serra"])
            sessao = client.get("/api/v1/auth/session")
            self.assertEqual(sessao.status_code, 200, sessao.text)
            self.assertEqual([a["id"] for a in sessao.json()["areas"]], ["serra"])


if __name__ == "__main__":
    unittest.main()
