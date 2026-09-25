from datetime import date, datetime, timedelta
import unittest

from backend.api.routers.highlight import _task_payload
from mes.services.cut import CutService
from mes.services.production import ProductionService
from tests.fakes import FakeDatabase


def _plan(**overrides):
    row = {
        "plano_hash": "hash-corte-1",
        "codigo_tarefa": "T3500",
        "programa": "P9000",
        "nome_chapa": "S420",
        "sequencia_nesting": 1,
        "material": "AÇO 304",
        "espessura": 3.0,
        "maquina_sigmanest": "Amada_ensis",
        "quantidade_processo": 1,
        "tempo_previsto_segundos": 82.5,
        "data_programa": date(2026, 8, 11),
        "area_usada": 4_500_000,
        "fracao_sucata": 0.25,
        "ativo": True,
    }
    row.update(overrides)
    return row


class CutServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.db.cut_plans.append(_plan())
        self.service = CutService(self.db, "OPERADOR CORTE", cutoff_date="2026-08-01")

    def test_fila_mapeia_maquina_e_nao_materializa_antes_do_inicio(self):
        rows = self.service.listar_fila("Laser Ensis 3015")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "Aguardando")
        self.assertEqual(rows[0]["maquina"], "Laser Ensis 3015")
        self.assertEqual(self.db.cut_appointments, [])

    def test_tarefa_repetida_aparece_uma_vez_com_total_de_nestings(self):
        self.db.cut_plans.append(_plan(
            plano_hash="hash-corte-2",
            programa="P9001",
            sequencia_nesting=2,
            tempo_previsto_segundos=40,
        ))

        rows = self.service.listar_fila("Laser Ensis 3015")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nesting_count"], 2)
        self.assertEqual(rows[0]["programas"], ["P9000", "P9001"])
        self.assertEqual(
            [(item["sequencia"], item["tempo_previsto_segundos"]) for item in rows[0]["nestings"]],
            [(1, 82.5), (2, 40)],
        )

        started = self.service.iniciar(rows[0]["plano_hash"], "Laser Ensis 3015")
        self.assertTrue(started.ok)
        self.assertEqual(started.data["nesting_count"], 2)
        self.assertEqual(started.data["nestings_em_processo"], 1)
        self.assertEqual(len(self.db.cut_appointments), 1)

        first_finished = self.service.finalizar(started.data["id"])
        self.assertTrue(first_finished.ok)
        self.assertEqual(first_finished.data["status"], "Em processo")
        self.assertEqual(first_finished.data["nestings_concluidos"], 1)
        self.assertEqual(first_finished.data["nestings_em_processo"], 1)
        self.assertEqual(first_finished.data["nestings_aguardando"], 0)
        self.assertIn("1/2", first_finished.message)
        self.assertEqual(len(self.db.cut_appointments), 2)

        last_finished = self.service.finalizar(first_finished.data["id"])
        self.assertTrue(last_finished.ok)
        self.assertEqual(last_finished.data["status"], "Finalizado")
        self.assertIn("Tarefa finalizada", last_finished.message)
        self.assertEqual(self.service.listar_fila(), [])
        self.assertTrue(all(row["status"] == "Finalizado" for row in self.db.cut_appointments))
        self.assertEqual(
            [event["tipo"] for event in self.db.events[-3:]],
            ["corte_iniciado", "corte_nesting_concluido", "corte_finalizado"],
        )

    def test_nestings_iniciam_do_primeiro_plano_registrado_ate_o_ultimo(self):
        self.db.cut_plans = [
            _plan(plano_hash="plano-10", programa="P10", sequencia_nesting=1),
            _plan(plano_hash="plano-2", programa="P2", sequencia_nesting=1),
        ]

        grouped = self.service.listar_fila("Laser Ensis 3015")[0]
        self.assertEqual(grouped["programas"], ["P2", "P10"])

        started = self.service.iniciar(grouped["plano_hash"], "Laser Ensis 3015")
        self.assertTrue(started.ok)
        self.assertEqual(self.db.cut_appointments[0]["programa"], "P2")

        advanced = self.service.finalizar(started.data["id"])
        self.assertTrue(advanced.ok)
        active = next(
            row for row in self.db.cut_appointments if row["status"] == "Em processo"
        )
        self.assertEqual(active["programa"], "P10")

    def test_inicio_e_fim_guardam_tempos_operadores_e_eventos(self):
        started = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")

        self.assertTrue(started.ok)
        self.assertEqual(started.data["status"], "Em processo")
        self.assertEqual(started.data["operador_inicio"], "OPERADOR CORTE")
        self.assertEqual(len(self.service.listar_fila()), 1)

        finished = self.service.finalizar(started.data["id"])

        self.assertTrue(finished.ok)
        self.assertEqual(finished.data["status"], "Finalizado")
        self.assertEqual(finished.data["operador_fim"], "OPERADOR CORTE")
        self.assertEqual(self.service.listar_fila(), [])
        self.assertEqual(
            [event["tipo"] for event in self.db.events[-2:]],
            ["corte_iniciado", "corte_finalizado"],
        )

    def test_parada_manual_e_retomada_do_corte_preservam_nesting_ativo(self):
        started = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")
        self.assertTrue(started.ok)

        stopped = self.service.parar(
            "Laser Ensis 3015",
            motivo_codigo="0029",
            comentario="Aguardando movimentação",
        )
        self.assertTrue(stopped.ok)
        self.assertEqual(self.db.buscar_estado_recurso_atual("Laser Ensis 3015")["categoria"], "parada")
        self.assertEqual(self.db.cut_appointments[0]["status"], "Em processo")

        resumed = self.service.retomar("Laser Ensis 3015")
        self.assertTrue(resumed.ok)
        estado = self.db.buscar_estado_recurso_atual("Laser Ensis 3015")
        self.assertEqual(estado["categoria"], "producao")
        # Nesting é repetição de chapa; o motivo mostra o plano em corte.
        self.assertRegex(estado["motivo"], r"^Plano \S")
        self.assertEqual(self.db.cut_appointments[0]["status"], "Em processo")
        self.assertEqual(
            [event["tipo"] for event in self.db.events[-3:]],
            ["corte_iniciado", "corte_parado", "corte_retomado"],
        )

    def test_parada_do_corte_independe_de_tarefa_ativa_e_exige_motivo_valido(self):
        no_task = self.service.parar("Laser Ensis 3015", motivo_codigo="0029")
        self.assertTrue(no_task.ok)
        self.assertEqual(no_task.data["estado_recurso"]["categoria"], "parada")

        resumed = self.service.retomar("Laser Ensis 3015")
        self.assertTrue(resumed.ok)
        self.assertEqual(resumed.data["status"], "Sem nesting ativo")
        estado = self.db.buscar_estado_recurso_atual("Laser Ensis 3015")
        self.assertEqual(estado["categoria"], "fila")
        self.assertEqual(estado["motivo"], "Recurso sem demanda")

        invalid = self.service.parar("Plasma TerraBlade 4", motivo_codigo="1005")
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.code, "motivo_invalido")

    def test_pausa_programada_manual_preserva_classificacao_do_catalogo(self):
        stopped = self.service.parar("Laser Ensis 3015", motivo_codigo="0009")

        self.assertTrue(stopped.ok)
        state = self.db.buscar_estado_recurso_atual("Laser Ensis 3015")
        self.assertTrue(state["planejado"])
        self.assertFalse(state["automatico"])

    def test_duplo_inicio_e_dupla_finalizacao_sao_bloqueados(self):
        started = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")

        duplicate_start = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")
        self.assertFalse(duplicate_start.ok)
        self.assertEqual(duplicate_start.code, "plano_indisponivel")

        self.assertTrue(self.service.finalizar(started.data["id"]).ok)
        duplicate_finish = self.service.finalizar(started.data["id"])
        self.assertFalse(duplicate_finish.ok)
        self.assertEqual(duplicate_finish.code, "estado_alterado")

    def test_recorte_data_maquina_e_inativacao_controlam_fila(self):
        self.db.cut_plans.extend([
            _plan(
                plano_hash="antigo",
                programa="PANTIGO",
                data_programa=date(2026, 7, 31),
            ),
            _plan(
                plano_hash="plasma",
                programa="PPLASMA",
                maquina_sigmanest="Messer_XPR_300",
            ),
            _plan(plano_hash="inativo", programa="PINATIVO", ativo=False),
        ])

        laser = self.service.listar_fila("Laser Ensis 3015")
        plasma = self.service.listar_fila("Plasma TerraBlade 4")

        self.assertEqual([row["plano_hash"] for row in laser], ["hash-corte-1"])
        self.assertEqual([row["plano_hash"] for row in plasma], ["plasma"])

    def test_fila_mostra_os_programas_mais_recentes_primeiro(self):
        self.db.cut_plans.append(_plan(
            plano_hash="mais-recente",
            codigo_tarefa="T3501",
            programa="PNOVO",
            data_programa=date(2026, 8, 12),
        ))

        rows = self.service.listar_fila("Laser Ensis 3015")

        self.assertEqual(
            [row["plano_hash"] for row in rows],
            ["mais-recente", "hash-corte-1"],
        )

    def test_dashboard_mes_consolida_catalogo_e_apontamentos_do_periodo(self):
        started = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")
        self.assertTrue(started.ok)
        self.db.cut_appointments[0]["data_inicio"] = datetime(2026, 8, 11, 8, 0, 0)
        finished = self.service.finalizar(started.data["id"])
        self.assertTrue(finished.ok)
        self.db.cut_appointments[0]["data_fim"] = datetime(2026, 8, 31, 18, 5, 0)
        self.db.cut_plans.append(_plan(
            plano_hash="fila-dashboard",
            codigo_tarefa="T3600",
            programa="P9100",
            data_programa=date(2026, 8, 12),
        ))

        result = self.service.calcular_dashboard_mes(
            datetime(2026, 8, 1),
            datetime(2026, 8, 31),
        )

        self.assertEqual(result["indicadores"]["tarefas"], 2)
        self.assertEqual(result["indicadores"]["nestings_concluidos"], 1)
        self.assertEqual(result["indicadores"]["tempo_previsto_segundos"], 165.0)
        self.assertEqual(len(result["atividades"]), 2)
        laser = result["maquinas"]["Laser Ensis 3015"]
        self.assertEqual(laser["status"], "Aguardando")
        self.assertEqual(laser["tarefa"], "T3600")
        self.assertEqual(laser["plano"], "P9100")

    def test_consulta_da_analista_mantem_finalizado_e_pesquisa(self):
        start = self.service.iniciar("hash-corte-1", "Laser Ensis 3015")
        row = self.db.cut_appointments[0]
        row["data_inicio"] = datetime.now().replace(microsecond=0) - timedelta(minutes=3)
        self.service.finalizar(start.data["id"])

        rows = self.service.listar_consulta(status="Finalizado", search="T3500")

        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["tempo_real_segundos"], 180)
        self.assertEqual(rows[0]["programa"], "P9000")

    def test_tempos_individuais_de_nesting_sao_expostos_para_gestao(self):
        self.db.cut_plans.append(_plan(
            plano_hash="hash-corte-2",
            programa="P9001",
            sequencia_nesting=2,
            tempo_previsto_segundos=120,
        ))
        grouped = self.service.listar_fila("Laser Ensis 3015")[0]
        started = self.service.iniciar(grouped["plano_hash"], "Laser Ensis 3015")
        self.db.cut_appointments[0]["data_inicio"] = datetime(2026, 8, 11, 8, 0, 0)
        first = self.service.finalizar(started.data["id"])
        self.db.cut_appointments[0]["data_fim"] = datetime(2026, 8, 11, 8, 2, 0)
        active = next(row for row in self.db.cut_appointments if row["status"] == "Em processo")
        active["data_inicio"] = datetime(2026, 8, 11, 8, 2, 0)
        self.service.finalizar(active["id"])
        active["data_fim"] = datetime(2026, 8, 11, 8, 5, 0)

        rows = self.service.listar_tempos_nesting(
            datetime(2026, 8, 11, 0, 0), datetime(2026, 8, 11, 23, 59)
        )

        self.assertEqual(len(rows), 2)
        by_program = {row["programa"]: row for row in rows}
        self.assertEqual(by_program["P9000"]["real_segundos"], 120)
        self.assertEqual(by_program["P9001"]["real_segundos"], 180)
        self.assertIsNotNone(by_program["P9000"]["desvio_percentual"])

    def test_historico_soma_duracoes_dos_nestings_sem_contar_intervalo_ou_virada(self):
        self.db.listar_ops_catalogo_tarefa = lambda codigo: [
            {"codigo_tarefa": codigo, "codigo_op": "OP-CORTE-01"},
            {"codigo_tarefa": codigo, "codigo_op": "OP-CORTE-02"},
        ]
        self.db.cut_plans.append(_plan(
            plano_hash="hash-corte-2",
            programa="P9001",
            sequencia_nesting=2,
            tempo_previsto_segundos=120,
        ))
        first = {**self.db.cut_plans[0], "id": 1, "maquina": "Laser Ensis 3015", "status": "Finalizado",
                 "operador_inicio": "A", "operador_fim": "A",
                 "data_inicio": datetime(2026, 8, 11, 23, 57), "data_fim": datetime(2026, 8, 12, 0, 2)}
        second = {**self.db.cut_plans[1], "id": 2, "maquina": "Laser Ensis 3015", "status": "Finalizado",
                  "operador_inicio": "B", "operador_fim": "B",
                  "data_inicio": datetime(2026, 8, 12, 8, 0), "data_fim": datetime(2026, 8, 12, 8, 3)}
        self.db.cut_appointments = [first, second]

        rows = self.service.listar_consulta(status="Finalizado", search="T3500")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["data_inicio"], first["data_inicio"])
        self.assertEqual(rows[0]["data_fim"], second["data_fim"])
        self.assertEqual(rows[0]["tempo_real_segundos"], 480)
        self.assertEqual(rows[0]["ops_relacionadas"], ["OP-CORTE-01", "OP-CORTE-02"])
        self.assertEqual(
            [item["tempo_real_segundos"] for item in rows[0]["nestings"]],
            [300, 180],
        )

    def test_historico_usa_fim_real_para_ordenar_processadas_mais_recentes(self):
        older = {**self.db.cut_plans[0], "id": 1, "maquina": "Laser Ensis 3015", "status": "Finalizado",
                 "codigo_tarefa": "T-ANTIGA", "operador_inicio": "A", "operador_fim": "A",
                 "data_programa": date(2026, 8, 20),
                 "data_inicio": datetime(2026, 8, 20, 8), "data_fim": datetime(2026, 8, 20, 9)}
        newer = {**self.db.cut_plans[0], "id": 2, "maquina": "Laser Ensis 3015", "status": "Finalizado",
                 "codigo_tarefa": "T-RECENTE", "plano_hash": "recente", "operador_inicio": "B", "operador_fim": "B",
                 "data_programa": date(2026, 8, 1),
                 "data_inicio": datetime(2026, 8, 21, 8), "data_fim": datetime(2026, 8, 21, 9)}
        self.db.cut_appointments = [older, newer]

        rows = self.service.listar_consulta(status="Finalizado")

        self.assertEqual([row["codigo_tarefa"] for row in rows], ["T-RECENTE", "T-ANTIGA"])

    def test_destaque_materializa_tarefa_do_catalogo_local_de_corte(self):
        class CatalogDatabase(FakeDatabase):
            def materializar_tarefa_catalogo(inner_self, codigo):
                plan = next(
                    (row for row in inner_self.cut_plans if row["codigo_tarefa"] == str(codigo).strip().upper()),
                    None,
                )
                if not plan:
                    return None
                task_id = inner_self.inserir_tarefa(
                    plan["codigo_tarefa"], material=plan["material"], espessura=plan["espessura"]
                )
                return inner_self.buscar_tarefa_por_id(task_id)

        database = CatalogDatabase()
        database.cut_plans.append(_plan())
        service = ProductionService(database, "OPERADOR DESTAQUE")

        payload = _task_payload(database, service, "T3500", operador="OPERADOR DESTAQUE")

        self.assertEqual(payload["task"]["codigo_tarefa"], "T3500")
        self.assertEqual(payload["state"]["estado"], "aguardando")
        self.assertEqual(payload["cutting"][0]["codigo_tarefa"], "T3500")
        self.assertEqual(payload["cutting"][0]["status"], "Aguardando")



if __name__ == "__main__":
    unittest.main()
