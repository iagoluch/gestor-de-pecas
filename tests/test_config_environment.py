"""A68: todo ambiente fora de test/development é tratado como produção."""

import unittest

from backend.api.config import WebSettings

SECRET = "s" * 40


class EnvironmentAsProductionTests(unittest.TestCase):
    def test_ambiente_desconhecido_sem_segredo_e_recusado(self):
        for nome in ("homologacao", "prd", "real"):
            with self.subTest(nome=nome), self.assertRaises(RuntimeError):
                WebSettings.from_env({"GESTOR_WEB_ENV": nome})

    def test_ambiente_desconhecido_liga_cookie_seguro_por_padrao(self):
        settings = WebSettings.from_env(
            {"GESTOR_WEB_ENV": "homologacao", "GESTOR_WEB_SESSION_SECRET": SECRET}
        )
        self.assertTrue(settings.cookie_secure)

    def test_development_e_test_seguem_sem_exigir_segredo(self):
        for nome in ("development", "test"):
            with self.subTest(nome=nome):
                settings = WebSettings.from_env({"GESTOR_WEB_ENV": nome})
                self.assertFalse(settings.cookie_secure)

    def test_cookie_explicito_continua_valendo(self):
        settings = WebSettings.from_env({
            "GESTOR_WEB_ENV": "homologacao",
            "GESTOR_WEB_SESSION_SECRET": SECRET,
            "GESTOR_WEB_COOKIE_SECURE": "false",
        })
        self.assertFalse(settings.cookie_secure)


if __name__ == "__main__":
    unittest.main()
