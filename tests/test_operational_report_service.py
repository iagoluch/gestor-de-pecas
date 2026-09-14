import unittest
from datetime import datetime

from mes.services.operational_reports import MOVEMENT_TYPE, OperationalReportService


class FakeReportDb:
    def __init__(self):
        self.op_count_queries = 0
        self.op_detail_queries = 0
        self.tasks_by_id = {
            1: {
                "id": 1,
                "codigo_tarefa": "T100",
                "material": "Aco",
                "status": "Despachado",
                "data_inicio_destaque": "2026-07-01 07:00:00",
                "data_finalizacao": "2026-07-01 10:00:00",
                "data_despacho": "2026-07-01 11:00:00",
            }
        }
        self.history = [
            {
                "op": "T100",
                "tipo": MOVEMENT_TYPE,
                "setor": "Destaque",
                "quantidade": 0,
                "operador": "IAGO",
                "data_hora": "2026-07-01 07:00:00",
                "peca": "",
                "tarefa_id": 1,
            },
            {
                "op": "OP1",
                "tipo": MOVEMENT_TYPE,
                "setor": "Dobra",
                "quantidade": 1,
                "operador": "IAGO",
                "data_hora": "2026-07-01 08:00:00",
                "peca": "Peca A",
                "tarefa_id": 1,
            },
            {
                "op": "OP1",
                "tipo": MOVEMENT_TYPE,
                "setor": "Usinagem",
                "quantidade": 1,
                "operador": "IAGO",
                "data_hora": "2026-07-01 10:00:00",
                "peca": "Peca A",
                "tarefa_id": 1,
            },
        ]
        self.apontamentos = [
            {
                "id": 1,
                "op": "OP1",
                "peca": "Peca A",
                "tarefa_id": 1,
                "tipo_setor": "Dobra",
                "maquina": "1303",
                "status": "Finalizado",
                "data_inicio": "2026-07-01 08:00:00",
                "data_fim": "2026-07-01 10:00:00",
                "setor_destino": "Almoxarifado",
            },
            {
                "id": 2,
                "op": "OP2",
                "peca": "Peca B",
                "tarefa_id": 1,
                "tipo_setor": "Dobra",
                "maquina": "2204",
                "status": "Em processo",
                "data_inicio": "2026-07-01 11:00:00",
                "data_fim": None,
                "setor_destino": None,
            },
        ]

    def buscar_tarefa_por_id(self, tarefa_id):
        return self.tasks_by_id.get(tarefa_id)

    def obter_historico_completo(self, periodo_inicio=None, periodo_fim=None, setor=None, operador=None, tipo=None, search=None):
        if tipo:
            return [row for row in self.history if row["tipo"] == tipo]
        return list(self.history)

    def get_tasks(self, status_filter=None, search=None):
        return list(self.tasks_by_id.values())

    def get_ops_for_task(self, tarefa_id):
        self.op_detail_queries += 1
        return [{"codigo_op": "OP1"}, {"codigo_op": "OP2"}]

    def get_op_counts_by_task(self, tarefa_ids=None):
        self.op_count_queries += 1
        ids = set(tarefa_ids or [])
        return {tarefa_id: 2 for tarefa_id in ids}

    def listar_apontamentos_operacionais_periodo(self, tipo_setor, inicio, fim):
        return [item for item in self.apontamentos if item["tipo_setor"] == tipo_setor]

    def buscar_movimentacoes_periodo(self, inicio, fim):
        return [
            row for row in self.history
            if row["tipo"] == MOVEMENT_TYPE
            and not row["op"].startswith("T")
            and inicio <= datetime.strptime(row["data_hora"], "%Y-%m-%d %H:%M:%S") <= fim
        ]


class PeriodDb:
    def buscar_movimentacoes_periodo(self, inicio, fim):
        rows = (
            {"op": "OP1", "tipo": MOVEMENT_TYPE, "setor": "Dobra", "data_hora": datetime(2026, 7, 1, 9), "peca": "Peca A"},
            {"op": "T100", "tipo": MOVEMENT_TYPE, "setor": "Destaque", "data_hora": datetime(2026, 7, 1, 8), "peca": ""},
            {"op": "OP2", "tipo": "Correcao", "setor": "Dobra", "data_hora": datetime(2026, 7, 1, 7), "peca": "Peca B"},
        )
        return [row for row in rows if row["tipo"] == MOVEMENT_TYPE and not row["op"].startswith("T") and inicio <= row["data_hora"] <= fim]


class DashboardDb:
    def __init__(self):
        self.history = [
            {"id": 1, "op": "OP1", "tipo": MOVEMENT_TYPE, "setor": "Dobra", "quantidade": 2, "data_hora": "2026-07-01 08:00:00"},
            {"id": 2, "op": "OP1", "tipo": MOVEMENT_TYPE, "setor": "Usinagem", "quantidade": 2, "data_hora": "2026-07-01 10:00:00"},
            {"id": 3, "op": "OP2", "tipo": MOVEMENT_TYPE, "setor": "Dobra", "quantidade": 3, "data_hora": "2026-07-01 08:00:00"},
            {"id": 4, "op": "OP2", "tipo": MOVEMENT_TYPE, "setor": "Almoxarifado", "quantidade": 3, "data_hora": "2026-07-01 11:00:00"},
            {"id": 5, "op": "T100", "tipo": MOVEMENT_TYPE, "setor": "Destaque", "quantidade": 0, "data_hora": "2026-07-01 07:00:00"},
        ]

    def obter_historico_completo(self, **_filters):
        return list(reversed(self.history))

    def get_current_ops(self, **_filters):
        return [dict(self.history[1]), dict(self.history[3])]


class OperationalReportServiceTests(unittest.TestCase):
    def _service(self, db=None):
        return OperationalReportService(
            db or FakeReportDb(),
            status_limits=((4, "Normal"), (8, "Atencao"), (24, "Atrasado"), (None, "Critico")),
            now_func=lambda: datetime(2026, 7, 1, 12, 0, 0),
        )

    def test_calcula_tempos_mes_sem_depender_da_interface(self):
        db = FakeReportDb()
        service = self._service(db)

        resultado = service.calcular_relatorio_tempos_mes(
            datetime(2026, 7, 1, 0, 0, 0),
            datetime(2026, 7, 1, 23, 59, 59),
        )

        self.assertEqual(resultado["indicadores"]["tarefas"], 1)
        self.assertEqual(resultado["indicadores"]["lead_medio"], "4h00min")
        self.assertEqual(resultado["indicadores"]["destaque_medio"], "3h00min")
        self.assertEqual(resultado["indicadores"]["pallet_medio"], "1h00min")
        self.assertEqual(resultado["indicadores"]["tempo_medio_etapa"], "2h00min")
        self.assertEqual(resultado["indicadores"]["ops"], 1)
        self.assertEqual(resultado["ops"][0]["op"], "OP1")
        self.assertEqual(resultado["ops"][0]["tempo_total"], "4h00min")
        self.assertEqual(resultado["ops"][0]["tempo_aberto"], "2h00min")
        self.assertEqual(resultado["ops"][0]["status_tempo"], "Normal")
        self.assertEqual(resultado["tarefas"][0]["qtd_ops"], 2)
        self.assertEqual(resultado["tarefas"][0]["tempo_destaque"], "3h00min")
        self.assertEqual(resultado["tarefas"][0]["tempo_pallet"], "1h00min")
        self.assertEqual(db.op_count_queries, 1)
        self.assertEqual(db.op_detail_queries, 0)

    def test_exportacao_respeita_filtros_texto_setor_e_status(self):
        service = self._service()
        resultado = service.calcular_relatorio_tempos_mes(
            datetime(2026, 7, 1, 0, 0, 0),
            datetime(2026, 7, 1, 23, 59, 59),
        )

        linhas = service.montar_linhas_exportacao_tempos_mes(
            resultado,
            {
                "resumo": False,
                "etapas": True,
                "tarefas": True,
                "ops": True,
                "texto": "OP1",
                "setor": "usinagem",
                "status": "Normal",
            },
        )

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["tipo"], "Tempo por OP")
        self.assertEqual(linhas[0]["item"], "OP1")
        self.assertEqual(linhas[0]["observacao"], "Setor atual: Usinagem")

    def test_calcula_dobra_por_inicio_e_finalizacao_explicitos(self):
        service = self._service()

        resultado = service.calcular_relatorio_tempos_mes(
            datetime(2026, 7, 1, 0, 0, 0),
            datetime(2026, 7, 1, 23, 59, 59),
            "Dobra",
        )

        self.assertEqual(resultado["visao"], "Dobra")
        self.assertEqual(resultado["indicadores"]["tarefas"], 2)
        self.assertEqual(resultado["indicadores"]["lead_medio"], "1h30min")
        self.assertEqual(resultado["indicadores"]["destaque_medio"], "3h00min")
        self.assertEqual(resultado["indicadores"]["pallet_medio"], "2h00min")
        self.assertEqual(resultado["indicadores"]["ops"], 2)
        self.assertEqual(resultado["indicadores"]["ops_criticas"], 1)
        self.assertEqual({row["setor"] for row in resultado["etapas"]}, {"1303", "2204"})
        self.assertEqual({row["status_processo"] for row in resultado["ops"]}, {"Finalizado", "Em processo"})

    def test_calcula_serra_por_maquina_com_status_em_processo(self):
        db = FakeReportDb()
        db.apontamentos.append(
            {
                "id": 3,
                "op": "OP-SERRA",
                "peca": "Perfil",
                "tarefa_id": 1,
                "tipo_setor": "Serra",
                "maquina": "SFG-330",
                "status": "Em processo",
                "data_inicio": "2026-07-01 11:30:00",
                "data_fim": None,
                "setor_destino": None,
            }
        )
        service = self._service(db)

        resultado = service.calcular_relatorio_tempos_mes(
            datetime(2026, 7, 1, 0, 0, 0),
            datetime(2026, 7, 1, 23, 59, 59),
            "Serra",
        )

        self.assertEqual(resultado["visao"], "Serra")
        self.assertEqual(resultado["indicadores"]["tarefas"], 1)
        self.assertEqual(resultado["indicadores"]["lead_medio"], "30min")
        self.assertEqual(resultado["indicadores"]["ops_criticas"], 1)
        self.assertEqual(resultado["etapas"][0]["setor"], "SFG-330")
        self.assertEqual(resultado["ops"][0]["status_processo"], "Em processo")

    def test_busca_movimentacoes_periodo_preserva_recorte_operacional(self):
        service = self._service(PeriodDb())

        rows = service.buscar_movimentacoes_periodo(
            datetime(2026, 7, 1, 0, 0, 0),
            datetime(2026, 7, 1, 23, 59, 59),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["op"], "OP1")

    def test_dashboard_movimentacoes_consolida_pecas_tempos_e_transicoes(self):
        service = self._service(DashboardDb())

        resultado = service.calcular_dashboard_movimentacoes(7)

        self.assertEqual(resultado["kpis"]["ops_fluxo"], 2)
        self.assertEqual(resultado["kpis"]["pecas_fluxo"], 5)
        self.assertEqual(resultado["kpis"]["movimentos_7d"], 4)
        self.assertEqual(
            resultado["pecas_setor"],
            [{"setor": "Almoxarifado", "quantidade": 3}, {"setor": "Usinagem", "quantidade": 2}],
        )
        dobra = next(row for row in resultado["tempos_setor"] if row["setor"] == "Dobra")
        self.assertEqual(dobra["passagens"], 2)
        self.assertEqual(dobra["media_horas"], 2.5)
        fluxos = {row["fluxo"]: row for row in resultado["transicoes"]}
        self.assertEqual(fluxos["Dobra → Usinagem"]["media_horas"], 2.0)
        self.assertEqual(fluxos["Dobra → Almoxarifado"]["media_horas"], 3.0)


if __name__ == "__main__":
    unittest.main()
