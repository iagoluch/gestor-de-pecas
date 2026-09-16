import unittest

from app.core.permissions import (
    ALL_OPERATIONAL_CONSULTATION_TABS,
    USER_LEVELS,
    can_access_andon_web,
    can_access_management_web,
    can_manage_users,
    consultation_tabs_for_level,
    is_sector_operator,
    navigation_for_level,
    normalize_user_level,
    operator_sector_for_user_level,
)


class PermissionMatrixTests(unittest.TestCase):
    def test_matriz_de_navegacao_por_nivel(self):
        self.assertEqual(
            navigation_for_level("admin"),
            (
                "Tela Inicial", "Tarefas", "Dobra", "Usinagem", "Serra", "Corte",
                "Consulta Operacional", "Relatórios", "Cadastro",
            ),
        )
        self.assertEqual(
            navigation_for_level("supervisor"),
            ("Tela Inicial", "Consulta Operacional", "Relatórios", "Cadastro"),
        )
        for level, sector in (
            ("operador_dobra", "Dobra"),
            ("operador_usinagem", "Usinagem"),
            ("operador_serra", "Serra"),
            ("operador_corte", "Corte"),
            ("operador_destaque", "Destaque"),
            ("operador_pintura", "Pintura"),
            # Wave 6F — a Solda virou cinco setores com conta por estação.
            ("estacao1aco", "Solda Aço"),
            ("estacao3alu", "Solda Alumínio"),
            ("robo1", "Solda Robô"),
            ("projetos", "Proj. Ferramentaria"),
            ("prototipo", "Protótipo"),
        ):
            self.assertEqual(
                navigation_for_level(level),
                (sector,),
            )
        self.assertEqual(navigation_for_level("almoxarifado"), ("Tela Inicial", "Consulta Operacional"))
        self.assertEqual(navigation_for_level("andon"), ())

    def test_matriz_de_consulta_e_compatibilidade_de_nivel(self):
        self.assertIn("almoxarifado", USER_LEVELS)
        self.assertIn("operador_serra", USER_LEVELS)
        self.assertIn("operador_corte", USER_LEVELS)
        self.assertIn("operador_pintura", USER_LEVELS)
        self.assertIn("estacao1aco", USER_LEVELS)
        self.assertIn("robo1", USER_LEVELS)
        self.assertNotIn("operador_solda", USER_LEVELS)
        self.assertIn("andon", USER_LEVELS)
        self.assertEqual(normalize_user_level("comum"), "operador_destaque")
        self.assertEqual(normalize_user_level("nivel_desconhecido"), "operador_destaque")
        for level in (
            "operador_destaque", "operador_dobra", "operador_usinagem",
            "operador_serra", "operador_corte", "operador_pintura", "estacao1aco",
        ):
            self.assertEqual(
                consultation_tabs_for_level(level),
                (),
            )
        self.assertEqual(consultation_tabs_for_level("admin"), ALL_OPERATIONAL_CONSULTATION_TABS)
        self.assertEqual(consultation_tabs_for_level("supervisor"), ALL_OPERATIONAL_CONSULTATION_TABS)
        self.assertEqual(consultation_tabs_for_level("almoxarifado"), ALL_OPERATIONAL_CONSULTATION_TABS)
        self.assertTrue(can_manage_users("admin"))
        self.assertTrue(can_manage_users("supervisor"))
        self.assertFalse(can_manage_users("almoxarifado"))
        self.assertFalse(can_manage_users("operador_corte"))
        for level in ("admin", "lider", "supervisor", "manufatura", "gestor", "diretoria"):
            self.assertTrue(can_access_management_web(level))
            self.assertEqual(consultation_tabs_for_level(level), ALL_OPERATIONAL_CONSULTATION_TABS)
        self.assertFalse(can_access_management_web("operador_dobra"))
        self.assertTrue(can_access_andon_web("andon"))
        self.assertTrue(can_access_andon_web("gestor"))
        self.assertFalse(can_access_andon_web("operador_dobra"))
        self.assertFalse(can_access_management_web("andon"))
        self.assertFalse(is_sector_operator("andon"))
        self.assertEqual(consultation_tabs_for_level("andon"), ())

    def test_perfis_operacionais_resolvem_um_unico_setor(self):
        self.assertTrue(is_sector_operator("estacao1aco"))
        self.assertEqual(operator_sector_for_user_level("estacao3aco").resources, ("Estação 3",))
        self.assertFalse(is_sector_operator("supervisor"))
        self.assertEqual(operator_sector_for_user_level("operador_pintura").name, "Pintura")
        self.assertEqual(operator_sector_for_user_level("operador_dobra").resources, ("1303", "2204", "Gasparini"))


if __name__ == "__main__":
    unittest.main()
