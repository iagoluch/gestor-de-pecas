from __future__ import annotations

from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

from psycopg.conninfo import conninfo_to_dict

from simulacao.andon_demo import (
    DEMO_DATABASE,
    MIN_VISIBLE_RESOURCES,
    AndonDemo,
    ResourceRuntime,
    demo_dsns,
    validate_demo_dsn,
)


class _CatalogDatabase:
    safe_target = {"dbname": DEMO_DATABASE}

    def __init__(self, rows):
        self.rows = rows

    def listar_recursos_pcfactory(self):
        return list(self.rows)


class _CanonicalInventoryDatabase(_CatalogDatabase):
    def __init__(self, catalog_rows, scheduler_rows):
        super().__init__(catalog_rows)
        self.scheduler_rows = scheduler_rows

    def listar_recursos_ativos_scheduler(self):
        return list(self.scheduler_rows)


class AndonDemoConfigurationTests(unittest.TestCase):
    def test_dsn_demo_e_derivado_somente_de_fonte_teste(self):
        source, target, maintenance = demo_dsns({
            "TEST_DATABASE_URL": "host=127.0.0.1 port=5432 dbname=gestor_pecas_test user=demo password=x"
        })
        self.assertEqual(conninfo_to_dict(source)["dbname"], "gestor_pecas_test")
        self.assertEqual(conninfo_to_dict(target)["dbname"], DEMO_DATABASE)
        self.assertEqual(conninfo_to_dict(maintenance)["dbname"], "postgres")

    def test_fonte_real_e_alvo_real_sao_recusados_antes_da_conexao(self):
        with self.assertRaisesRegex(RuntimeError, "Fonte recusada"):
            demo_dsns({
                "TEST_DATABASE_URL": "host=127.0.0.1 dbname=gestor_pecas user=demo"
            })
        with self.assertRaisesRegex(RuntimeError, "Alvo recusado"):
            validate_demo_dsn("host=127.0.0.1 dbname=gestor_pecas user=demo")

    def test_discovery_cobre_todos_setores_presentes_e_minimo_oito(self):
        sectors = [
            "Corte", "Dobra", "Usinagem", "Serra", "Pintura",
            "Solda Aço", "Solda Robô", "Proj. Ferramentaria", "Protótipo",
        ]
        rows = [
            {"codigo": f"R{index:02d}", "nome": f"Recurso {index}", "tipo_setor": sector}
            for index, sector in enumerate(sectors, 1)
        ]
        rows.extend(
            {"codigo": f"EXTRA{index:02d}", "nome": f"Extra {index}", "tipo_setor": "Solda Aço"}
            for index in range(1, 12)
        )
        demo = AndonDemo(_CatalogDatabase(rows), seed=7, resource_count=16)
        selected, missing = demo.discover_resources()
        self.assertGreaterEqual(len(selected), MIN_VISIBLE_RESOURCES)
        self.assertEqual({row["tipo_setor"] for row in selected}, set(sectors))
        self.assertIn("Montagem", missing)
        self.assertIn("Solda Alumínio", missing)

    def test_catalogo_insuficiente_falha_em_vez_de_entregar_tela_vazia(self):
        rows = [
            {"codigo": f"R{index}", "nome": f"Recurso {index}", "tipo_setor": "Dobra"}
            for index in range(7)
        ]
        demo = AndonDemo(_CatalogDatabase(rows), seed=7, resource_count=8)
        with self.assertRaisesRegex(RuntimeError, "mínimo"):
            demo.discover_resources()

    def test_discovery_usa_inventario_apontavel_e_exclui_almox_sincronizado(self):
        sectors = [
            "Corte", "Dobra", "Usinagem", "Serra", "Pintura",
            "Solda Aço", "Solda Alumínio", "Solda Robô",
        ]
        scheduler_rows = [
            {"codigo": f"R{index:02d}", "nome": f"Posto {index}", "tipo_setor": sector}
            for index, sector in enumerate(sectors, 1)
        ]
        scheduler_rows[5] = {
            "codigo": "Estação 1", "nome": "Estação 1", "tipo_setor": "Solda Aço"
        }
        database = _CanonicalInventoryDatabase(
            catalog_rows=[
                {"codigo": "ALMOXS", "nome": "Almox", "tipo_setor": "Solda Aço"}
            ],
            scheduler_rows=scheduler_rows,
        )
        selected, _missing = AndonDemo(database, seed=3, resource_count=8).discover_resources()
        codes = {row["codigo"] for row in selected}
        self.assertIn("Estação 1", codes)
        self.assertNotIn("ALMOXS", codes)


class AndonDemoEvolutionTests(unittest.TestCase):
    def _demo(self):
        demo = AndonDemo(_CatalogDatabase([]), seed=11, resource_count=8)
        now = datetime(2026, 10, 6, 10, 0, 0)
        demo.resources = [
            ResourceRuntime(
                code="DOBRA1", name="Dobra 1", sector="Dobra", state="producao",
                appointment_id=10, op="DEMO-ANDON-DOBRA1-00001", operation="010",
                product="DEMO-DOBRA1", cycle_started=now - timedelta(minutes=24),
                cycle_ends=now + timedelta(minutes=20), next_quantity_at=now,
            ),
            ResourceRuntime(
                code="LASER1", name="Laser", sector="Corte", state="atividade_sem_op",
                appointment_id=None, op=None, operation=None, product=None,
                cycle_started=now - timedelta(minutes=30),
                cycle_ends=now + timedelta(minutes=50),
                next_quantity_at=now + timedelta(minutes=5),
            ),
        ]
        demo._day = now.date()
        demo.next_profile_at = now + timedelta(hours=1)
        return demo, now

    def test_corte_sem_nesting_nao_recebe_quantidade_ou_op_artificial(self):
        demo, now = self._demo()
        with patch.object(demo, "_increment_quantities") as increment:
            demo.step(now)
        increment.assert_called_once_with(demo.resources[0], now)
        self.assertIsNone(demo.resources[1].appointment_id)

    def test_virada_do_dia_rotaciona_apontamentos_e_nao_carrega_acumulado(self):
        demo, now = self._demo()
        demo._day = (now - timedelta(days=1)).date()
        with patch.object(demo, "_finish_and_restart") as rotate, patch.object(
            demo, "_increment_quantities"
        ):
            events = demo.step(now)
        rotate.assert_called_once_with(
            demo.resources[0], datetime(2026, 10, 6, 0, 0, 0)
        )
        self.assertEqual(events[0]["event"], "daily_rotation")

    def test_novo_ciclo_tem_duracao_entre_vinte_e_noventa_e_cinco_minutos(self):
        demo, now = self._demo()
        item = demo.resources[1]
        item.sector = "Dobra"
        item.appointment_id = None
        with patch.object(
            demo,
            "_create_active_cycle",
            return_value=(11, "DEMO-ANDON-DOBRA-00002", "011", "DEMO-DOBRA"),
        ), patch.object(demo, "_state"):
            demo._finish_and_restart(item, now)
        duration = (item.cycle_ends - item.cycle_started).total_seconds() / 60
        self.assertGreaterEqual(duration, 20)
        self.assertLessEqual(duration, 95)

    def test_perturbacao_gera_paradas_longas(self):
        demo, _now = self._demo()
        demo.profile = "PERTURBACAO"
        durations = [demo._stop_minutes() for _ in range(20)]
        self.assertTrue(all(20 <= duration <= 45 for duration in durations))
        self.assertGreater(len(set(durations)), 1)

    def test_retomada_de_parada_volta_ao_motor_de_producao(self):
        demo, now = self._demo()
        item = demo.resources[0]
        item.state = "parada"
        item.resume_at = now
        item.next_quantity_at = now + timedelta(minutes=1)
        with patch.object(demo, "_state") as state:
            events = demo.step(now)
        state.assert_called_once_with(
            item.code, item.sector, "producao", now,
            item.op, item.operation, item.product,
        )
        self.assertEqual(item.state, "producao")
        self.assertIsNone(item.resume_at)
        self.assertIn({"event": "resume", "resource": item.code}, events)

    def test_perfis_mudam_sem_sincronizar_ciclos_dos_recursos(self):
        demo, now = self._demo()
        original_ends = [item.cycle_ends for item in demo.resources]
        demo.next_profile_at = now
        with patch.object(demo, "_increment_quantities"):
            events = demo.step(now)
        self.assertNotEqual(demo.profile, "NORMAL")
        self.assertEqual([item.cycle_ends for item in demo.resources], original_ends)
        self.assertEqual(events[0]["event"], "profile")

    def test_loop_e_infinito_ate_interrupcao(self):
        demo, _now = self._demo()
        with patch.object(demo, "step", return_value=[]) as step, patch(
            "simulacao.andon_demo.time.sleep", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                demo.run_forever(poll_seconds=0.2)
        step.assert_called_once()


if __name__ == "__main__":
    unittest.main()
