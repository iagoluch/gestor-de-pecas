import unittest

from simulacao.resource_selection import avaliar_corte, avaliar_destaque, avaliar_workbench


class SimulationResourceSelectionTests(unittest.TestCase):
    def test_workbench_selects_only_matching_resource_with_real_card(self):
        selected = avaliar_workbench(
            {"resource": "1303", "queue": [{"op": "SOAK1"}], "production": []}, "1303"
        )
        self.assertTrue(selected["selecionado"])
        self.assertEqual(selected["motivo"], "workbench_com_operacao_elegivel")

        no_demand = avaliar_workbench({"resource": "1303", "queue": [], "production": []}, "1303")
        self.assertFalse(no_demand["selecionado"])

        divergent = avaliar_workbench({"resource": "2204", "queue": [{"op": "SOAK1"}]}, "1303")
        self.assertFalse(divergent["selecionado"])
        self.assertEqual(divergent["motivo"], "resposta_recurso_divergente")

    def test_cutting_uses_backend_highlight_signal_without_reimplementing_rule(self):
        cut = avaliar_corte(
            {"resource": "Laser Ensis 3015", "items": [{"planos": [{"libera_destaque": True}]}]},
            "Laser Ensis 3015",
        )
        self.assertTrue(cut["selecionado"])
        self.assertTrue(cut["libera_destaque"])
        self.assertTrue(avaliar_destaque(corte_libera_destaque=cut["libera_destaque"])["selecionado"])

        no_release = avaliar_corte(
            {"resource": "Plasma TerraBlade 4", "items": [{"planos": [{"libera_destaque": False}]}]},
            "Plasma TerraBlade 4",
        )
        self.assertFalse(no_release["libera_destaque"])
        self.assertFalse(avaliar_destaque(corte_libera_destaque=False)["selecionado"])


if __name__ == "__main__":
    unittest.main()
