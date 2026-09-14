from datetime import datetime
import unittest

from mes.analytics.timeline import build_operator_timeline
from mes.domain import EventCategory, ManufacturingRules
from mes.services.shift_boundary import ShiftBoundaryService
from tests.fakes import FakeDatabase


class ManufacturingRulesTests(unittest.TestCase):
    def test_saldo_e_conclusao_usam_boas_mais_refugo(self):
        self.assertEqual(ManufacturingRules.quantity_remaining(10, 6, 2), 2)
        self.assertFalse(ManufacturingRules.operation_is_complete(10, 7, 2))
        self.assertTrue(ManufacturingRules.operation_is_complete(10, 8, 2))
        self.assertEqual(ManufacturingRules.attended_quantity(8, 2), 10)

    def test_classificacao_produtiva_segue_manufatura(self):
        produtivos = {
            EventCategory.PRODUCTION,
            EventCategory.SETUP,
            EventCategory.ACTIVITY_WITHOUT_OP,
        }
        for categoria in EventCategory:
            self.assertEqual(
                ManufacturingRules.is_productive(categoria),
                categoria in produtivos,
                categoria.value,
            )

    def test_parada_manual_e_nao_programada_e_automatica_e_programada(self):
        self.assertFalse(ManufacturingRules.manual_stop_is_planned())
        self.assertTrue(ManufacturingRules.automatic_stop_is_planned())


class GoodQuantityFlowTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        task = self.db.inserir_tarefa("T-REGRA-BOAS")
        self.db.inserir_op_na_tarefa(task, "OP-REGRA-BOAS", "P1", "Dobra", 2)
        self.item = self.db.enfileirar_apontamento_operacional(
            "OP-REGRA-BOAS",
            "P1",
            task,
            "Dobra",
            "1303",
            "OPERADOR",
            quantidade=2,
            data_entrada=datetime(2026, 8, 19, 16, 0),
            operacao={"id": 1, "numero_operacao": "20", "produto_codigo": "P1"},
        )
        self.db.transicionar_apontamento_operador(
            self.item["id"],
            "producao",
            "OPERADOR",
            data_hora=datetime(2026, 8, 19, 16, 1),
        )

    def test_refugo_reduz_saldo_e_pode_atender_op_sem_virar_peca_boa(self):
        result = self.db.transicionar_apontamento_operador(
            self.item["id"],
            "finalizado",
            "OPERADOR",
            quantidade_boa=0,
            quantidade_refugo=2,
            data_hora=datetime(2026, 8, 19, 16, 20),
        )
        self.assertFalse(result["finalizacao_parcial"])
        self.assertEqual(result["status"], "Finalizado")
        self.assertEqual(result["quantidade_boa"], 0)
        self.assertEqual(result["quantidade_refugo"], 2)
        self.assertEqual(result["saldo_restante"], 0)


class ShiftBoundaryTests(unittest.TestCase):
    def _open_appointment(self, start):
        db = FakeDatabase()
        task = db.inserir_tarefa("T-TURNO")
        db.inserir_op_na_tarefa(task, "OP-TURNO", "P1", "Dobra", 5)
        item = db.enfileirar_apontamento_operacional(
            "OP-TURNO",
            "P1",
            task,
            "Dobra",
            "1303",
            "OPERADOR",
            quantidade=5,
            data_entrada=start,
            operacao={"id": 5, "numero_operacao": "20", "produto_codigo": "P1"},
        )
        db.transicionar_apontamento_operador(
            item["id"],
            "producao",
            "OPERADOR",
            data_hora=start,
        )
        return db, item

    def test_1730_interrompe_sem_quantidade_e_e_idempotente(self):
        db, item = self._open_appointment(datetime(2026, 8, 19, 17, 0))
        service = ShiftBoundaryService(db)

        first = service.apply_due(datetime(2026, 8, 19, 17, 31))
        second = service.apply_due(datetime(2026, 8, 19, 17, 32))

        self.assertEqual(first["count"], 1)
        self.assertEqual(second["count"], 0)
        row = db.buscar_apontamento_operacional(item["id"])
        self.assertEqual(row["status"], "Parada")
        self.assertEqual(row["quantidade_boa"], 0)
        self.assertEqual(row["quantidade_refugo"], 0)

        events = db.listar_eventos_apontamento_operador(item["id"])
        shift_events = [e for e in events if e.get("tipo_interrupcao") == "fim_turno"]
        self.assertEqual(len(shift_events), 1)
        self.assertEqual(shift_events[0]["data_hora"], datetime(2026, 8, 19, 17, 30))
        self.assertTrue(shift_events[0]["interrupcao_programada"])
        self.assertTrue(shift_events[0]["origem_automatica"])
        self.assertEqual(shift_events[0]["quantidade_boa"], 0)
        self.assertEqual(shift_events[0]["quantidade_refugo"], 0)
        self.assertEqual(db.history[-1]["quantidade"], 0)
        self.assertEqual(db.quantity_events, [])

    def test_timeline_nao_conta_noite_como_parada(self):
        events = [
            {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 17, 0)},
            {
                "id": 2,
                "estado": "fora_turno",
                "data_hora": datetime(2026, 8, 19, 17, 30),
                "interrupcao_programada": True,
                "origem_automatica": True,
                "tipo_interrupcao": "fim_turno",
            },
            {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 20, 7, 0)},
        ]
        timeline = build_operator_timeline(
            events,
            start=datetime(2026, 8, 19, 17, 0),
            end=datetime(2026, 8, 20, 8, 0),
        )
        self.assertEqual(timeline.seconds(EventCategory.PRODUCTION), 90 * 60)
        self.assertEqual(timeline.seconds(EventCategory.DOWNTIME), 0)
        self.assertEqual(timeline.seconds(EventCategory.OUT_OF_SHIFT), 13.5 * 3600)
        outside = next(
            segment for segment in timeline.segments
            if segment.category == EventCategory.OUT_OF_SHIFT
        )
        self.assertTrue(outside.planned)
        self.assertTrue(outside.automatic)
        self.assertEqual(outside.interruption_type, "fim_turno")

    def test_parada_manual_antes_do_limite_e_cortada_em_1730(self):
        db, item = self._open_appointment(datetime(2026, 8, 19, 17, 0))
        db.transicionar_apontamento_operador(
            item["id"],
            "parada",
            "OPERADOR",
            motivo="Aguardando material",
            data_hora=datetime(2026, 8, 19, 17, 20),
        )
        ShiftBoundaryService(db).apply_due(datetime(2026, 8, 19, 17, 31))
        events = db.listar_eventos_apontamento_operador(item["id"])
        timeline = build_operator_timeline(
            events,
            start=datetime(2026, 8, 19, 17, 0),
            end=datetime(2026, 8, 19, 18, 0),
        )
        self.assertEqual(timeline.seconds(EventCategory.PRODUCTION), 20 * 60)
        self.assertEqual(timeline.seconds(EventCategory.DOWNTIME), 10 * 60)
        self.assertEqual(timeline.seconds(EventCategory.OUT_OF_SHIFT), 30 * 60)
        row = db.buscar_apontamento_operacional(item["id"])
        # O corte temporal não apaga a causa da parada manual vigente.
        self.assertEqual(row["motivo_parada"], "Aguardando material")


if __name__ == "__main__":
    unittest.main()
