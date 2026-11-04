"""Regras essenciais das preferências da dashboard home."""

import unittest

from app.core.preferences import (
    DASHBOARD_CARD_KEYS,
    MAX_CARD_COLS,
    MAX_CARD_ROWS,
    MAX_CARDS_ON_SCREEN,
    dashboard_default,
    normalizar_dashboard_home,
)

CARD_COUNT = len(DASHBOARD_CARD_KEYS)
DEFAULT_VISIBLE = tuple(key for key in DASHBOARD_CARD_KEYS if key not in {"chamadas", "metas", "andon"})
CUSTOM_KEYS = {"chamadas", "metas", "andon"}


class DashboardPreferencesTests(unittest.TestCase):
    def test_default_tem_catorze_visiveis_e_tres_novos_ocultos(self):
        cards = dashboard_default()["cards"]
        self.assertEqual(len(cards), CARD_COUNT)
        self.assertTrue(all(cards[key] for key in DEFAULT_VISIBLE))
        self.assertFalse(any(cards[key] for key in CUSTOM_KEYS))
        order = dashboard_default()["order"]
        self.assertEqual(len(order), CARD_COUNT)
        self.assertEqual(len(set(order)), CARD_COUNT)

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

    def test_normalizar_limita_a_tela_a_quatorze_visiveis(self):
        todos_true = {"cards": {key: True for key in DASHBOARD_CARD_KEYS}}
        normalizado = normalizar_dashboard_home(todos_true)
        visiveis = [key for key in normalizado["order"] if normalizado["cards"][key]]
        self.assertEqual(len(visiveis), MAX_CARDS_ON_SCREEN)

    def test_normalizar_sizes_invalidos_caem_no_default(self):
        normalizado = normalizar_dashboard_home(
            {"sizes": {"oee": {"cols": 99, "rows": 0}, "sectors_table": {"cols": "x"}, "insuportavel": {"cols": 10}}}
        )
        self.assertEqual(normalizado["sizes"]["oee"], dashboard_default()["sizes"]["oee"])
        self.assertEqual(normalizado["sizes"]["sectors_table"], dashboard_default()["sizes"]["sectors_table"])
        self.assertLessEqual(normalizado["sizes"]["oee"]["cols"], MAX_CARD_COLS)
        self.assertLessEqual(normalizado["sizes"]["oee"]["rows"], MAX_CARD_ROWS)

    def test_normalizar_order_desduplicado_e_completo(self):
        normalizado = normalizar_dashboard_home(
            {"cards": {"oee": True}, "order": ["andon", "oee", "oee", "epleas"]}
        )
        self.assertEqual(normalizado["order"][0], "andon")
        self.assertEqual(normalizado["order"][1], "oee")
        self.assertEqual(len(set(normalizado["order"])), CARD_COUNT)
        self.assertNotIn("epleas", normalizado["order"])

    def test_default_sizes_respeitam_tetos(self):
        for size in dashboard_default()["sizes"].values():
            self.assertLessEqual(size["cols"], MAX_CARD_COLS)
            self.assertLessEqual(size["rows"], MAX_CARD_ROWS)


if __name__ == "__main__":
    unittest.main()
