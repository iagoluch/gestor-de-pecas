from datetime import datetime
import unittest

from mes.contracts import AnalyticsFilter
from mes.services.andon import AndonService
from mes.services.frontend_facade import FrontendBackendFacade


def metric(value):
    return {"value": value, "availability": "disponivel", "unit": "%", "reason": None}


class AndonRepositoryFake:
    def __init__(self):
        self.resources = [
            {"codigo": "LASER1", "nome": "Laser Ensis 3015", "tipo_setor": "Corte", "ordem": 1},
            {"codigo": "PLASMA", "nome": "Plasma TerraBlade 4", "tipo_setor": "Corte", "ordem": 2},
            {"codigo": "DOBRA1", "nome": "Gasparini", "tipo_setor": "Dobra", "ordem": 1},
            {"codigo": "CNC-01", "nome": "Romi D 1000", "tipo_setor": "Usinagem", "ordem": 1},
            {"codigo": "SERRA1", "nome": "S4220", "tipo_setor": "Serra", "ordem": 1},
            {"codigo": "SOLDA1", "nome": "Solda 01", "tipo_setor": "Solda Aço", "ordem": 1},
            {"codigo": "SOLDA2", "nome": "Solda 02", "tipo_setor": "Solda Aço", "ordem": 2},
            {"codigo": "PINT.L", "nome": "Cabine 01", "tipo_setor": "Pintura", "ordem": 1},
            {"codigo": "INATIVO", "nome": "Recurso apenas cadastrado", "tipo_setor": "Solda Aço", "ordem": 99},
            {"codigo": "FILA", "nome": "Recurso em fila", "tipo_setor": "Solda Aço", "ordem": 100},
        ]
        self.highlights = []
        self.active_cuts = []

    def listar_recursos_pcfactory(self):
        return list(self.resources)

    def listar_destaques_ativos_andon(self):
        return list(self.highlights)

    def listar_cortes_ativos_andon(self):
        return list(self.active_cuts)


class AndonActiveResourcesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 4, 16, 30)
        self.filters = AnalyticsFilter(datetime(2026, 9, 4), self.now)
        self.service = AndonService(AndonRepositoryFake())
        self.states = [
            {"recurso": "LASER1", "setor": "Corte", "categoria": "producao", "inicio": self.now, "ops_ativas": [{"op": "1001", "produto": "LASER-P"}]},
            {"recurso": "PLASMA", "setor": "Corte", "categoria": "setup", "inicio": self.now},
            {"recurso": "DOBRA1", "setor": "Dobra", "categoria": "parada", "codigo_status": "0029", "motivo": "0029 - Falta de material", "inicio": self.now},
            {"recurso": "CNC-01", "setor": "Usinagem", "categoria": "retrabalho", "inicio": self.now, "ops_ativas": [{"op": "1002", "produto": "CNC-P"}]},
            {"recurso": "SERRA1", "setor": "Serra", "categoria": "producao", "inicio": self.now, "ops_ativas": [{"op": "1003", "produto": "SERRA-P"}]},
            {"recurso": "SOLDA1", "setor": "Solda Aço", "categoria": "atividade_sem_op", "tipo_atividade": "diaria", "descricao_atividade": "Limpeza do posto", "inicio": self.now},
            {"recurso": "SOLDA2", "setor": "Solda Aço", "categoria": "atividade_sem_op", "descricao_atividade": "Apoio à montagem", "inicio": self.now},
            {"recurso": "PINT.L", "setor": "Pintura", "categoria": "producao", "inicio": self.now, "ops_ativas": [{"op": "1004", "produto": "PINT-P"}]},
            {"recurso": "FILA", "setor": "Solda Aço", "categoria": "fila", "inicio": self.now},
        ]
        self.kpis = []
        for index, code in enumerate(("LASER1", "PLASMA", "DOBRA1", "CNC-01", "SERRA1", "SOLDA1", "SOLDA2", "PINT.L"), 1):
            self.kpis.append({
                "resource": code,
                "metrics": {
                    "oee": metric(index * 10 + 1),
                    "availability": metric(index * 10 + 2),
                    "performance": metric(index * 10 + 3),
                    "ftt": metric(index * 10 + 4),
                },
            })

    def snapshot(self, states=None):
        return self.service.build_snapshot(
            self.filters,
            operational={"agora": self.now, "resources": self.states if states is None else states},
            overview={"kpis": {}, "resource_kpis": self.kpis},
        )

    @staticmethod
    def resources(snapshot):
        return {
            resource["code"]: resource
            for sector in snapshot["sectors"]
            for resource in sector["resources"]
        }

    def test_somente_estados_operacionais_ativos_aparecem(self):
        snapshot = self.snapshot()
        resources = self.resources(snapshot)

        self.assertEqual(snapshot["resource_count"], 8)
        self.assertNotIn("INATIVO", resources)
        self.assertNotIn("FILA", resources)
        self.assertEqual(resources["DOBRA1"]["state"]["display_label"], "Falta de material")
        self.assertEqual(resources["SOLDA1"]["state"]["display_label"], "Atividade diária")
        self.assertEqual(resources["SOLDA2"]["state"]["display_label"], "Atividade s/OP")
        self.assertIsNone(resources["SOLDA1"]["operation"])
        self.assertIsNone(resources["SOLDA2"]["operation"])

    def test_finalizacao_remove_recurso_quando_nao_resta_estado_ativo(self):
        before = self.snapshot()
        after = self.snapshot([row for row in self.states if row["recurso"] != "LASER1"])

        self.assertIn("LASER1", self.resources(before))
        self.assertNotIn("LASER1", self.resources(after))
        self.assertEqual(after["resource_count"], before["resource_count"] - 1)

    def test_alias_do_posto_e_codigo_do_catalogo_formam_um_so_recurso(self):
        states = [
            {
                "recurso": "LASER1", "setor": "Corte", "categoria": "fila",
                "sem_demanda": True, "inicio": self.now,
            },
            {
                "recurso": "Laser Ensis 3015", "setor": "Corte", "categoria": "parada",
                "codigo_status": "0009", "motivo": "0009 - Pausa para café",
                "classificacao_parada": "planejada", "inicio": self.now,
            },
        ]

        resources = self.resources(self.snapshot(states))

        self.assertEqual(list(resources), ["LASER1"])
        self.assertEqual(resources["LASER1"]["state"]["category"], "parada")
        self.assertEqual(resources["LASER1"]["state"]["stop_classification"], "planejada")

    def test_paineis_e_grupos_sao_estaveis_e_canonicos(self):
        snapshot = self.snapshot()
        self.assertEqual(
            [sector["name"] for sector in snapshot["sectors"]],
            ["Corte", "Caldeiraria", "Solda", "Pintura"],
        )
        groups = {sector["name"]: [group["name"] for group in sector["groups"]] for sector in snapshot["sectors"]}
        self.assertEqual(groups["Corte"], ["Laser", "Plasma"])
        self.assertEqual(groups["Caldeiraria"], ["Dobra", "Usinagem", "Serra"])

    def test_montagem_e_setor_sem_classificacao_ativa_nao_sao_descartados(self):
        self.service.db.resources.extend([
            {"codigo": "MONT-01", "nome": "Posto de montagem", "tipo_setor": "Montagem", "ordem": 1},
            {"codigo": "SEM-SETOR", "nome": "Recurso pendente", "tipo_setor": None, "ordem": 2},
        ])

        snapshot = self.snapshot(self.states + [
            {"recurso": "MONT-01", "setor": "Montagem", "categoria": "producao", "inicio": self.now},
            {"recurso": "SEM-SETOR", "setor": "Setor pendente", "categoria": "parada", "inicio": self.now},
        ])
        panels = {sector["name"]: sector for sector in snapshot["sectors"]}

        self.assertEqual(panels["Montagem"]["groups"][0]["name"], "Montagem")
        self.assertEqual(panels["Montagem"]["resources"][0]["code"], "MONT-01")
        self.assertEqual(panels["Não classificado"]["groups"][0]["name"], "Setor pendente")
        self.assertEqual(panels["Não classificado"]["resources"][0]["code"], "SEM-SETOR")

    def test_oee_disponibilidade_performance_e_ftt_permanecem_por_recurso(self):
        resources = self.resources(self.snapshot())
        for index, code in enumerate(("LASER1", "PLASMA", "DOBRA1", "CNC-01", "SERRA1", "SOLDA1", "SOLDA2", "PINT.L"), 1):
            self.assertEqual(resources[code]["metrics"]["oee"]["value"], index * 10 + 1)
            self.assertEqual(resources[code]["metrics"]["availability"]["value"], index * 10 + 2)
            self.assertEqual(resources[code]["metrics"]["performance"]["value"], index * 10 + 3)
            self.assertEqual(resources[code]["metrics"]["ftt"]["value"], index * 10 + 4)

    def test_destaque_ativo_aparece_dentro_de_corte_sem_inventar_oee(self):
        self.service.db.highlights = [{
            "tarefa_id": 91,
            "codigo_tarefa": "T-901",
            "plano_hash": "hash-901",
            "estado": "inicio",
            "operador": "Destacador",
            "data_hora": self.now,
            "programa": "P-17",
            "nome_chapa": "CHAPA 6MM",
            "ops": [{
                "codigo_op": "10901",
                "produto_codigo": "PROD-901",
                "produto_descricao": "Suporte lateral",
            }],
        }]

        snapshot = self.snapshot()
        corte = next(sector for sector in snapshot["sectors"] if sector["name"] == "Corte")
        groups = {group["name"]: group for group in corte["groups"]}
        destaque = groups["Destaque"]["resources"][0]

        self.assertEqual(destaque["code"], "DESTAQUE")
        self.assertEqual(destaque["state"]["category"], "producao")
        self.assertEqual(destaque["operation"]["op"], "10901")
        self.assertIsNone(destaque["metrics"]["oee"]["value"])

    def test_destaque_sem_evento_ativo_nao_aparece(self):
        self.service.db.highlights = [{
            "tarefa_id": 91,
            "codigo_tarefa": "T-901",
            "estado": "fim",
            "data_hora": self.now,
            "ops": [],
        }]
        snapshot = self.snapshot()
        corte = next(sector for sector in snapshot["sectors"] if sector["name"] == "Corte")
        self.assertNotIn("Destaque", [group["name"] for group in corte["groups"]])

    def test_apontamento_corte_publica_laser_sem_estado_operacional_paralelo(self):
        self.service.db.active_cuts = [{
            "maquina": "Laser Ensis 3015",
            "codigo_tarefa": "8478",
            "programa": "N-8478",
            "nome_chapa": "CH-1",
            "repeticao": 1,
            "operador_inicio": "Operador Corte",
            "data_inicio": self.now,
        }]
        states = [row for row in self.states if row["recurso"] != "LASER1"]

        laser = self.resources(self.snapshot(states))["LASER1"]

        self.assertEqual(laser["state"]["category"], "producao")
        self.assertEqual(laser["state"]["source"], "apontamentos_corte")
        self.assertIn("Tarefa 8478", laser["state"]["activity_description"])


class AndonNoDemandStateTests(unittest.TestCase):
    """"Sem demanda" nunca vira card no Andon.

    Decisão do usuário (16/09/2026): o quadro mostra só recurso com
    apontamento válido em execução. A decisão de "sem_demanda" continua vindo
    pronta da consulta operacional (que por sua vez pergunta ao domínio) —
    o Andon aqui só precisa provar que a esconde sempre, em qualquer
    variação de origem (OP ativa, evento manual, corte automático de fim de
    turno).
    """

    def setUp(self):
        self.now = datetime(2026, 9, 4, 19, 30)
        self.filters = AnalyticsFilter(datetime(2026, 9, 4), self.now)
        self.service = AndonService(AndonRepositoryFake())

    def snapshot(self, states):
        return self.service.build_snapshot(
            self.filters,
            operational={"agora": self.now, "resources": states},
            overview={"kpis": {}, "resource_kpis": []},
        )

    @staticmethod
    def resources(snapshot):
        return {
            resource["code"]: resource
            for sector in snapshot["sectors"]
            for resource in sector["resources"]
        }

    def _sem_demanda(self, *, source="eventos_estado_recurso", active_account=False):
        return [{
            "recurso": "DOBRA1",
            "setor": "Dobra",
            "categoria": "fora_turno",
            "inicio": self.now,
            "sem_demanda": True,
            "tem_apontamento_canonico": True,
            "classificacao_parada": "planejada",
            "cor_parada": "warning",
            "fonte": source,
            "conta_operador_ativa": active_account,
        }]

    def test_recurso_sem_demanda_de_conta_ativa_nao_vira_card(self):
        states = self._sem_demanda(source="contas_operador_ativas", active_account=True)
        self.assertNotIn("DOBRA1", self.resources(self.snapshot(states)))

    def test_recurso_sem_demanda_fisico_nao_vira_card(self):
        self.assertNotIn("DOBRA1", self.resources(self.snapshot(self._sem_demanda())))

    def test_resumo_nao_conta_sem_demanda_de_conta_ativa(self):
        summary = self.snapshot(self._sem_demanda(source="contas_operador_ativas", active_account=True))["summary"]
        self.assertEqual(summary["no_demand"], 0)

    def test_fora_de_turno_sem_a_marca_continua_invisivel(self):
        # Sem a decisão do domínio nada muda: fora de turno segue fora do Andon.
        estados = self._sem_demanda()
        estados[0]["sem_demanda"] = False
        self.assertNotIn("DOBRA1", self.resources(self.snapshot(estados)))

    def test_sem_demanda_com_apontamento_canonico_continua_invisivel(self):
        estados = self._sem_demanda()
        estados[0]["tem_apontamento_canonico"] = True
        self.assertNotIn("DOBRA1", self.resources(self.snapshot(estados)))

    def test_recurso_ocioso_fechado_automaticamente_continua_invisivel(self):
        # `interromper_recursos_ociosos_fim_turno` fecha o estado físico de um
        # recurso que já não tinha OP nem apontamento aberto — o corte
        # automático de fim de turno continua acontecendo normalmente, só não
        # é mais exibido aqui.
        estados = self._sem_demanda()
        estados[0]["tem_apontamento_canonico"] = False
        estados[0]["tipo_interrupcao"] = "fim_turno"
        self.assertNotIn("DOBRA1", self.resources(self.snapshot(estados)))


class AccountResourceNoDemandTests(unittest.TestCase):
    def test_andon_uses_only_resources_of_active_operator_accounts(self):
        repository = AndonRepositoryFake()
        repository.listar_estados_recurso_atuais = lambda **_kwargs: []
        repository.listar_fatos_operacionais_periodo = lambda *_args, **_kwargs: []
        repository.listar_usuarios = lambda: [
            {"nivel": "estacao1aco", "ativo": True},
            {"nivel": "estacao2aco", "ativo": False},
            {"nivel": "admin", "ativo": True},
        ]
        now = datetime(2026, 9, 16, 11, 0)
        facade = FrontendBackendFacade(repository, now_func=lambda: now)
        filters = AnalyticsFilter(now, now)

        resources = facade.consulta_operacional(
            filters,
            incluir_recursos_sem_demanda_de_contas=True,
        )["resources"]
        self.assertEqual(
            [(item["recurso"], item["setor"], item["fonte"]) for item in resources],
            [("Estação 1", "Solda Aço", "contas_operador_ativas")],
        )
        self.assertEqual(
            facade.consulta_operacional(
                filters,
                somente_vinculo_operacional=True,
                incluir_recursos_sem_demanda_de_contas=True,
            )["resources"],
            [],
        )

    def test_codigo_real_e_posto_ativo_nao_geram_alias_em_card_separado(self):
        repository = AndonRepositoryFake()
        now = datetime(2026, 9, 24, 10, 45)
        repository.listar_estados_recurso_atuais = lambda **_kwargs: [
            {
                "id": 1,
                "recurso": "INSPE2",
                "tipo_setor": "Pintura",
                "categoria": "fila",
                "data_inicio": now,
                "automatico": True,
            },
            {
                "id": 2,
                "recurso": "PREP",
                "tipo_setor": "Pintura",
                "categoria": "fila",
                "data_inicio": now,
                "automatico": True,
            },
            {
                "id": 3,
                "recurso": "ROBO S",
                "tipo_setor": "Solda Robô",
                "categoria": "fila",
                "data_inicio": now,
                "automatico": True,
            },
        ]
        repository.listar_fatos_operacionais_periodo = lambda *_args, **_kwargs: []
        repository.listar_usuarios = lambda: [
            {"nivel": "operador_pintura", "ativo": True},
            {"nivel": "robo1", "ativo": True},
        ]
        repository.resources.extend([
            {
                "codigo": "INSPE2",
                "nome": "INSPEÇÃO PINTURA",
                "tipo_setor": "Pintura",
            },
            {
                "codigo": "PREP",
                "nome": "PREPARAÇÃO PINTURA",
                "tipo_setor": "Pintura",
            },
            {
                "codigo": "ROBO S",
                "nome": "SOLDA ROBO CHASSI S",
                "tipo_setor": "Solda Robô",
            },
        ])
        facade = FrontendBackendFacade(repository, now_func=lambda: now)
        resources = facade.consulta_operacional(
            AnalyticsFilter(now, now),
            incluir_recursos_sem_demanda_de_contas=True,
        )["resources"]

        selected = {
            item["recurso"]: (item["recurso_nome"], item["fonte"])
            for item in resources
            if item["recurso"] in {"INSPE2", "PREP", "ROBO S"}
        }
        self.assertEqual(
            selected,
            {
                "INSPE2": ("Inspeção Final", "eventos_estado_recurso"),
                "PREP": ("Preparação", "eventos_estado_recurso"),
                "ROBO S": ("Robô 1", "eventos_estado_recurso"),
            },
        )
        self.assertFalse(
            any(
                item["fonte"] == "contas_operador_ativas"
                and item["recurso"] in {"Inspeção Final", "Preparação", "Robô 1"}
                for item in resources
            )
        )


if __name__ == "__main__":
    unittest.main()
