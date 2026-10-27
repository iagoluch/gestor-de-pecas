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
        self.assertIsNone(normalize_user_level("nivel_desconhecido"))
        self.assertEqual(navigation_for_level("nivel_desconhecido"), ())
        self.assertEqual(consultation_tabs_for_level("nivel_desconhecido"), ())
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
        self.assertFalse(can_manage_users("supervisor"))
        self.assertFalse(can_manage_users("almoxarifado"))
        self.assertFalse(can_manage_users("operador_corte"))
        for level in ("admin", "lider", "supervisor", "manufatura", "qualidade", "gestor", "diretoria"):
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


class MaintenanceOnlyAccessTests(unittest.TestCase):
    def test_mantenedor_nao_ve_gestao_nem_andon(self):
        from backend.api.dependencies.auth import access_flags
        self.assertEqual(
            access_flags("lider", "manutencao"),
            {"management_access": False, "andon_access": False, "maintenance_access": True},
        )

    def test_admin_mantem_tudo_e_lider_comum_nao_decide_manutencao(self):
        from backend.api.dependencies.auth import access_flags
        self.assertTrue(all(access_flags("admin", None).values()))
        flags = access_flags("lider", "lider")
        self.assertTrue(flags["management_access"])
        self.assertFalse(flags["maintenance_access"])

    def test_mantenedor_nao_edita_cotas_nem_desenho_da_qualidade(self):
        from types import SimpleNamespace
        from backend.api.routers.quality import _pode_editar
        self.assertFalse(_pode_editar(SimpleNamespace(role="lider", assigned_level="manutencao")))
        self.assertTrue(_pode_editar(SimpleNamespace(role="lider", assigned_level="lider")))
        self.assertTrue(_pode_editar(SimpleNamespace(role="admin", assigned_level="admin")))

    def test_lista_de_usuarios_rotula_mantenedor_como_manutencao(self):
        from backend.api.routers.management import _tela_do_nivel
        self.assertEqual(_tela_do_nivel("lider", "manutencao"), "manutencao")
        self.assertEqual(_tela_do_nivel("lider", "lider"), "gestao")
        self.assertEqual(_tela_do_nivel("admin", "admin"), "gestao")


class MaintenanceOnlyApiForbiddenTests(unittest.TestCase):
    """Rotas reais (só a sessão é simulada): a conta de Manutenção leva 403."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from backend.api.config import WebSettings
        from backend.api.database import get_database
        from backend.api.dependencies.auth import access_flags, get_current_user, require_csrf
        from backend.api.main import create_app
        from backend.api.schemas.auth import SessionUser

        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        app = create_app(settings=settings, database_factory=lambda: None)
        user = SessionUser(
            id=9, name="Mantenedor", role="lider", assigned_level="manutencao",
            operator_access=False, **access_flags("lider", "manutencao"),
        )
        app.dependency_overrides[get_database] = lambda: None
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: user
        self.client = TestClient(app)

    def test_gestao_andon_qualidade_e_chamada_recusam_o_mantenedor(self):
        casos = (
            ("get", "/api/v1/management/users", None),
            ("get", "/api/v1/andon", None),
            ("get", "/api/v1/quality/templates/PROD-1", None),
            ("post", "/api/v1/chamadas", {
                "contato_id": 1, "motivo": "Manutenção", "comentario": "teste",
                "solicitante_nome_manual": "Mantenedor", "solicitante_email": "m@x.com",
            }),
        )
        for metodo, rota, corpo in casos:
            with self.subTest(rota=rota):
                resposta = getattr(self.client, metodo)(rota, **({"json": corpo} if corpo else {}))
                self.assertEqual(resposta.status_code, 403)


if __name__ == "__main__":
    unittest.main()
