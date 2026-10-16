"""Aba Diretoria — serviço de resumo (Painel + Ficha + Custos), Task 4.

Fonte física canônica (``eventos_estado_recurso``) com dados determinísticos.
Semana de 12/10/2026 (segunda) a sexta 16/10/2026 18:00 (``NOW``).

LASER1 (Corte): 31 h de produção, 9 h de parada não planejada (5 h falta de
material + 4 h manutenção), 1 h de parada planejada, 1 h de pausa automática,
2 h sem demanda (fila sem OP), 1 h fora de turno; 128 peças boas.
DOBRA1 (Dobra): 4 h de produção, 2 h de quebra (segunda) e uma parada em
andamento desde sexta 16:00 (2 h até ``NOW``); 20 peças.
SOLDA1 (Solda): 3 h produção + 1 h parada; PINTURA1 (Pintura): 2 h + 0,5 h.
EXP1 (Expedição): só parada planejada (10 h) e pausa automática (10 h).
"""

from __future__ import annotations

import unittest
from unittest import mock
from datetime import datetime, timedelta
from decimal import Decimal

from mes.contracts import AnalyticsFilter
from mes.services.director_summary import (
    DirectorSummaryError,
    DirectorSummaryService,
    best_and_worst_sector,
    format_hours,
    format_reais,
    resolve_period,
)
from mes.services.management import ManagementService

NOW = datetime(2026, 10, 16, 18, 0)
MON = datetime(2026, 10, 12)


def _h(day, hour, minute=0):
    return MON + timedelta(days=day, hours=hour, minutes=minute)


def _state(sid, recurso, setor, categoria, inicio, fim, *, motivo=None, planejado=False,
           automatico=False, op="OP1"):
    return {
        "id": sid, "recurso": recurso, "tipo_setor": setor, "categoria": categoria,
        "data_inicio": inicio, "data_fim": fim, "motivo": motivo,
        "planejado": planejado, "automatico": automatico, "op": op,
        "status_nome": None, "status_grupo_codigo": None, "status_planejado": None,
        "codigo_status_recurso": None, "tipo_interrupcao": None,
    }


def _states():
    return [
        # LASER1 — Corte
        _state(1, "LASER1", "Corte", "producao", _h(0, 6), _h(0, 22)),
        _state(2, "LASER1", "Corte", "parada", _h(0, 22), _h(1, 3), motivo="falta de material"),
        _state(3, "LASER1", "Corte", "producao", _h(1, 3), _h(1, 18)),
        _state(4, "LASER1", "Corte", "parada", _h(1, 18), _h(1, 22), motivo="manutenção corretiva"),
        _state(5, "LASER1", "Corte", "parada", _h(1, 22), _h(1, 23), motivo="reunião", planejado=True),
        _state(6, "LASER1", "Corte", "parada", _h(2, 12), _h(2, 13), motivo="almoço",
               planejado=True, automatico=True),
        _state(7, "LASER1", "Corte", "fila", _h(2, 13), _h(2, 15), op=None),
        _state(8, "LASER1", "Corte", "fora_turno", _h(2, 15), _h(2, 16), op=None),
        # DOBRA1 — Dobra (parada em andamento na sexta)
        _state(10, "DOBRA1", "Dobra", "producao", _h(0, 8), _h(0, 12), op="OP2"),
        _state(11, "DOBRA1", "Dobra", "parada", _h(0, 12), _h(0, 14), motivo="quebra", op="OP2"),
        _state(12, "DOBRA1", "Dobra", "parada", _h(4, 16), None, motivo="falta de operador", op="OP2"),
        # SOLDA1 — Solda
        _state(20, "SOLDA1", "Solda", "producao", _h(0, 9), _h(0, 12), op="OP3"),
        _state(21, "SOLDA1", "Solda", "parada", _h(0, 12), _h(0, 13), motivo="falta de material", op="OP3"),
        # PINTURA1 — Pintura
        _state(30, "PINTURA1", "Pintura", "producao", _h(0, 9), _h(0, 11), op="OP4"),
        _state(31, "PINTURA1", "Pintura", "parada", _h(0, 11), _h(0, 11, 30), motivo="limpeza", op="OP4"),
        # EXP1 — Expedição: só planejada/automática, nunca entra no ranking
        _state(40, "EXP1", "Expedição", "parada", _h(0, 6), _h(0, 16), motivo="inventário",
               planejado=True, op=None),
        _state(41, "EXP1", "Expedição", "parada", _h(1, 6), _h(1, 16), motivo="pausa",
               planejado=True, automatico=True, op=None),
    ]


def _quantities():
    return [
        {"id": 1, "tipo": "boa", "quantidade": 128, "tipo_setor": "Corte", "recurso": "LASER1",
         "data_hora": _h(1, 17)},
        {"id": 2, "tipo": "boa", "quantidade": 20, "tipo_setor": "Dobra", "recurso": "DOBRA1",
         "data_hora": _h(0, 11)},
    ]


def _participations():
    def part(pid, cracha, operador_id, nome, recurso, setor, inicio, fim):
        return {
            "id": pid, "cracha": cracha, "cracha_resolvido": cracha, "operador_id": operador_id,
            "nome": nome, "nome_resolvido": nome, "recurso": recurso, "tipo_setor": setor,
            "data_inicio": inicio, "data_fim": fim,
        }

    return [
        # Ana a semana inteira no LASER1 (aberta).
        part(1, "100", 1, "Ana", "LASER1", "Corte", _h(0, 0), None),
        # Bruno em dois recursos ao mesmo tempo (10h–14h): conta uma vez só,
        # no recurso da participação iniciada mais recentemente (SOLDA1).
        part(2, "200", 2, "Bruno", "DOBRA1", "Dobra", _h(0, 8), _h(0, 14)),
        part(3, "200", 2, "Bruno", "SOLDA1", "Solda", _h(0, 10), _h(0, 14)),
        # Carla junto com Bruno no DOBRA1 e depois na parada em andamento.
        part(4, "300", 3, "Carla", "DOBRA1", "Dobra", _h(0, 8), _h(0, 14)),
        part(5, "300", 3, "Carla", "DOBRA1", "Dobra", _h(4, 15), None),
    ]


class _Repo:
    """Repositório em memória que imita os recortes do PostgreSQL."""

    def __init__(self, *, states=None, quantities=None, participations=None):
        self.states = _states() if states is None else states
        self.quantities = _quantities() if quantities is None else quantities
        self.participations = _participations() if participations is None else participations
        self.resource_rates = {}
        self.operator_rates = {}
        self.operators = [
            {"id": 1, "nome": "Ana", "cracha": "100", "ativo": True},
            {"id": 2, "nome": "Bruno", "cracha": "200", "ativo": True},
            {"id": 3, "nome": "Carla", "cracha": "300", "ativo": True},
        ]

    # --- fontes analíticas -------------------------------------------------
    def listar_estados_recurso_periodo(self, inicio, fim, *, setor=None, recurso=None,
                                       categoria=None, op=None, operacao=None):
        open_end = min(fim, NOW)
        rows = []
        for raw in self.states:
            if setor and raw["tipo_setor"].upper() != setor.upper():
                continue
            if recurso and raw["recurso"].upper() != recurso.upper():
                continue
            if categoria and raw["categoria"] != categoria:
                continue
            end = raw["data_fim"] or open_end
            if raw["data_inicio"] >= fim or end <= inicio:
                continue
            row = dict(raw)
            row["inicio_periodo"] = max(raw["data_inicio"], inicio)
            row["fim_periodo"] = min(end, fim)
            rows.append(row)
        return rows

    def listar_eventos_quantidade_periodo(self, inicio, fim, *, setor=None, recurso=None, **_):
        return [
            dict(row) for row in self.quantities
            if inicio <= row["data_hora"] <= fim
            and (not setor or row["tipo_setor"].upper() == setor.upper())
            and (not recurso or row["recurso"].upper() == recurso.upper())
        ]

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return []

    def listar_tempos_nesting_corte(self, *_a, **_k):
        return []

    def listar_producao_corte_periodo(self, *_a, **_k):
        return []

    def possui_calendario_produtivo(self, *_a, **_k):
        return False

    def listar_inconsistencias_dados(self, *_a, **_k):
        return []

    def listar_participacoes_operador_periodo(self, inicio, fim, *, recurso=None, setor=None, **_):
        return [
            dict(row) for row in self.participations
            if row["data_inicio"] < fim and (row["data_fim"] or fim) > inicio
            and (not recurso or row["recurso"].upper() == recurso.upper())
            and (not setor or row["tipo_setor"].upper() == setor.upper())
        ]

    def listar_operadores_apontamento(self, somente_ativos=True):
        return [dict(row) for row in self.operators if row["ativo"] or not somente_ativos]

    # --- custos (Task 1) ---------------------------------------------------
    def listar_custos_hora_recurso(self):
        return [{"recurso": k, "valor_hora": v} for k, v in self.resource_rates.items()]

    def listar_custos_hora_operador(self):
        return [{"operador_id": k, "valor_hora": v} for k, v in self.operator_rates.items()]

    def salvar_custo_hora_recurso(self, recurso, valor_hora, usuario):
        self.resource_rates[str(recurso).strip().upper()] = valor_hora

    def salvar_custo_hora_operador(self, operador_id, valor_hora, usuario):
        self.operator_rates[int(operador_id)] = valor_hora


def _with_rates(repo):
    repo.resource_rates["LASER1"] = Decimal("150")
    repo.operator_rates[1] = Decimal("100")  # Ana
    repo.operator_rates[2] = Decimal("50")   # Bruno
    repo.operator_rates[3] = Decimal("40")   # Carla
    return repo


class ResolvePeriodTests(unittest.TestCase):
    def test_hoje_e_o_dia_civil_igual_a_visao_geral(self):
        self.assertEqual(
            resolve_period("hoje", NOW),
            (datetime(2026, 10, 16, 0, 0), datetime(2026, 10, 16, 23, 59, 59)),
        )

    def test_semana_comeca_na_segunda_e_mes_no_dia_1(self):
        self.assertEqual(resolve_period("semana", NOW)[0], datetime(2026, 10, 12))
        self.assertEqual(resolve_period("mes", NOW)[0], datetime(2026, 10, 1))
        self.assertEqual(resolve_period("mes", NOW)[1], datetime(2026, 10, 16, 23, 59, 59))

    def test_periodo_desconhecido_e_erro_de_validacao(self):
        with self.assertRaises(DirectorSummaryError) as ctx:
            resolve_period("ano", NOW)
        self.assertEqual(ctx.exception.status_code, 422)


class FormatTests(unittest.TestCase):
    def test_reais_com_milhar_e_sem_centavos_quando_inteiro(self):
        self.assertEqual(format_reais(Decimal("2250")), "R$ 2.250")
        self.assertEqual(format_reais(Decimal("2250.5")), "R$ 2.250,50")
        self.assertEqual(format_reais(Decimal("0")), "R$ 0")
        self.assertEqual(format_reais(Decimal("1234567.89")), "R$ 1.234.567,89")

    def test_horas(self):
        self.assertEqual(format_hours(31.0), "31 h")
        self.assertEqual(format_hours(0.5), "0,5 h")
        self.assertEqual(format_hours(8.04), "8 h")


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.repo = _with_rates(_Repo())
        self.service = DirectorSummaryService(self.repo)

    def test_a_cards_identicos_ao_get_overview_do_mesmo_filtro(self):
        panel = self.service.panel("semana", NOW)
        inicio, fim = resolve_period("semana", NOW)
        overview = ManagementService(self.repo, now_func=lambda: NOW).get_overview(
            AnalyticsFilter(inicio, fim)
        )
        self.assertEqual(panel["cards"]["produzido"], overview["production"]["good"])
        # Mesma conta da Visão Geral (frontend_facade): parada − parada planejada.
        self.assertEqual(
            panel["cards"]["horas_paradas"],
            (overview["hours"]["downtime_seconds"] - overview["hours"]["planned_downtime_seconds"]) / 3600,
        )
        self.assertEqual(panel["cards"]["eficiencia_oee"], overview["kpis"]["oee"])
        self.assertEqual(panel["cards"]["produzido"], 148)
        self.assertAlmostEqual(panel["cards"]["horas_paradas"], 9 + 4 + 1 + 0.5)

    def test_b_onde_perdemos_so_nao_planejada_ordenado_e_no_maximo_3(self):
        panel = self.service.panel("semana", NOW)
        ranking = panel["onde_perdemos"]
        self.assertEqual([item["setor"] for item in ranking], ["Corte", "Dobra", "Solda"])
        self.assertAlmostEqual(ranking[0]["horas_paradas"], 9.0)
        self.assertAlmostEqual(ranking[1]["horas_paradas"], 4.0)
        self.assertEqual(ranking[0]["motivo_principal"], "falta de material")
        self.assertEqual(ranking[0]["custo"], 2250.0)
        self.assertNotIn("Expedição", [item["setor"] for item in ranking])

    def test_custo_total_soma_so_paradas_nao_planejadas(self):
        panel = self.service.panel("semana", NOW)
        # LASER1 9h x (150 + Ana 100) = 2250; DOBRA1 2h x Carla 40 + 2h x Carla 40
        # = 160 (Bruno estava no SOLDA1); SOLDA1 1h x Bruno 50 = 50.
        # DOBRA1/SOLDA1/PINTURA1 sem custo próprio.
        self.assertEqual(panel["cards"]["custo_parada"], 2460.0)
        self.assertFalse(panel["custo_completo"])
        self.assertEqual(panel["custos_faltando"], 3)
        self.assertIn("faltam custos de 3 recursos/pessoas", panel["aviso"])
        by_sector = {item["setor"]: item for item in panel["onde_perdemos"]}
        self.assertTrue(by_sector["Corte"]["custo_completo"])
        self.assertFalse(by_sector["Dobra"]["custo_completo"])

    def test_periodo_nome_normalizado(self):
        panel = self.service.panel(" Semana ", NOW)
        self.assertEqual(panel["periodo"]["nome"], "semana")


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.repo = _with_rates(_Repo())
        self.service = DirectorSummaryService(self.repo)

    def test_c_texto_exato_do_laser1(self):
        sheet = self.service.sheet("semana", None, "LASER1", NOW)
        self.assertEqual(
            sheet["texto"],
            "O LASER1 (Corte) trabalhou 31 h de 40 h e produziu 128 peças. "
            "Ficou parado 9 h, o que custou R$ 2.250. "
            "Principal motivo: falta de material (5 h).",
        )
        self.assertTrue(sheet["custo_completo"])
        self.assertEqual(sheet["custos_faltando"], 0)
        self.assertAlmostEqual(sheet["trabalhou_h"], 31.0)
        self.assertAlmostEqual(sheet["disponivel_h"], 40.0)
        self.assertAlmostEqual(sheet["parado_h"], 9.0)
        self.assertEqual(sheet["custo_parada"], 2250.0)
        self.assertEqual(sheet["custo_trabalho"], 31 * 250.0)
        self.assertAlmostEqual(sheet["sem_demanda_h"], 2.0)
        self.assertAlmostEqual(sheet["fora_turno_h"], 1.0)
        self.assertEqual(
            sheet["paradas_por_motivo"],
            [{"motivo": "falta de material", "horas": 5.0},
             {"motivo": "manutenção corretiva", "horas": 4.0}],
        )
        self.assertEqual(
            sheet["pessoas"],
            [{"nome": "Ana", "horas": 40.0, "custo": 4000.0, "custo_completo": True}],
        )

    def test_falta_de_custo_so_no_trabalho_nao_avisa_no_texto_da_parada(self):
        # Bruno (sem valor/h) ajuda no LASER1 só durante a produção de terça.
        del self.repo.operator_rates[2]
        self.repo.participations.append({
            "id": 9, "cracha": "200", "cracha_resolvido": "200", "operador_id": 2,
            "nome": "Bruno", "nome_resolvido": "Bruno", "recurso": "LASER1",
            "tipo_setor": "Corte", "data_inicio": _h(1, 5), "data_fim": _h(1, 10),
        })
        sheet = self.service.sheet("semana", None, "LASER1", NOW)
        self.assertNotIn("Atenção", sheet["texto"])
        self.assertTrue(sheet["texto"].endswith("Principal motivo: falta de material (5 h)."))
        self.assertTrue(sheet["custo_parada_completo"])
        self.assertEqual(sheet["custos_faltando_parada"], 0)
        self.assertFalse(sheet["custo_trabalho_completo"])
        self.assertEqual(sheet["custos_faltando_trabalho"], 1)
        self.assertFalse(sheet["custo_completo"])
        bruno = next(p for p in sheet["pessoas"] if p["nome"] == "Bruno")
        self.assertEqual(bruno, {"nome": "Bruno", "horas": 5.0, "custo": 0.0, "custo_completo": False})

    def test_d_sem_custos_cadastrados_avisa_e_mostra_zero(self):
        service = DirectorSummaryService(_Repo())
        sheet = service.sheet("semana", None, "LASER1", NOW)
        self.assertFalse(sheet["custo_completo"])
        self.assertGreater(sheet["custos_faltando"], 0)
        self.assertEqual(sheet["custo_parada"], 0.0)
        self.assertIn("faltam custos de 2 recursos/pessoas — o valor real é maior", sheet["texto"])
        panel = service.panel("semana", NOW)
        self.assertEqual(panel["cards"]["custo_parada"], 0.0)
        self.assertFalse(panel["custo_completo"])
        self.assertEqual([item["setor"] for item in panel["onde_perdemos"]], ["Corte", "Dobra", "Solda"])

    def test_e_periodo_vazio_nao_quebra(self):
        empty_now = datetime(2026, 12, 1, 10, 0)
        sheet = self.service.sheet("hoje", None, "LASER1", empty_now)
        self.assertIn("sem paradas no período", sheet["texto"].lower())
        self.assertEqual(sheet["parado_h"], 0.0)
        self.assertEqual(sheet["custo_parada"], 0.0)
        self.assertIsNone(sheet["motivo_principal"])
        panel = self.service.panel("hoje", empty_now)
        self.assertEqual(panel["onde_perdemos"], [])
        self.assertEqual(panel["cards"]["custo_parada"], 0.0)
        self.assertTrue(panel["custo_completo"])

    def test_pessoa_em_dois_recursos_conta_uma_vez(self):
        dobra = self.service.sheet("semana", "Dobra", None, NOW)
        solda = self.service.sheet("semana", "Solda", None, NOW)
        bruno_dobra = next(p for p in dobra["pessoas"] if p["nome"] == "Bruno")
        bruno_solda = next(p for p in solda["pessoas"] if p["nome"] == "Bruno")
        # 08–10 no DOBRA1 (2 h); de 10 h em diante vale a participação mais
        # recente (SOLDA1): 2 h de trabalho + 1 h de parada.
        self.assertAlmostEqual(bruno_dobra["horas"], 2.0)
        self.assertEqual(bruno_dobra["custo"], 100.0)
        self.assertAlmostEqual(bruno_solda["horas"], 3.0)
        self.assertEqual(bruno_solda["custo"], 150.0)
        self.assertEqual(solda["custo_parada"], 50.0)
        fabrica = self.service.sheet("semana", None, None, NOW)
        bruno = next(p for p in fabrica["pessoas"] if p["nome"] == "Bruno")
        self.assertAlmostEqual(bruno["horas"], 5.0)

    def test_dois_operadores_no_mesmo_recurso_somam_cada_um_uma_vez(self):
        dobra = self.service.sheet("semana", None, "DOBRA1", NOW)
        horas = {p["nome"]: p["horas"] for p in dobra["pessoas"]}
        self.assertEqual(horas, {"Bruno": 2.0, "Carla": 8.0})
        # 2h x Carla 40 (Bruno já no SOLDA1) + 2h x 40 (parada em andamento, só Carla)
        self.assertEqual(dobra["custo_parada"], 160.0)
        self.assertFalse(dobra["custo_completo"])  # DOBRA1 sem custo
        self.assertEqual(dobra["custos_faltando"], 1)

    def test_parada_em_andamento_conta_uma_vez_ate_agora(self):
        sheet = self.service.sheet("hoje", None, "DOBRA1", NOW)
        self.assertAlmostEqual(sheet["parado_h"], 2.0)
        self.assertEqual(sheet["custo_parada"], 80.0)
        self.assertEqual(sheet["paradas_por_motivo"], [{"motivo": "falta de operador", "horas": 2.0}])

    def test_ficha_do_setor_sem_recurso_agrega_o_setor(self):
        sheet = self.service.sheet("semana", "Corte", None, NOW)
        self.assertTrue(sheet["texto"].startswith("O setor Corte trabalhou 31 h de 40 h"))

    def test_ficha_da_fabrica_inteira(self):
        sheet = self.service.sheet("semana", None, None, NOW)
        self.assertTrue(sheet["texto"].startswith("A fábrica trabalhou"))
        self.assertIn(" Ficou parada 14,5 h, o que custou R$ 2.460.", sheet["texto"])
        self.assertEqual(sheet["custo_parada"], 2460.0)

    def test_ops_simultaneas_com_o_mesmo_motivo_contam_uma_vez(self):
        repo = _Repo(states=[
            _state(1, "LASER1", "Corte", "parada", _h(0, 8), _h(0, 10),
                   motivo="falta de material", op="OP1"),
            _state(2, "LASER1", "Corte", "parada", _h(0, 9), _h(0, 10),
                   motivo="falta de material", op="OP2"),
        ], quantities=[], participations=[])
        sheet = DirectorSummaryService(repo).sheet("semana", None, "LASER1", NOW)
        self.assertEqual(sheet["paradas_por_motivo"], [{"motivo": "falta de material", "horas": 2.0}])
        self.assertIn("Principal motivo: falta de material (2 h).", sheet["texto"])


class PhysicalConsolidationTests(unittest.TestCase):
    """Custo e horas seguem os trechos consolidados da Visão Geral."""

    def _carla(self, inicio, fim, recurso="DOBRA1", setor="Dobra"):
        return {"id": 1, "cracha": "300", "cracha_resolvido": "300", "operador_id": 3, "nome": "Carla",
                "nome_resolvido": "Carla", "recurso": recurso, "tipo_setor": setor,
                "data_inicio": inicio, "data_fim": fim}

    def test_producao_e_parada_simultaneas_no_mesmo_recurso_producao_prevalece(self):
        # OP2 produz 8–12 e OP9 fica parada por falta de material no mesmo DOBRA1.
        repo = _Repo(states=[
            _state(1, "DOBRA1", "Dobra", "producao", _h(0, 8), _h(0, 12), op="OP2"),
            _state(2, "DOBRA1", "Dobra", "parada", _h(0, 8), _h(0, 12), motivo="falta de material", op="OP9"),
        ], quantities=[], participations=[self._carla(_h(0, 8), _h(0, 12))])
        repo.resource_rates["DOBRA1"] = Decimal("100")
        repo.operator_rates[3] = Decimal("50")
        service = DirectorSummaryService(repo)
        sheet = service.sheet("semana", None, "DOBRA1", NOW)
        self.assertEqual(sheet["parado_h"], 0.0)
        self.assertEqual(sheet["custo_parada"], 0.0)
        self.assertEqual(sheet["paradas_por_motivo"], [])
        self.assertIn("Sem paradas no período.", sheet["texto"])
        self.assertAlmostEqual(sheet["trabalhou_h"], 4.0)
        self.assertEqual(sheet["custo_trabalho"], 4 * 150.0)
        # Janela de 4 h: a pessoa nunca passa disso.
        self.assertEqual(sheet["pessoas"], [{"nome": "Carla", "horas": 4.0, "custo": 200.0, "custo_completo": True}])
        panel = service.panel("semana", NOW)
        self.assertEqual(panel["cards"]["horas_paradas"], 0.0)
        self.assertEqual(panel["cards"]["custo_parada"], 0.0)
        self.assertEqual(panel["onde_perdemos"], [])

    def test_parada_e_setup_sobrepostos_viram_desconhecido_sem_custo(self):
        # Visão Geral: estados físicos diferentes ao mesmo tempo = desconhecido.
        repo = _with_rates(_Repo(states=[
            _state(1, "LASER1", "Corte", "setup", _h(0, 8), _h(0, 10), op="OP1"),
            _state(2, "LASER1", "Corte", "parada", _h(0, 8), _h(0, 11), motivo="quebra", op="OP2"),
        ], quantities=[], participations=[self._carla(_h(0, 8), _h(0, 11), "LASER1", "Corte")]))
        sheet = DirectorSummaryService(repo).sheet("semana", None, "LASER1", NOW)
        inicio, fim = resolve_period("semana", NOW)
        overview = ManagementService(repo, now_func=lambda: NOW).get_overview(
            AnalyticsFilter(inicio, fim, recurso="LASER1")
        )
        self.assertEqual(overview["hours"]["conflicting_state_seconds"], 2 * 3600)
        # Só 10–11 é parada de fato (1 h); 8–10 é desconhecido, sem custo.
        self.assertAlmostEqual(sheet["parado_h"], 1.0)
        self.assertEqual(sheet["custo_parada"], 1 * (150.0 + 40.0))
        self.assertEqual(sheet["paradas_por_motivo"], [{"motivo": "quebra", "horas": 1.0}])
        self.assertEqual(sheet["trabalhou_h"], 0.0)
        self.assertEqual(sheet["pessoas"], [{"nome": "Carla", "horas": 1.0, "custo": 40.0, "custo_completo": True}])

    def test_card_e_ficha_usam_parada_menos_planejada_como_a_visao_geral(self):
        # Força unplanned_downtime_seconds divergente: o card não pode lê-lo.
        original = ManagementService.get_overview

        def overview_with_stale_unplanned(service, filters):
            result = dict(original(service, filters))
            result["hours"] = {**result["hours"], "unplanned_downtime_seconds": 0.0}
            return result

        service = DirectorSummaryService(_with_rates(_Repo()))
        with mock.patch.object(ManagementService, "get_overview", overview_with_stale_unplanned):
            panel = service.panel("semana", NOW)
            sheet = service.sheet("semana", None, None, NOW)
            inicio, fim = resolve_period("semana", NOW)
            hours = ManagementService(_Repo(), now_func=lambda: NOW).get_overview(
                AnalyticsFilter(inicio, fim)
            )["hours"]
        expected = (hours["downtime_seconds"] - hours["planned_downtime_seconds"]) / 3600
        self.assertAlmostEqual(expected, 14.5)
        self.assertEqual(panel["cards"]["horas_paradas"], expected)
        self.assertEqual(sheet["parado_h"], expected)
        self.assertIn("Ficou parada 14,5 h", sheet["texto"])


class BestWorstTests(unittest.TestCase):
    def test_melhor_e_pior_usam_o_oee_do_overview_e_ignoram_sem_valor(self):
        sector_kpis = [
            {"setor": "Corte", "metrics": {"oee": {"value": 70.0}}},
            {"setor": "Dobra", "metrics": {"oee": {"value": None}}},
            {"setor": "Solda", "metrics": {"oee": {"value": 40.0}}},
        ]
        best, worst = best_and_worst_sector(sector_kpis)
        self.assertEqual(best, {"nome": "Corte", "oee": 70.0})
        self.assertEqual(worst, {"nome": "Solda", "oee": 40.0})
        self.assertEqual(best_and_worst_sector([]), (None, None))

    def test_com_um_setor_so_nao_existe_pior(self):
        best, worst = best_and_worst_sector([{"setor": "Corte", "metrics": {"oee": {"value": 70.0}}}])
        self.assertEqual(best, {"nome": "Corte", "oee": 70.0})
        self.assertIsNone(worst)

    def test_empate_total_nao_inventa_pior(self):
        kpis = [{"setor": n, "metrics": {"oee": {"value": 0.0}}} for n in ("Corte", "Dobra")]
        best, worst = best_and_worst_sector(kpis)
        self.assertIsNotNone(best)
        self.assertIsNone(worst)


class CostRateTests(unittest.TestCase):
    def setUp(self):
        self.repo = _Repo()
        self.service = DirectorSummaryService(self.repo)

    def test_f_valor_zero_ou_negativo_e_recusado(self):
        for valor in (0, -5, "0", "abc", float("nan")):
            with self.assertRaises(DirectorSummaryError) as ctx:
                self.service.set_resource_rate("LASER1", valor, "dir")
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(ctx.exception.code, "COST_RATE_INVALID")
            with self.assertRaises(DirectorSummaryError):
                self.service.set_operator_rate(1, valor, "dir")
        self.assertEqual(self.repo.resource_rates, {})
        self.assertEqual(self.repo.operator_rates, {})

    def test_valor_que_arredonda_para_zero_ou_absurdo_e_recusado(self):
        for valor in ("0.001", "0.004", "1e12", 10 ** 10):
            with self.assertRaises(DirectorSummaryError) as ctx:
                self.service.set_resource_rate("LASER1", valor, "dir")
            self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("COST_RATE_INVALID", 422))
        self.assertEqual(self.repo.resource_rates, {})
        self.service.set_resource_rate("LASER1", "0.005", "dir")
        self.assertEqual(self.repo.resource_rates["LASER1"], Decimal("0.01"))

    def test_operador_inexistente_e_404(self):
        with self.assertRaises(DirectorSummaryError) as ctx:
            self.service.set_operator_rate(999, 50, "dir")
        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("OPERATOR_NOT_FOUND", 404))
        self.assertEqual(self.repo.operator_rates, {})

    def test_periodo_desconhecido_usa_a_excecao_de_dominio(self):
        with self.assertRaises(DirectorSummaryError) as ctx:
            resolve_period("ano", NOW)
        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("INVALID_PERIOD", 422))

    def test_valor_valido_grava_decimal_e_aparece_em_custos(self):
        self.service.set_resource_rate("laser1", "150.5", "dir")
        self.service.set_operator_rate(2, 50, "dir")
        self.assertEqual(self.repo.resource_rates["LASER1"], Decimal("150.5"))
        costs = self.service.costs()
        laser = next(r for r in costs["recursos"] if r["recurso"] == "LASER1")
        self.assertEqual(laser["valor_hora"], 150.5)
        self.assertEqual(laser["setor"], "Corte")
        bruno = next(p for p in costs["pessoas"] if p["operador_id"] == 2)
        self.assertEqual(bruno, {"operador_id": 2, "nome": "Bruno", "cracha": "200", "valor_hora": 50.0})
        ana = next(p for p in costs["pessoas"] if p["operador_id"] == 1)
        self.assertIsNone(ana["valor_hora"])


if __name__ == "__main__":
    unittest.main()
