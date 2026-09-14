from __future__ import annotations

import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import resetar_banco_teste as reset  # noqa: E402


class ResetarBancoTesteSafetyTests(unittest.TestCase):
    def test_nome_do_alvo_precisa_ser_literal_e_exato(self):
        self.assertEqual(
            reset._validate_exact_name(
                "gestor_pecas_test",
                source="teste",
                expected=reset.EXPECTED_DATABASE,
            ),
            reset.EXPECTED_DATABASE,
        )
        for invalid in ("gestor_pecas", "GESTOR_PECAS_TEST", "gestor_pecas_test_2", ""):
            with self.subTest(invalid=invalid), self.assertRaises(RuntimeError):
                reset._validate_exact_name(
                    invalid,
                    source="teste",
                    expected=reset.EXPECTED_DATABASE,
                )

    def test_tabelas_operacionais_e_protegidas_sao_disjuntas(self):
        operational = set(reset.TRUNCATE_TABLES)
        protected = set(reset.PROTECTED_TABLES)
        self.assertFalse(operational & protected)
        self.assertNotIn(reset.SELECTIVE_TABLE, operational)
        self.assertNotIn(reset.SELECTIVE_TABLE, protected)
        self.assertEqual(
            operational | protected | {reset.SELECTIVE_TABLE},
            set(reset.KNOWN_TABLES),
        )

    def test_cadastros_e_configuracoes_permanecem_protegidos(self):
        expected_protected = {
            "schema_migrations",
            "usuarios",
            "operadores_apontamento",
            "catalogo_recursos_pcfactory",
            "catalogo_status_recursos",
            "calendarios_produtivos",
            "turnos_produtivos",
            "intervalos_turno_produtivo",
            "excecoes_calendario_produtivo",
            "pausas_automaticas_setor",
            "ai_conversations",
            "ai_messages",
            "ai_knowledge",
            "generated_reports",
            "report_schedules",
            "messaging_destinations",
            "report_deliveries",
            "qualidade_templates_produto",
            "qualidade_cotas_template",
            "qualidade_desenhos_produto",
        }
        self.assertTrue(expected_protected <= set(reset.PROTECTED_TABLES))

    def test_planejamento_e_execucao_estao_no_escopo(self):
        expected_operational = {
            "catalogo_pcp_ops",
            "catalogo_operacoes_op",
            "catalogo_sigmanest_tarefas",
            "catalogo_sigmanest_programas",
            "catalogo_sigmanest_ops",
            "catalogo_sigmanest_planos_corte",
            "tarefas",
            "op_por_tarefa",
            "apontamentos_operacionais",
            "eventos_apontamento_operador",
            "apontamentos_corte",
            "eventos_destaque_tarefa",
            "qualidade_inspecoes",
            "qualidade_pecas_inspecionadas",
            "qualidade_resultados_cota",
            "qualidade_rnc",
            "totvs_outbox",
            "totvs_outbox_attempts",
            "totvs_op_sync_requests",
        }
        self.assertTrue(expected_operational <= set(reset.TRUNCATE_TABLES))

    def test_execucao_sem_confirmacao_nao_abre_banco(self):
        with (
            patch.object(sys, "argv", ["resetar_banco_teste.py"]),
            patch.object(reset, "execute_reset") as execute,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(reset.main(), 2)
        execute.assert_not_called()

    def test_confirmacao_errada_nao_abre_banco(self):
        with (
            patch.object(
                sys,
                "argv",
                ["resetar_banco_teste.py", "--confirmar", "gestor_pecas"],
            ),
            patch.object(reset, "execute_reset") as execute,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            self.assertEqual(reset.main(), 2)
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
