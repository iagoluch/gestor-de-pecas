import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.clock import ApplicationClock
from backend.api.errors import AppError, register_error_handlers
from mes.analytics.oee import calculate_oee
from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory, ManufacturingRules
from mes.services.andon import AndonService
from mes.services.shift_boundary import ShiftBoundaryService


class ApplicationClockTests(unittest.TestCase):
    def test_relogio_virtual_avanca_continuamente_na_escala_configurada(self):
        ticks = iter((100.0, 101.5, 103.0))
        clock = ApplicationClock(
            simulation_mode=True,
            reference_time=datetime(2026, 8, 31, 11, 40),
            scale=120,
            monotonic_func=lambda: next(ticks),
        )

        self.assertEqual(clock.now(), datetime(2026, 8, 31, 11, 43))
        self.assertEqual(clock.now(), datetime(2026, 8, 31, 11, 46))

    def test_relogio_virtual_parado_preserva_referencia(self):
        clock = ApplicationClock(
            simulation_mode=True,
            reference_time=datetime(2026, 8, 31, 11, 40, 27),
            scale=0,
        )
        self.assertFalse(clock.running)
        self.assertEqual(clock.now(), datetime(2026, 8, 31, 11, 40, 27))


class BreakRepositoryFake:
    def __init__(self):
        self.started = []
        self.finished = []
        self.shift_returns = []

    def listar_apontamentos_abertos_no_limite_turno(self, _boundary):
        return []

    def interromper_apontamento_fim_turno(self, *_args, **_kwargs):
        raise AssertionError("não deveria haver apontamento de turno no cenário")

    def listar_cortes_abertos_no_limite_turno(self, _boundary):
        return []

    def interromper_corte_fim_turno(self, *_args, **_kwargs):
        raise AssertionError("não deveria haver Corte de turno no cenário")

    def iniciar_intervalo_automatico(self, moment, name, *, operador, tipo_setor=None):
        self.started.append((moment, name, operador, tipo_setor))
        return [{"id": 1, "recurso": "1303"}]

    def finalizar_intervalo_automatico(self, moment, name, *, operador, tipo_setor=None):
        self.finished.append((moment, name, operador, tipo_setor))
        return [{"id": 2, "recurso": "1303"}]

    def finalizar_fora_turno_automatico(
        self, moment, *, operador, motivo, tipo_interrupcao
    ):
        self.shift_returns.append((moment, operador, motivo, tipo_interrupcao))
        return [{"id": 3, "recurso": "1303"}]


class AutomaticBreakTests(unittest.TestCase):
    def test_horarios_oficiais_incluem_almoco_e_cafe(self):
        rules = ManufacturingRules()
        self.assertEqual(
            rules.automatic_breaks,
            (
                (
                    datetime.strptime("12:10", "%H:%M").time(),
                    datetime.strptime("12:52", "%H:%M").time(),
                    "Almoço",
                ),
                (
                    datetime.strptime("15:30", "%H:%M").time(),
                    datetime.strptime("15:45", "%H:%M").time(),
                    "Café",
                ),
            ),
        )

    def test_intervalo_dispara_inicio_e_fim_nos_instantes_exatos(self):
        db = BreakRepositoryFake()
        service = ShiftBoundaryService(db)

        start_result = service.apply_due(datetime(2026, 8, 31, 12, 10))
        self.assertTrue(
            any(moment == datetime(2026, 8, 31, 12, 10) for moment, *_ in db.started)
        )
        self.assertGreaterEqual(start_result["count"], 1)

        finish_result = service.apply_due(datetime(2026, 8, 31, 12, 52))
        self.assertTrue(
            any(moment == datetime(2026, 8, 31, 12, 52) for moment, *_ in db.finished)
        )
        self.assertGreaterEqual(finish_result["count"], 1)

    def test_intervalo_configuravel_nao_retorna_antes_e_retorna_no_fim_cadastrado(self):
        db = _PausaConfiguradaFake([{
            "tipo_setor": "Serra",
            "nome": "Café especial",
            "hora_inicio": datetime.strptime("14:03", "%H:%M").time(),
            "hora_fim": datetime.strptime("14:17", "%H:%M").time(),
            "ativo": True,
            "ordem": 1,
        }])
        service = ShiftBoundaryService(db)

        service.apply_due(datetime(2026, 8, 31, 14, 16, 59))
        self.assertFalse(any(
            moment == datetime(2026, 8, 31, 14, 17)
            for moment, *_ in db.finished
        ))

        service.apply_due(datetime(2026, 8, 31, 14, 17))
        self.assertTrue(any(
            moment == datetime(2026, 8, 31, 14, 17)
            and name == "Café especial"
            and sector == "Serra"
            for moment, name, _operator, sector in db.finished
        ))

    def test_abertura_do_turno_dispara_retorno_sem_demanda_as_0800(self):
        db = BreakRepositoryFake()
        service = ShiftBoundaryService(db)

        service.apply_due(datetime(2026, 9, 4, 8, 0))

        returns_today = [item for item in db.shift_returns if item[0].date() == date(2026, 9, 4)]
        self.assertEqual(len(returns_today), 1)
        self.assertEqual(returns_today[0][0], datetime(2026, 9, 4, 8, 0))
        self.assertEqual(returns_today[0][3], "retorno_turno_sem_demanda")

    def test_sem_configuracao_a_pausa_vale_para_a_fabrica_inteira(self):
        """Fallback do domínio: nenhum setor declarado, nenhuma filtragem."""

        service = ShiftBoundaryService(BreakRepositoryFake())
        configuradas = service.configured_breaks()
        self.assertEqual(len(configuradas), 2)
        self.assertTrue(all(setor is None for *_ignorado, setor in configuradas))


class _PausaConfiguradaFake(BreakRepositoryFake):
    """Configuração gerencial por setor, como a migration 23 persiste."""

    def __init__(self, pausas):
        super().__init__()
        self.pausas = list(pausas)

    def listar_pausas_automaticas(self, *, tipo_setor=None, somente_ativas=True):
        linhas = [dict(item) for item in self.pausas]
        if somente_ativas:
            linhas = [item for item in linhas if item.get("ativo", True)]
        if tipo_setor:
            alvo = str(tipo_setor).strip().casefold()
            linhas = [
                item for item in linhas
                if str(item.get("tipo_setor") or "").strip().casefold() == alvo
            ]
        return linhas


class PausasConfiguraveisPorSetorTests(unittest.TestCase):
    """Wave 3: horário de pausa é configuração gerencial, não regra de código."""

    @staticmethod
    def _hora(texto):
        return datetime.strptime(texto, "%H:%M").time()

    def _servico(self, pausas):
        db = _PausaConfiguradaFake(pausas)
        return db, ShiftBoundaryService(db)

    def test_setores_diferentes_param_em_horarios_diferentes(self):
        db, service = self._servico([
            {"tipo_setor": "Corte", "nome": "Almoço", "hora_inicio": self._hora("11:30"),
             "hora_fim": self._hora("12:12"), "ativo": True, "ordem": 1},
            {"tipo_setor": "Dobra", "nome": "Almoço", "hora_inicio": self._hora("12:10"),
             "hora_fim": self._hora("12:52"), "ativo": True, "ordem": 1},
        ])

        # A janela de recuperação também reprocessa o dia anterior; o que
        # importa é o setor de CADA instante, não o conjunto acumulado.
        service.apply_due(datetime(2026, 8, 31, 11, 30))
        no_instante = {
            setor for momento, _n, _o, setor in db.started
            if momento == datetime(2026, 8, 31, 11, 30)
        }
        self.assertEqual(no_instante, {"Corte"})

        service.apply_due(datetime(2026, 8, 31, 12, 10))
        self.assertEqual(
            {
                setor for momento, _n, _o, setor in db.started
                if momento == datetime(2026, 8, 31, 12, 10)
            },
            {"Dobra"},
        )

    def test_varias_pausas_no_mesmo_dia_e_setor(self):
        db, service = self._servico([
            {"tipo_setor": "Dobra", "nome": "Almoço", "hora_inicio": self._hora("12:10"),
             "hora_fim": self._hora("12:52"), "ativo": True, "ordem": 1},
            {"tipo_setor": "Dobra", "nome": "Café", "hora_inicio": self._hora("15:30"),
             "hora_fim": self._hora("15:45"), "ativo": True, "ordem": 2},
            {"tipo_setor": "Dobra", "nome": "Ginástica", "hora_inicio": self._hora("09:40"),
             "hora_fim": self._hora("09:50"), "ativo": True, "ordem": 3},
        ])
        service.apply_due(datetime(2026, 8, 31, 16, 0))
        nomes = {
            nome for momento, nome, _o, _s in db.started
            if momento.date() == date(2026, 8, 31)
        }
        self.assertEqual(nomes, {"Almoço", "Café", "Ginástica"})

    def test_pausa_inativa_nao_dispara(self):
        db, service = self._servico([
            {"tipo_setor": "Dobra", "nome": "Almoço", "hora_inicio": self._hora("12:10"),
             "hora_fim": self._hora("12:52"), "ativo": True, "ordem": 1},
            {"tipo_setor": "Dobra", "nome": "Café", "hora_inicio": self._hora("15:30"),
             "hora_fim": self._hora("15:45"), "ativo": False, "ordem": 2},
        ])
        service.apply_due(datetime(2026, 8, 31, 16, 0))
        self.assertEqual(
            {
                nome for momento, nome, _o, _s in db.started
                if momento.date() == date(2026, 8, 31)
            },
            {"Almoço"},
        )

    def test_mudar_a_configuracao_muda_o_horario_sem_tocar_no_codigo(self):
        db, service = self._servico([
            {"tipo_setor": "Serra", "nome": "Almoço", "hora_inicio": self._hora("12:30"),
             "hora_fim": self._hora("13:12"), "ativo": True, "ordem": 1},
        ])
        service.apply_due(datetime(2026, 8, 31, 12, 10))
        self.assertEqual(
            [m for m, *_ in db.started if m.date() == date(2026, 8, 31)], []
        )
        service.apply_due(datetime(2026, 8, 31, 12, 30))
        self.assertEqual(
            [
                (momento, setor) for momento, _n, _o, setor in db.started
                if momento.date() == date(2026, 8, 31)
            ],
            [(datetime(2026, 8, 31, 12, 30), "Serra")],
        )


class ActiveResourceAtShiftLimitFake:
    """Recurso em Produção que atravessa o limite oficial das 21:30."""

    def __init__(self):
        self.interrupted = []
        self.open_appointment = {
            "id": 51,
            "op": "A9717101001",
            "maquina": "Estação 3",
            "codigo_recurso": "ROBO P",
            "status": "Em processo",
            "data_inicio": datetime(2026, 9, 3, 21, 3),
        }

    def listar_apontamentos_abertos_no_limite_turno(self, boundary):
        if self.open_appointment["data_inicio"] > boundary:
            return []
        if any(moment == boundary for _, moment in self.interrupted):
            return []
        return [self.open_appointment]

    def interromper_apontamento_fim_turno(self, appointment_id, *, data_hora, operador, motivo, tipo_interrupcao):
        self.interrupted.append((appointment_id, data_hora))
        return {
            "id": appointment_id,
            "interrupcao_registrada": True,
            "data_hora": data_hora,
            "operador": operador,
            "motivo": motivo,
            "tipo_interrupcao": tipo_interrupcao,
        }


class OvertimeShiftLimitTests(unittest.TestCase):
    """Etapa 4B: H2 (17:30–21:30) e o corte automático das 21:30."""

    def test_janela_h2_e_limites_oficiais_permanecem_os_homologados(self):
        rules = ManufacturingRules()
        self.assertEqual(
            rules.shift_end_boundaries,
            (
                datetime.strptime("17:30", "%H:%M").time(),
                datetime.strptime("21:30", "%H:%M").time(),
            ),
        )
        self.assertEqual(
            rules.overtime_windows[1],
            (
                datetime.strptime("17:30", "%H:%M").time(),
                datetime.strptime("21:30", "%H:%M").time(),
            ),
        )

    def test_recurso_ativo_em_h2_e_interrompido_no_horario_oficial_das_2130(self):
        db = ActiveResourceAtShiftLimitFake()
        service = ShiftBoundaryService(db)

        # O detector roda depois do limite; a interrupção precisa ser gravada
        # às 21:30 em ponto, não no instante da detecção.
        result = service.apply_due(datetime(2026, 9, 3, 21, 32, 19))

        self.assertEqual(
            db.interrupted, [(51, datetime(2026, 9, 3, 21, 30))]
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["boundary"], datetime(2026, 9, 3, 21, 30))

    def test_limite_das_2130_nao_e_reaplicado_ao_mesmo_apontamento(self):
        db = ActiveResourceAtShiftLimitFake()
        service = ShiftBoundaryService(db)

        service.apply_due(datetime(2026, 9, 3, 21, 32))
        again = service.apply_due(datetime(2026, 9, 3, 21, 40))

        self.assertEqual(len(db.interrupted), 1)
        self.assertEqual(again["count"], 0)


class OutOfShiftInOeeTests(unittest.TestCase):
    """Fora de turno é medido, mas não entra no tempo disponível do OEE."""

    @staticmethod
    def _seconds(out_of_shift):
        return {
            EventCategory.PRODUCTION: 3600.0,
            EventCategory.SETUP: 600.0,
            EventCategory.DOWNTIME: 1800.0,
            EventCategory.OUT_OF_SHIFT: out_of_shift,
        }

    def test_fora_de_turno_nao_altera_disponibilidade(self):
        base = calculate_oee(
            seconds_by_category=self._seconds(0.0),
            good_quantity=10,
            scrap_quantity=1,
            rework_quantity=0,
            standard_run_seconds=1200.0,
        )
        with_out_of_shift = calculate_oee(
            seconds_by_category=self._seconds(36000.0),
            good_quantity=10,
            scrap_quantity=1,
            rework_quantity=0,
            standard_run_seconds=1200.0,
        )

        self.assertEqual(
            base.time_bases["available_seconds"],
            with_out_of_shift.time_bases["available_seconds"],
        )
        self.assertEqual(base.availability.value, with_out_of_shift.availability.value)
        self.assertEqual(base.oee.value, with_out_of_shift.oee.value)

    def test_disponibilidade_usa_apenas_tempo_trabalhado_sobre_disponivel(self):
        calculation = calculate_oee(
            seconds_by_category=self._seconds(7200.0),
            good_quantity=10,
            scrap_quantity=1,
            rework_quantity=0,
            standard_run_seconds=1200.0,
        )
        self.assertEqual(calculation.time_bases["available_seconds"], 6000.0)
        self.assertEqual(calculation.time_bases["worked_seconds"], 4200.0)
        self.assertAlmostEqual(calculation.availability.value, 70.0, places=6)


class AndonCatalogFake:
    def __init__(self, resources):
        self._resources = resources

    def listar_recursos_pcfactory(self):
        return self._resources


class AndonContractTests(unittest.TestCase):
    """O verificador da 4B precisa ler o contrato real: `sectors[].resources[]`."""

    def setUp(self):
        self.filters = AnalyticsFilter(
            inicio=datetime(2026, 9, 3, 8, 0), fim=datetime(2026, 9, 4, 8, 0)
        )
        self.db = AndonCatalogFake(
            [
                {"codigo": "ROBO P", "nome": "SOLDA ROBO CHASSI PRIME", "tipo_setor": "Solda"},
                {"codigo": "CNC-02", "nome": "Eurostec", "tipo_setor": "Usinagem"},
                {"codigo": "SERRA4", "nome": "SERRA4", "tipo_setor": "Serra"},
            ]
        )
        self.overview = {
            "kpis": {
                "oee": {"value": 11.2, "availability": "disponivel", "unit": "%", "reason": None},
                "availability": {"value": 78.4, "availability": "disponivel", "unit": "%", "reason": None},
                "performance": {"value": 14.8, "availability": "disponivel", "unit": "%", "reason": None},
                "ftt": {"value": 96.5, "availability": "disponivel", "unit": "%", "reason": None},
            },
            "resource_kpis": [],
        }

    def _snapshot(self, operational_resources):
        service = AndonService(self.db, simulation_mode=True)
        return service.build_snapshot(
            self.filters,
            operational={"agora": datetime(2026, 9, 4, 8, 0), "resources": operational_resources},
            overview=self.overview,
        )

    def test_snapshot_sem_apontamentos_preserva_paineis_compactos_sem_maquinas(self):
        snapshot = self._snapshot([])

        self.assertNotIn("resources", snapshot)
        self.assertNotIn("items", snapshot)
        self.assertIn("sectors", snapshot)
        agrupados = [
            resource
            for sector in snapshot["sectors"]
            for resource in sector["resources"]
        ]
        self.assertEqual(snapshot["resource_count"], len(agrupados))
        self.assertEqual(snapshot["summary"]["resources"], len(agrupados))
        self.assertEqual(snapshot["availability"], "sem_registros")
        self.assertEqual(
            [sector["name"] for sector in snapshot["sectors"]],
            ["Corte", "Caldeiraria", "Solda", "Pintura"],
        )
        self.assertEqual(agrupados, [])

    def test_fora_turno_nao_e_apontamento_ativo_do_andon(self):
        snapshot = self._snapshot(
            [
                {
                    "recurso": "Eurostec",
                    "setor": "Usinagem",
                    "categoria": "fora_turno",
                    "inicio": datetime(2026, 9, 3, 21, 30),
                    "duracao_segundos": 37800.0,
                    "motivo": "Fim de turno — interrupção programada automática",
                    "fonte": "eventos_estado_recurso",
                }
            ]
        )
        self.assertFalse(any(
            resource["code"] == "CNC-02"
            for sector in snapshot["sectors"]
            for resource in sector["resources"]
        ))
        self.assertEqual(snapshot["summary"]["out_of_shift"], 0)

    def test_categoria_sintetica_da_simulacao_nao_vira_estado_fisico(self):
        """`livre` só existe na Consulta Operacional em simulação e não é estado."""

        snapshot = self._snapshot(
            [
                {
                    "recurso": "SERRA4",
                    "setor": "Serra",
                    "categoria": "livre",
                    "motivo": "Recurso livre no instante simulado.",
                    "fonte": "catalogo_recursos_pcfactory+apontamentos_operacionais",
                }
            ]
        )
        self.assertFalse(any(
            resource["code"] == "SERRA4"
            for sector in snapshot["sectors"]
            for resource in sector["resources"]
        ))
        self.assertEqual(snapshot["summary"]["unknown"], 0)

    def test_andon_copia_os_kpis_do_management_sem_recalcular(self):
        snapshot = self._snapshot([])
        for key in ("oee", "availability", "performance", "ftt"):
            self.assertEqual(
                snapshot["summary"][key]["value"], self.overview["kpis"][key]["value"]
            )
        self.assertEqual(
            snapshot["sources"]["factory_metrics"], "ManagementService.get_overview"
        )
        self.assertEqual(snapshot["sources"]["physical_state"], "eventos_estado_recurso")


class OperationalViewRepositoryFake:
    """Estado físico gravado pelo nome do posto; catálogo pelo código técnico."""

    def __init__(self):
        self.states = [
            {
                "id": 91,
                "recurso": "Gasparini",
                "tipo_setor": "Dobra",
                "categoria": "fora_turno",
                "codigo_status_recurso": None,
                "motivo": "Fim de turno — interrupção programada automática",
                "causa_raiz": None,
                "data_inicio": datetime(2026, 9, 3, 21, 30),
                "planejado": True,
                "automatico": True,
                "tipo_interrupcao": "fim_turno",
                "op": None,
                "numero_operacao": None,
                "produto_codigo": None,
                "operador": "SISTEMA",
            }
        ]

    def listar_estados_recurso_atuais(self, **_kwargs):
        return self.states

    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return []

    def listar_configuracao_capacidade_recursos(self, **_kwargs):
        return [
            {"codigo": "DOBRA1", "nome": "Gasparini", "tipo_setor": "Dobra"},
            {"codigo": "DOBRA2", "nome": "2204", "tipo_setor": "Dobra"},
        ]

    def listar_cortes_ativos_andon(self):
        return []


class OperationalViewIdentityTests(unittest.TestCase):
    """Bug comprovado na 4B: a mesma máquina listada duas vezes na simulação."""

    def _resources(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        moment = datetime(2026, 9, 4, 6, 55)
        facade = FrontendBackendFacade(
            OperationalViewRepositoryFake(), now_func=lambda: moment, simulation_mode=True
        )
        payload = facade.consulta_operacional(
            AnalyticsFilter(inicio=datetime(2026, 9, 3, 8, 0), fim=moment)
        )
        return payload, payload["resources"]

    def test_maquina_com_estado_fisico_nao_reaparece_como_livre_pelo_codigo(self):
        payload, resources = self._resources()

        gasparini = [item for item in resources if item["recurso"] == "Gasparini"]
        dobra1 = [item for item in resources if item["recurso"] == "DOBRA1"]

        self.assertEqual(len(gasparini), 1)
        self.assertEqual(gasparini[0]["categoria"], "fora_turno")
        self.assertEqual(gasparini[0]["fonte"], "eventos_estado_recurso")
        self.assertEqual(dobra1, [], "DOBRA1 e Gasparini são a mesma máquina")
        self.assertEqual(payload["count"], len(resources))

    def test_recurso_sem_estado_fisico_continua_listado_como_livre(self):
        _payload, resources = self._resources()

        dobra2 = [item for item in resources if item["recurso"] == "DOBRA2"]
        self.assertEqual(len(dobra2), 1)
        self.assertEqual(dobra2[0]["categoria"], "livre")
        self.assertEqual(
            dobra2[0]["fonte"], "catalogo_recursos_pcfactory+apontamentos_operacionais"
        )

    def test_visao_por_posto_exclui_inventario_sem_apontamento_canonico(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        moment = datetime(2026, 9, 4, 6, 55)
        facade = FrontendBackendFacade(
            OperationalViewRepositoryFake(), now_func=lambda: moment, simulation_mode=True
        )
        payload = facade.consulta_operacional(
            AnalyticsFilter(inicio=datetime(2026, 9, 3, 8, 0), fim=moment),
            somente_vinculo_operacional=True,
        )
        self.assertEqual(payload["resources"], [])
        self.assertEqual(payload["count"], 0)

    def test_visao_por_posto_publica_apontamento_corte_ativo(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        repository = OperationalViewRepositoryFake()
        repository.listar_cortes_ativos_andon = lambda: [{
            "maquina": "Laser Ensis 3015",
            "codigo_tarefa": "8478",
            "programa": "N-8478",
            "nome_chapa": "CH-1",
            "operador_inicio": "Operador Corte",
            "data_inicio": datetime(2026, 9, 4, 6, 50),
        }]
        moment = datetime(2026, 9, 4, 6, 55)
        facade = FrontendBackendFacade(repository, now_func=lambda: moment, simulation_mode=True)

        payload = facade.consulta_operacional(
            AnalyticsFilter(inicio=datetime(2026, 9, 3, 8, 0), fim=moment),
            somente_vinculo_operacional=True,
        )

        self.assertEqual([item["recurso"] for item in payload["resources"]], ["Laser Ensis 3015"])
        self.assertEqual(payload["resources"][0]["fonte"], "apontamentos_corte")

    def test_retorno_das_0800_e_sem_demanda_sem_reabrir_op_interrompida(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        repository = OperationalViewRepositoryFake()
        repository.states = [{
            **repository.states[0],
            "categoria": "fila",
            "motivo": "Retorno do turno — recurso sem demanda",
            "data_inicio": datetime(2026, 9, 4, 8, 0),
            "planejado": None,
            "tipo_interrupcao": "retorno_turno_sem_demanda",
        }]
        repository.listar_fatos_operacionais_periodo = lambda *_args, **_kwargs: [{
            "id": 51,
            "maquina": "Gasparini",
            "tipo_setor": "Dobra",
            "op": "OP-INTERROMPIDA",
            "status": "Parada",
            "data_inicio": datetime(2026, 9, 3, 16, 0),
        }]
        moment = datetime(2026, 9, 4, 8, 1)
        facade = FrontendBackendFacade(
            repository, now_func=lambda: moment, simulation_mode=True
        )

        payload = facade.consulta_operacional(
            AnalyticsFilter(inicio=datetime(2026, 9, 4, 8, 0), fim=moment),
            somente_vinculo_operacional=True,
        )

        self.assertEqual(len(payload["resources"]), 1)
        resource = payload["resources"][0]
        self.assertTrue(resource["sem_demanda"])
        self.assertEqual(resource["categoria"], "fila")
        self.assertEqual(resource["ops_ativas"], [])
        self.assertEqual(resource["quantidade_ops_ativas"], 0)


class SerializableExpectedBlockTests(unittest.TestCase):
    def test_bloqueio_com_datetime_nos_detalhes_permanece_409(self):
        app = FastAPI()
        register_error_handlers(app)

        @app.get("/blocked")
        def blocked():
            raise AppError(
                "expected_block",
                "Bloqueio esperado.",
                status_code=409,
                details={"operacao": {"sincronizado_em": datetime(2026, 8, 31, 11, 20)}},
            )

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/blocked")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "expected_block")
        self.assertEqual(
            response.json()["details"]["operacao"]["sincronizado_em"],
            "2026-08-31T11:20:00",
        )


if __name__ == "__main__":
    unittest.main()
