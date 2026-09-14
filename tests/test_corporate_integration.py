import unittest

from mes.contracts.corporate import CorporatePlanningGateway
from mes.services.corporate_integration import PendingCorporateIntegration
from mes.services.corporate_integration import totvs_production_order_status
from backend.api.config import WebSettings


class CorporateIntegrationTests(unittest.TestCase):
    def test_adaptador_pendente_implementa_porta_sem_acesso_externo(self):
        gateway = PendingCorporateIntegration()

        self.assertIsInstance(gateway, CorporatePlanningGateway)
        status = gateway.status()
        self.assertEqual(status.provider, "pending_totvs_definition")
        self.assertFalse(status.configured)
        self.assertFalse(status.planning_read_enabled)
        self.assertFalse(status.execution_write_enabled)

    def test_planejamento_nao_e_inferido_enquanto_ti_nao_definir_mecanismo(self):
        with self.assertRaisesRegex(RuntimeError, "ainda não configurada"):
            PendingCorporateIntegration().list_planning_changes()

    def test_status_push_reflete_configuracao_sem_habilitar_escrita_no_totvs(self):
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            totvs_enabled=True,
        )
        status = totvs_production_order_status(settings)
        self.assertEqual(status.provider, "totvs_production_order_push_v1")
        self.assertTrue(status.configured)
        self.assertTrue(status.planning_read_enabled)
        self.assertFalse(status.execution_write_enabled)


if __name__ == "__main__":
    unittest.main()
