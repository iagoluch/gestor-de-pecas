import unittest
from datetime import datetime

from mes.services.production import ProductionService


class FakeProductionDb:
    def __init__(self):
        self.tarefas = {}
        self.ops = {}
        self.catalog_ops = {}
        self.historico = []
        self.eventos = []
        self.eventos_destaque = []
        self.status_updates = []
        self.despachos = []
        self.op_updates = []
        self.despacho_result = True
        self.transition_result = True
        self.correction_result = True

    def buscar_tarefa_por_codigo(self, codigo):
        return self.tarefas.get(str(codigo).strip().upper())

    def atualizar_tarefa_status(self, tarefa_id, status):
        self.status_updates.append((tarefa_id, status))
        for tarefa in self.tarefas.values():
            if tarefa["id"] == tarefa_id:
                tarefa["status"] = status

    def inserir_historico(self, *args, **kwargs):
        self.historico.append({"args": args, "kwargs": kwargs})

    def registrar_transicao_tarefa(
        self, tarefa_id, status_esperado, novo_status, operador, setor, motivo
    ):
        if not self.transition_result:
            return False
        tarefa = next((item for item in self.tarefas.values() if item["id"] == tarefa_id), None)
        atual = tarefa.get("status") if tarefa else None
        if not tarefa or atual != status_esperado:
            return False
        self.atualizar_tarefa_status(tarefa_id, novo_status)
        self.inserir_historico(
            op=tarefa["codigo_tarefa"], tipo="Movimentação", setor=setor, motivo=motivo,
            quantidade=0, operador=operador, peca="", tarefa_id=tarefa_id,
        )
        return True

    def despachar_tarefa(
        self, tarefa_id, operador, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None
    ):
        self.despachos.append((tarefa_id, operador, maquinas_dobra, maquinas_usinagem, maquinas_serra))
        for tarefa in self.tarefas.values():
            if tarefa["id"] == tarefa_id:
                tarefa["status"] = "Despachado"
        return self.despacho_result

    def atualizar_op(self, op_id, novo_setor, nova_quantidade):
        self.op_updates.append((op_id, novo_setor, nova_quantidade))

    def corrigir_op_com_historico(
        self, op_id, codigo_op, setor_esperado, quantidade_esperada,
        novo_setor, nova_quantidade, operador, tarefa_id,
    ):
        if not self.correction_result:
            return False
        self.atualizar_op(op_id, novo_setor, nova_quantidade)
        self.inserir_historico(
            op=codigo_op,
            tipo="Correção",
            setor=novo_setor,
            motivo=f"Ajuste: {setor_esperado}->{novo_setor}, qtd {quantidade_esperada}->{nova_quantidade}",
            quantidade=nova_quantidade - quantidade_esperada,
            operador=operador,
            peca="",
            tarefa_id=tarefa_id,
        )
        return True

    def buscar_op_por_codigo(self, codigo_op):
        return self.ops.get(str(codigo_op).strip().upper())

    def buscar_op_catalogo(self, codigo_op):
        return self.catalog_ops.get(str(codigo_op).strip().upper())

    def registrar_evento_sistema(self, **kwargs):
        self.eventos.append(kwargs)

    def listar_eventos_destaque(self, tarefa_id):
        return [dict(item) for item in self.eventos_destaque if item.get("tarefa_id") == tarefa_id]

class ProductionServiceTests(unittest.TestCase):
    def test_tempos_destaque_separam_execucao_e_parada_no_backend(self):
        db = FakeProductionDb()
        db.eventos_destaque = [
            {"id": 1, "tarefa_id": 10, "estado": "inicio", "data_hora": datetime(2026, 8, 20, 8, 0)},
            {"id": 2, "tarefa_id": 10, "estado": "parada", "data_hora": datetime(2026, 8, 20, 8, 10)},
            {"id": 3, "tarefa_id": 10, "estado": "retomada", "data_hora": datetime(2026, 8, 20, 8, 15)},
        ]

        result = ProductionService(db, operador="IAGO").tempos_destaque(
            10,
            agora=datetime(2026, 8, 20, 8, 25),
        )

        self.assertEqual(result["execution_seconds"], 20 * 60)
        self.assertEqual(result["stopped_seconds"], 5 * 60)
        self.assertEqual(result["current_mode"], "execucao")
        self.assertEqual(result["state_since"], datetime(2026, 8, 20, 8, 15))

    def test_registrar_destacando_atualiza_status_e_historico(self):
        db = FakeProductionDb()
        db.tarefas["T10"] = {"id": 10, "codigo_tarefa": "T10", "status": None}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_destacando(10, "t10")

        self.assertTrue(result.ok)
        self.assertEqual(db.status_updates, [(10, "Destacando")])
        self.assertEqual(db.historico[0]["kwargs"]["op"], "T10")
        self.assertEqual(db.eventos[0]["tipo"], "tarefa_destacando")

    def test_registrar_destacando_bloqueia_status_existente(self):
        db = FakeProductionDb()
        db.tarefas["T20"] = {"id": 20, "codigo_tarefa": "T20", "status": "Despachado"}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_destacando(20, "t20")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "status_existente")
        self.assertEqual(db.status_updates, [])

    def test_registrar_despachado_exige_finalizado(self):
        db = FakeProductionDb()
        db.tarefas["T30"] = {"id": 30, "codigo_tarefa": "T30", "status": None}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_despachado(30, "t30")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "status_invalido")
        self.assertEqual(db.despachos, [])

    def test_registrar_finalizado_exige_destacando(self):
        db = FakeProductionDb()
        db.tarefas["T35"] = {"id": 35, "codigo_tarefa": "T35", "status": None}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_finalizado(35, "t35")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "status_invalido")
        self.assertEqual(db.status_updates, [])

    def test_registrar_finalizado_atualiza_status_e_historico(self):
        db = FakeProductionDb()
        db.tarefas["T36"] = {"id": 36, "codigo_tarefa": "T36", "status": "Destacando"}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_finalizado(36, "t36")

        self.assertTrue(result.ok)
        self.assertEqual(db.status_updates, [(36, "Finalizado")])
        self.assertEqual(db.historico[0]["kwargs"]["setor"], "Organização de Pallets")
        self.assertEqual(db.eventos[0]["tipo"], "tarefa_finalizada")

    def test_transicao_concorrente_nao_confirma_inicio_ou_finalizacao(self):
        for status, method_name in ((None, "registrar_destacando"), ("Destacando", "registrar_finalizado")):
            with self.subTest(status=status):
                db = FakeProductionDb()
                db.tarefas["T37"] = {"id": 37, "codigo_tarefa": "T37", "status": status}
                db.transition_result = False
                result = getattr(ProductionService(db, operador="IAGO"), method_name)(37, "T37")
                self.assertFalse(result.ok)
                self.assertEqual(result.code, "status_alterado")
                self.assertEqual(db.historico, [])
                self.assertEqual(db.eventos, [])

    def test_registrar_despachado_chama_banco_com_maquinas(self):
        db = FakeProductionDb()
        db.tarefas["T40"] = {"id": 40, "codigo_tarefa": "T40", "status": "Finalizado"}
        service = ProductionService(
            db,
            operador="IAGO",
            maquinas_dobra=["Gasparini"],
            maquinas_usinagem=["Romi"],
            maquinas_serra=["SFG-330"],
        )

        result = service.registrar_despachado(40, "t40")

        self.assertTrue(result.ok)
        self.assertEqual(db.despachos[0], (40, "IAGO", ["Gasparini"], ["Romi"], ["SFG-330"]))
        self.assertEqual(db.eventos[0]["tipo"], "tarefa_despachada")

    def test_registrar_despachado_nao_confirma_quando_transicao_concorrente_falha(self):
        db = FakeProductionDb()
        db.tarefas["T41"] = {"id": 41, "codigo_tarefa": "T41", "status": "Finalizado"}
        db.despacho_result = False
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_despachado(41, "t41")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "status_alterado")
        self.assertEqual(db.eventos, [])

    def test_corrigir_op_valida_quantidade(self):
        db = FakeProductionDb()
        service = ProductionService(db, operador="IAGO")

        result = service.corrigir_op(1, "OP1", "Dobra", 1, "Usinagem", "0", 10)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "quantidade_invalida")
        self.assertEqual(db.op_updates, [])

    def test_corrigir_op_atualiza_e_registra_correcao(self):
        db = FakeProductionDb()
        service = ProductionService(db, operador="IAGO")

        result = service.corrigir_op(1, "OP1", "Dobra", 2, "Usinagem", "3", 10)

        self.assertTrue(result.ok)
        self.assertEqual(db.op_updates, [(1, "Usinagem", 3)])
        self.assertEqual(db.historico[0]["kwargs"]["tipo"], "Correção")
        self.assertEqual(db.eventos[0]["tipo"], "op_corrigida")

    def test_corrigir_op_nao_confirma_quando_dados_foram_alterados(self):
        db = FakeProductionDb()
        db.correction_result = False
        service = ProductionService(db, operador="IAGO")

        result = service.corrigir_op(1, "OP1", "Dobra", 2, "Usinagem", "3", 10)

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "dados_alterados")
        self.assertEqual(db.historico, [])
        self.assertEqual(db.eventos, [])

    def test_registrar_movimentacao_vincula_peca_quando_op_existe(self):
        db = FakeProductionDb()
        db.ops["OP10"] = {"tarefa_id": 7, "id_peca": "Peca A"}
        service = ProductionService(db, operador="IAGO")

        result = service.registrar_movimentacao(" op10 ", "Gasparini")

        self.assertTrue(result.ok)
        self.assertEqual(result.data["tarefa_id"], 7)
        self.assertEqual(db.historico[0]["args"], ("OP10", "Movimentação", "Gasparini", "", 1, "IAGO", "Peca A", 7))
        self.assertEqual(db.eventos[0]["tipo"], "op_movimentada")

if __name__ == "__main__":
    unittest.main()
