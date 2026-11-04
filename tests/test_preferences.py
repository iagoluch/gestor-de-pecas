"""Regras essenciais das preferências da dashboard home."""

import unittest

from app.core.preferences import dashboard_default, normalizar_dashboard_home


class DashboardPreferencesTests(unittest.TestCase):
    def test_default_habilita_todos_os_blocos(self):
        cards = dashboard_default()["cards"]
        self.assertEqual(len(cards), 14)
        self.assertTrue(all(cards.values()))

    def test_normalizar_descarta_chaves_desconhecidas_e_preenche_omitidas(self):
        normalizado = normalizar_dashboard_home(
            {"cards": {"oee": False, "nao_existe": True, "sectors_table": False}}
        )
        self.assertFalse(normalizado["cards"]["oee"])
        self.assertFalse(normalizado["cards"]["sectors_table"])
        self.assertTrue(normalizado["cards"]["ftt"])
        self.assertNotIn("nao_existe", normalizado["cards"])

    def test_normalizar_devolve_default_para_payload_invalido(self):
        self.assertEqual(normalizar_dashboard_home(None), dashboard_default())
        self.assertEqual(normalizar_dashboard_home({"cards": "invalido"}), dashboard_default())


if __name__ == "__main__":
    unittest.main()
