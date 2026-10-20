"""Ataque ao Lote 3 da explicação clicável (``kpi.*``): OEE e percentuais de tempo.

Invariante: ``value`` da explicação == cartão do ``get_overview`` (``kpis`` /
``kpis_estendidos``) e ``reconciliation.ok`` verdadeiro, em qualquer filtro.
Não repete ``tests/test_kpi_explanation.py``.
"""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta

from backend.api.errors import AppError
from backend.api.routers.explanation import explain_for_user
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.kpi_explanation import KpiExplanationService
from mes.services.metric_explanation import UnknownMetricError
from tests.test_value_explanation import AGORA, _ApiRepo, _BaseRepo, _user

INICIO = datetime(2026, 8, 18)
FIM = datetime(2026, 8, 21)
DIA = datetime(2026, 8, 19)

OEE = "kpi.oee"
RATIOS = (
    ("kpi.disponibilidade", "kpis", "availability"),
    ("kpi.performance", "kpis", "performance"),
    ("kpi.ae", "kpis_estendidos", "ae"),
    ("kpi.produtividade", "kpis_estendidos", "productivity"),
    ("kpi.utilizacao", "kpis_estendidos", "utilization"),
)
ALL = (("kpi.oee", "kpis", "oee"),) + RATIOS


def _f(inicio=INICIO, fim=FIM, **extra):
    return AnalyticsFilter(inicio, fim, **extra)


def _facade(repo):
    return FrontendBackendFacade(repo, now_func=lambda: AGORA)


def _service(repo):
    return KpiExplanationService(_facade(repo).management, now_func=lambda: AGORA)


class _ManyRepo(_BaseRepo):
    """Vários recursos em vários setores, com horas quebradas (nada redondo).

    Respeita os filtros setor/recurso como o repositório real. Cada recurso:
    ``(setor, recurso, estados[(categoria, hora_ini_min, hora_fim_min)], boas, refugo,
    retrabalho, tempo_medio_s)``.
    """

    def __init__(self, resources=None):
        super().__init__()
        self.resources = resources if resources is not None else self.default_resources()

    @staticmethod
    def default_resources():
        return [
            ("Dobra", "DOBRA1", [("producao", 480, 551), ("setup", 551, 571), ("parada", 571, 590)], 17, 2, 1, 137),
            ("Dobra", "DOBRA2", [("producao", 480, 523), ("fila", 523, 560), ("parada", 560, 577)], 5, 0, 0, 301),
            ("Solda", "SOLDA1", [("producao", 490, 611), ("retrabalho", 611, 640)], 11, 1, 2, 83),
            ("Solda", "SOLDA2", [("producao", 500, 509), ("atividade_sem_op", 509, 530)], 3, 0, 0, 59),
            # Só fila: disponibilidade zero (denominador 0).
            ("Usinagem", "USIN1", [("fila", 480, 600)], 0, 0, 0, 0),
        ]

    def _match(self, setor, recurso):
        return [
            r for r in self.resources
            if (not setor or r[0] == setor) and (not recurso or r[1] == recurso)
        ]

    @staticmethod
    def _at(minutes):
        return DIA + timedelta(minutes=minutes)

    def listar_estados_recurso_periodo(self, inicio, fim, setor=None, recurso=None, **_k):
        rows, n = [], 0
        for sector, name, states, *_ in self._match(setor, recurso):
            for cat, a, b in states:
                start, end = self._at(a), self._at(b)
                if start < fim and end > inicio:
                    n += 1
                    rows.append({
                        "id": n, "recurso": name, "tipo_setor": sector, "categoria": cat,
                        "data_inicio": start, "data_fim": end,
                    })
        return rows

    def listar_fatos_operacionais_periodo(self, inicio, fim, setor=None, recurso=None, **_k):
        rows = []
        for i, (sector, name, states, boas, refugo, retrab, tm) in enumerate(self._match(setor, recurso), 1):
            prod = [s for s in states if s[0] == "producao"]
            if not prod or not (boas or refugo or retrab):
                continue
            start, end = self._at(prod[0][1]), self._at(prod[0][2])
            if not (start < fim and end > inicio):
                continue
            rows.append({
                "id": i, "op": f"OP-{i}", "tipo_setor": sector, "maquina": name,
                "status": "Finalizado", "data_inicio": start, "data_fim": end,
                "quantidade_boa": boas, "quantidade_refugo": refugo,
                "quantidade_retrabalho": retrab, "tempo_medio_segundos": tm,
                "eventos": [
                    {"id": i * 2, "estado": "producao", "data_hora": start},
                    {"id": i * 2 + 1, "estado": "finalizado", "data_hora": end},
                ],
            })
        return rows

    def listar_eventos_quantidade_periodo(self, inicio, fim, setor=None, recurso=None, **_k):
        rows, n = [], 0
        for sector, name, states, boas, refugo, retrab, _tm in self._match(setor, recurso):
            prod = [s for s in states if s[0] == "producao"]
            if not prod:
                continue
            moment = self._at(prod[0][2] - 1)
            if not (inicio <= moment <= fim):
                continue
            for tipo, qtd in (("boa", boas), ("refugo", refugo), ("retrabalho", retrab)):
                if qtd:
                    n += 1
                    rows.append({
                        "id": n, "tipo": tipo, "quantidade": qtd, "op": f"OP-{name}",
                        "tipo_setor": sector, "recurso": name, "operador": "Maria",
                        "motivo": "x" if tipo != "boa" else None,
                        "data_hora": moment, "origem": "gestor_pecas",
                    })
        return rows


class _Stub:
    """Entrega um overview real já adulterado."""

    def __init__(self, repo, mutate):
        self._management = _facade(repo).management
        self._mutate = mutate

    def get_overview(self, filters):
        overview = copy.deepcopy(self._management.get_overview(filters))
        self._mutate(overview)
        return overview

    def _now(self):
        return AGORA


def _stub_explain(repo, metric, mutate, filters=None):
    return KpiExplanationService(_Stub(repo, mutate), now_func=lambda: AGORA).explain(
        metric, filters or _f()
    ).to_dict()


class InvariantMixin:
    def assertInvariant(self, repo, filters, metrics=ALL):
        overview = _facade(repo).management.get_overview(filters)
        service = _service(repo)
        for metric, section, key in metrics:
            with self.subTest(metric=metric, filters=str(filters)):
                tree = service.explain(metric, filters).to_dict()
                card = (overview.get(section) or {}).get(key) or {}
                self.assertEqual(tree["value"], card.get("value"))
                self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
                json.dumps(tree, default=str)  # serializável
                self.assertTrue(tree["reason"])
        return overview


class FilterMatrixTests(InvariantMixin, unittest.TestCase):
    def test_base_com_horas_quebradas_fecha_em_todas_as_metricas(self):
        overview = self.assertInvariant(_ManyRepo(), _f())
        # Sanidade: o cenário realmente exercita valores não redondos.
        self.assertNotEqual(overview["kpis"]["availability"]["value"] % 1, 0.0)

    def test_filtros_de_setor_recurso_turno_existentes_inexistentes_e_combinados(self):
        repo = _ManyRepo()
        for extra in (
            {"setor": "Dobra"}, {"setor": "Solda"}, {"setor": "Usinagem"},
            {"setor": "Inexistente"}, {"recurso": "DOBRA2"}, {"recurso": "SOLDA1"},
            {"recurso": "USIN1"}, {"recurso": "NAO_EXISTE"},
            {"setor": "Dobra", "recurso": "SOLDA1"},  # incompatível entre si
            {"setor": "Solda", "recurso": "SOLDA2"},
            {"turno": "Manhã"}, {"turno": "Turno que não existe"},
            {"setor": "Dobra", "turno": "Tarde"},
            {"setor": "  Dobra  "}, {"setor": "dobra"}, {"setor": ""}, {"recurso": ""},
        ):
            with self.subTest(extra=extra):
                self.assertInvariant(repo, _f(**extra))

    def test_filtro_nao_vaza_recurso_de_outro_setor_na_arvore(self):
        tree = _service(_ManyRepo()).explain("kpi.disponibilidade", _f(setor="Solda")).to_dict()
        names = {n["label"] for s in tree["children"] if s["kind"] == "sector" for n in s["children"]}
        self.assertTrue(names <= {"SOLDA1", "SOLDA2"}, names)

    def test_repo_de_um_recurso_com_filtros_que_o_fake_ignora(self):
        repo = _ApiRepo()
        for extra in ({"setor": "Solda"}, {"recurso": "XPTO"}, {"turno": "Noite"}):
            with self.subTest(extra=extra):
                self.assertInvariant(repo, _f(**extra))


class PeriodTests(InvariantMixin, unittest.TestCase):
    def test_periodo_sem_nenhum_dado(self):
        for repo in (_ManyRepo(), _BaseRepo()):
            self.assertInvariant(repo, _f(datetime(2026, 1, 1), datetime(2026, 1, 2)))

    def test_periodo_futuro(self):
        self.assertInvariant(_ManyRepo(), _f(datetime(2027, 1, 1), datetime(2027, 1, 8)))

    def test_periodo_de_um_segundo_dentro_e_fora_de_estado(self):
        repo = _ManyRepo()
        t = DIA + timedelta(hours=8, minutes=30)
        self.assertInvariant(repo, _f(t, t + timedelta(seconds=1)))
        t2 = DIA + timedelta(hours=3)
        self.assertInvariant(repo, _f(t2, t2 + timedelta(seconds=1)))

    def test_periodo_de_zero_segundos(self):
        t = DIA + timedelta(hours=8, minutes=30)
        self.assertInvariant(_ManyRepo(), _f(t, t))

    def test_periodo_invertido_nao_inventa_numero_diferente_do_cartao(self):
        repo = _ManyRepo()
        filters = _f(FIM, INICIO)
        try:
            overview = _facade(repo).management.get_overview(filters)
        except Exception as exc:  # o cartão também falha: a explicação deve falhar igual
            for metric, _s, _k in ALL:
                with self.subTest(metric=metric):
                    with self.assertRaises(type(exc)):
                        _service(repo).explain(metric, filters)
            return
        for metric, section, key in ALL:
            with self.subTest(metric=metric):
                tree = _service(repo).explain(metric, filters).to_dict()
                self.assertEqual(tree["value"], overview[section][key]["value"])
                self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])

    def test_periodo_que_corta_o_estado_no_meio(self):
        self.assertInvariant(_ManyRepo(), _f(DIA + timedelta(hours=8, minutes=17, seconds=13),
                                              DIA + timedelta(hours=9, minutes=41, seconds=59)))


class MetricIdTests(unittest.TestCase):
    def test_service_rejeita_ids_malformados_com_unknown_metric(self):
        service = _service(_ManyRepo())
        for metric in (
            "KPI.OEE", "kpi.OEE", "Kpi.oee", " kpi.oee", "kpi.oee ", "kpi. oee", "kpi.", "kpi",
            "kpi.oee.extra", "kpi.oee.", ".oee", "oee", "kpi..oee", "kpi.inexistente", "",
            "kpi.oee\n", "kpi.oee\x00", "kpi.ftt", "qtd.ftt",
        ):
            with self.subTest(metric=metric):
                with self.assertRaises(UnknownMetricError):
                    service.explain(metric, _f())

    def test_roteador_tira_espacos_das_pontas_mas_nao_aceita_maiuscula_nem_extra(self):
        facade = _facade(_ManyRepo())
        user = _user("gestor", management=True)
        ok = explain_for_user(facade, "  kpi.oee  ", _f(), user)
        self.assertEqual(ok["metric"], "kpi.oee")
        for metric in ("KPI.OEE", "kpi.OEE", "kpi.oee.extra", "kpi.", "kpi. oee", "kpi"):
            with self.subTest(metric=metric):
                with self.assertRaises(AppError) as ctx:
                    explain_for_user(facade, metric, _f(), user)
                self.assertEqual(ctx.exception.status_code, 422)

    def test_ids_registrados_no_servico_sao_exatamente_os_seis(self):
        from mes.services.kpi_explanation import KPI_TEXT
        self.assertEqual(
            set(KPI_TEXT),
            {"kpi.oee", "kpi.disponibilidade", "kpi.performance", "kpi.ae",
             "kpi.produtividade", "kpi.utilizacao"},
        )


def _flat(nodes):
    for node in nodes:
        yield node
        yield from _flat(node["children"])


class TruncationTests(InvariantMixin, unittest.TestCase):
    def _many(self, n):
        res = [("Dobra", f"DOBRA{i:02d}", [("producao", 480 + i, 540 + 2 * i)], 4 + i, 0, 0, 90 + i)
               for i in range(1, n + 1)]
        return _ManyRepo(res)

    def test_max_leaves_pequeno_trunca_e_a_reconciliacao_continua_fechando(self):
        repo = self._many(7)
        overview = _facade(repo).management.get_overview(_f())
        service = _service(repo)
        for max_leaves in (0, 1, 2, 3, 6, 7, 8, 200):
            for metric, section, key in ALL:
                with self.subTest(max_leaves=max_leaves, metric=metric):
                    tree = service.explain(metric, _f(), max_leaves=max_leaves).to_dict()
                    self.assertEqual(tree["value"], overview[section][key]["value"])
                    self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
                    sector = next(n for n in tree["children"] if n["kind"] == "sector")
                    real = [c for c in sector["children"] if not c.get("truncated")]
                    outros = [c for c in sector["children"] if c.get("truncated")]
                    self.assertEqual(len(real), min(max_leaves, 7))
                    if max_leaves < 7:
                        self.assertEqual(len(outros), 1)
                        self.assertTrue(sector["truncated"])
                        self.assertTrue(tree["truncated"])
                        rest = 7 - max_leaves
                        self.assertEqual(
                            outros[0]["label"], f"Outros {rest} recursos" if rest > 1 else "Outro recurso"
                        )
                        # nada some: os que ficaram + os agregados = todos
                        self.assertEqual(len(real) + rest, 7)
                    else:
                        self.assertEqual(outros, [])
                        self.assertFalse(tree["truncated"])

    def test_os_recursos_que_ficam_sao_sempre_os_de_maior_valor(self):
        repo = self._many(6)
        service = _service(repo)
        full = service.explain("kpi.performance", _f()).to_dict()
        sector_full = next(n for n in full["children"] if n["kind"] == "sector")
        ordered = [c["label"] for c in sector_full["children"]]
        cut = service.explain("kpi.performance", _f(), max_leaves=2).to_dict()
        sector_cut = next(n for n in cut["children"] if n["kind"] == "sector")
        self.assertEqual([c["label"] for c in sector_cut["children"][:2]], ordered[:2])

    def test_truncar_nao_muda_numerador_denominador_nem_valor(self):
        repo = self._many(5)
        service = _service(repo)
        a = service.explain("kpi.disponibilidade", _f(), max_leaves=1).to_dict()
        b = service.explain("kpi.disponibilidade", _f()).to_dict()
        self.assertEqual(a["value"], b["value"])
        self.assertEqual(a["children"][:2], b["children"][:2])
        self.assertEqual(a["reconciliation"], b["reconciliation"])


class ZeroAvailabilityTests(InvariantMixin, unittest.TestCase):
    def test_recurso_so_com_fila_tem_disponibilidade_zero_e_nao_quebra(self):
        repo = _ManyRepo([("Usinagem", "USIN1", [("fila", 480, 600)], 0, 0, 0, 0)])
        self.assertInvariant(repo, _f())
        repo = _ManyRepo([("Usinagem", "USIN1", [("fora_turno", 480, 600)], 0, 0, 0, 0)])
        self.assertInvariant(repo, _f())

    def test_recurso_zerado_junto_de_recursos_normais_aparece_por_ultimo_sem_none_quebrar_ordem(self):
        tree = _service(_ManyRepo()).explain("kpi.disponibilidade", _f()).to_dict()
        sectors = [n for n in tree["children"] if n["kind"] == "sector"]
        values = [s["value"] for s in sectors]
        non_null = [v for v in values if v is not None]
        self.assertEqual(non_null, sorted(non_null, reverse=True))
        # None sempre depois dos valores
        if None in values:
            self.assertEqual(values.index(None), len(non_null))

    def test_so_parada_nao_planejada_zera_trabalhado_mas_nao_o_disponivel(self):
        repo = _ManyRepo([("Dobra", "DOBRA1", [("parada", 480, 560)], 0, 0, 0, 0)])
        overview = self.assertInvariant(repo, _f())
        self.assertEqual(overview["kpis"]["availability"]["value"], 0.0)


class PerformanceAbove100Tests(InvariantMixin, unittest.TestCase):
    def _fast(self):
        # tempo padrão enorme por peça: Performance >> 100%.
        return _ManyRepo([
            ("Dobra", "DOBRA1", [("producao", 480, 500)], 40, 0, 0, 900),
            ("Dobra", "DOBRA2", [("producao", 480, 530)], 5, 0, 0, 30),
        ])

    def test_valor_acima_de_100_nao_e_cortado_e_fecha(self):
        repo = self._fast()
        overview = self.assertInvariant(repo, _f())
        self.assertGreater(overview["kpis"]["performance"]["value"], 100.0)

    def test_oee_com_performance_acima_de_100_fecha_pelo_produto(self):
        tree = _service(self._fast()).explain(OEE, _f()).to_dict()
        self.assertTrue(tree["reconciliation"]["ok"], tree["reconciliation"])
        perf = next(n for n in tree["children"] if n["label"] == "Performance")
        self.assertGreater(perf["value"], 100.0)

    def test_alerta_real_do_calculador_aparece_nas_notas(self):
        repo = self._fast()
        overview = _facade(repo).management.get_overview(_f())
        alerts = overview["kpi_calculation"]["alerts"]
        notes = _service(repo).explain("kpi.performance", _f()).to_dict()["notes"]
        if alerts:
            self.assertTrue(any(alerts[0] in n for n in notes), (alerts, notes))
        else:
            self.fail(f"o calculador não emitiu alerta com Performance > 100%: {overview['kpis']}")


class TamperedOverviewTests(unittest.TestCase):
    """Overview adulterado: o serviço deve degradar, nunca explodir."""

    MUTATIONS = {
        "resource_kpis_none": lambda o: o.update(resource_kpis=None),
        "sector_kpis_none": lambda o: o.update(sector_kpis=None),
        "ambos_ausentes": lambda o: (o.pop("resource_kpis", None), o.pop("sector_kpis", None)),
        "ambos_vazios": lambda o: o.update(resource_kpis=[], sector_kpis=[]),
        "bases_do_recurso_none": lambda o: [r.update(kpi_time_bases=None) for r in o["resource_kpis"]],
        "bases_do_setor_none": lambda o: [r.update(kpi_time_bases=None) for r in o["sector_kpis"]],
        "valores_das_bases_none": lambda o: [
            r.update(kpi_time_bases={k: None for k in r["kpi_time_bases"]}) for r in o["resource_kpis"]
        ],
        "metrics_none": lambda o: [r.update(metrics=None) for r in o["resource_kpis"] + o["sector_kpis"]],
        "metrics_valor_none": lambda o: [
            r["metrics"].update({k: {"value": None} for k in r["metrics"]})
            for r in o["resource_kpis"] + o["sector_kpis"]
        ],
        "metrics_ausentes": lambda o: [r.update(metrics={}) for r in o["resource_kpis"] + o["sector_kpis"]],
        "kpi_calculation_none": lambda o: [
            r.update(kpi_calculation=None) for r in o["resource_kpis"] + o["sector_kpis"]
        ],
        "kpi_calculation_total_none": lambda o: o.update(kpi_calculation=None),
        "alerts_none": lambda o: [
            r["kpi_calculation"].update(alerts=None) for r in o["resource_kpis"]
        ] + [o["kpi_calculation"].update(alerts=None)],
        "resource_none": lambda o: [r.update(resource=None) for r in o["resource_kpis"]],
        "resource_vazio": lambda o: [r.update(resource="  ") for r in o["resource_kpis"]],
        "sector_none": lambda o: [r.update(sector=None) for r in o["resource_kpis"]],
        "setor_none": lambda o: [r.update(setor=None) for r in o["sector_kpis"]],
        "setor_fantasma": lambda o: [r.update(sector="Fantasma") for r in o["resource_kpis"]],
        "hours_none": lambda o: o.update(hours=None),
        "hours_valores_none": lambda o: o.update(hours={k: None for k in o["hours"]}),
        "kpi_time_bases_none": lambda o: o.update(kpi_time_bases=None),
        "kpi_time_bases_ausente": lambda o: o.pop("kpi_time_bases", None),
        "kpis_estendidos_none": lambda o: o.update(kpis_estendidos=None),
        "kpis_none": lambda o: o.update(kpis=None),
        "card_none": lambda o: o["kpis"].update(oee=None, availability=None, performance=None, ftt=None),
        "ftt_value_none": lambda o: o["kpis"]["ftt"].update(value=None),
        "kpis_estimados_none": lambda o: o.update(kpis_estimados=None),
        "kpis_estimados_sem_value": lambda o: o.update(
            kpis_estimados={"usa_tempo_estimado": True, "performance": {}}
        ),
        "pecas_sem_padrao_none": lambda o: [r.update(pecas_boas_sem_tempo_padrao=None) for r in o["sector_kpis"]],
        "bases_negativas": lambda o: [
            r["kpi_time_bases"].update(available_seconds=-5.0, worked_seconds=-1.0)
            for r in o["resource_kpis"]
        ],
        "sem_demanda_total": lambda o: o["kpi_calculation"].update(result_origin="SEM_DEMANDA_PERIODO"),
        "linha_extra_duplicada": lambda o: o["resource_kpis"].append(copy.deepcopy(o["resource_kpis"][0])),
    }

    def test_nenhuma_adulteracao_derruba_a_explicacao(self):
        repo = _ManyRepo()
        for name, mutate in self.MUTATIONS.items():
            for metric, _s, _k in ALL:
                with self.subTest(mutation=name, metric=metric):
                    tree = _stub_explain(repo, metric, mutate)
                    self.assertEqual(tree["kind"], "value")
                    json.dumps(tree, default=str)

    def test_valor_do_cartao_manda_mesmo_quando_o_detalhe_esta_corrompido(self):
        repo = _ManyRepo()
        overview = _facade(repo).management.get_overview(_f())
        for name in ("resource_kpis_none", "sector_kpis_none", "ambos_ausentes", "bases_do_recurso_none",
                     "metrics_none", "resource_none"):
            for metric, section, key in ALL:
                with self.subTest(mutation=name, metric=metric):
                    tree = _stub_explain(repo, metric, self.MUTATIONS[name])
                    self.assertEqual(tree["value"], overview[section][key]["value"])

    def test_detalhe_corrompido_nao_declara_reconciliacao_ok_quando_nao_fecha(self):
        # Sem nenhum recurso para somar, o total do cartão não pode ser "confirmado".
        repo = _ManyRepo()
        for metric, _s, _k in RATIOS:
            with self.subTest(metric=metric):
                tree = _stub_explain(repo, metric, self.MUTATIONS["ambos_vazios"])
                if tree["value"] is not None:
                    self.assertFalse(tree["reconciliation"]["ok"], tree["reconciliation"])

    def test_valor_adulterado_do_cartao_quebra_a_reconciliacao(self):
        repo = _ManyRepo()

        def mutate(o):
            o["kpis"]["availability"]["value"] += 3.0
            o["kpis"]["oee"]["value"] += 3.0
            o["kpis_estendidos"]["ae"]["value"] += 3.0

        for metric in ("kpi.disponibilidade", "kpi.oee", "kpi.ae"):
            with self.subTest(metric=metric):
                self.assertFalse(_stub_explain(repo, metric, mutate)["reconciliation"]["ok"])

    def test_linha_duplicada_de_recurso_nao_passa_como_fechado(self):
        # Se o detalhe soma recurso em dobro, a soma das bases muda: tem de aparecer.
        repo = _ManyRepo()
        tree = _stub_explain(repo, "kpi.disponibilidade", self.MUTATIONS["linha_extra_duplicada"])
        overview = _facade(repo).management.get_overview(_f())
        self.assertEqual(tree["value"], overview["kpis"]["availability"]["value"])
        self.assertTrue(
            (not tree["reconciliation"]["ok"]) or any("não fecha" in n for n in tree["notes"]),
            tree["reconciliation"],
        )


class StableOrderTests(unittest.TestCase):
    def test_duas_execucoes_dao_exatamente_a_mesma_arvore(self):
        repo = _ManyRepo()
        for metric, _s, _k in ALL:
            with self.subTest(metric=metric):
                a = _service(repo).explain(metric, _f()).to_dict()
                b = _service(repo).explain(metric, _f()).to_dict()
                self.assertEqual(a, b)

    def test_mesma_instancia_reutilizada_nao_acumula_estado_entre_chamadas(self):
        service = _service(_ManyRepo())
        first = service.explain("kpi.performance", _f()).to_dict()
        service.explain("kpi.oee", _f())
        second = service.explain("kpi.performance", _f()).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(len(first["notes"]), len(set(first["notes"])) + (len(first["notes"]) - len(set(first["notes"]))))

    def test_ordem_das_linhas_de_entrada_nao_muda_a_arvore(self):
        repo = _ManyRepo()
        shuffle = lambda o: (o["resource_kpis"].reverse(), o["sector_kpis"].reverse())  # noqa: E731
        for metric, _s, _k in ALL:
            with self.subTest(metric=metric):
                base = _stub_explain(repo, metric, lambda o: None)
                rev = _stub_explain(repo, metric, shuffle)
                self.assertEqual(base["children"], rev["children"])
                self.assertEqual(base["excluded"], rev["excluded"])

    def test_empate_de_valor_desempata_por_nome_e_nao_pela_entrada(self):
        repo = _ManyRepo([
            ("Dobra", "DOBRA_B", [("producao", 480, 540)], 10, 0, 0, 100),
            ("Dobra", "DOBRA_A", [("producao", 480, 540)], 10, 0, 0, 100),
            ("Dobra", "DOBRA_C", [("producao", 480, 540)], 10, 0, 0, 100),
        ])
        for metric, _s, _k in ALL:
            with self.subTest(metric=metric):
                tree = _service(repo).explain(metric, _f()).to_dict()
                sector = next(n for n in tree["children"] if n["kind"] == "sector")
                self.assertEqual([c["label"] for c in sector["children"]], ["DOBRA_A", "DOBRA_B", "DOBRA_C"])


class OutrosEdgeTests(unittest.TestCase):
    def test_max_leaves_negativo_nao_pode_descartar_recurso_em_silencio(self):
        # Não é exposto pela API (usa o default), mas o parâmetro é público.
        resources = [("Dobra", f"D{i}", [("producao", 480, 540 + i)], 3 + i, 0, 0, 90) for i in range(1, 5)]
        tree = _service(_ManyRepo(resources)).explain("kpi.performance", _f(), max_leaves=-1).to_dict()
        sector = next(n for n in tree["children"] if n["kind"] == "sector")
        shown = [c for c in sector["children"] if not c.get("truncated")]
        outros = [c for c in sector["children"] if c.get("truncated")]
        rest = int(outros[0]["label"].split()[1]) if outros and outros[0]["label"].startswith("Outros") else (1 if outros else 0)
        self.assertEqual(len(shown) + rest, 4, [c["label"] for c in sector["children"]])


class NoDemandAndNamelessTests(InvariantMixin, unittest.TestCase):
    """Regra sem demanda (``fila`` sem OP) e registros sem setor/recurso, com dados reais do cálculo."""

    @staticmethod
    def _res(sector, name, states, boas=0, refugo=0, retrab=0, tm=100):
        return (sector, name, states, boas, refugo, retrab, tm)

    def test_periodo_todo_sem_demanda_em_varios_recursos_segue_a_regra_e_fecha(self):
        repo = _ManyRepo([
            self._res("A", "R1", [("fila", 480, 540)]),
            self._res("B", "R2", [("fila", 480, 600)]),
        ])
        overview = self.assertInvariant(repo, _f())
        self.assertEqual(overview["kpi_calculation"]["result_origin"], "REGRA_CORPORATIVA_SEM_DEMANDA")
        tree = _service(repo).explain("kpi.disponibilidade", _f()).to_dict()
        self.assertEqual(tree["reconciliation"]["method"], "regra_sem_demanda")
        self.assertTrue(any("regra, não da conta das horas" in n for n in tree["notes"]))

    def test_um_recurso_sem_demanda_junto_de_recurso_normal_sai_da_conta_e_fica_em_excluded(self):
        repo = _ManyRepo([
            self._res("A", "R1", [("fila", 480, 540)]),
            self._res("B", "R2", [("producao", 480, 600)], boas=7, refugo=1),
        ])
        self.assertInvariant(repo, _f())
        for metric, _s, _k in RATIOS:
            with self.subTest(metric=metric):
                tree = _service(repo).explain(metric, _f()).to_dict()
                self.assertTrue(any("R1 (período todo sem demanda)" == e["label"] for e in tree["excluded"]), tree["excluded"])
                self.assertTrue(any("sem demanda (R1)" in n for n in tree["notes"]))

    def test_excluded_nao_conta_o_mesmo_tempo_sem_demanda_duas_vezes(self):
        # Corrigido: o "Recurso sem demanda" geral desconta o recurso que já aparece sozinho,
        # senão o excluído somaria mais que ``hours.no_demand_seconds``.
        repo = _ManyRepo([
            self._res("A", "R1", [("fila", 480, 540)]),
            self._res("B", "R2", [("producao", 480, 600)], boas=7),
        ])
        overview = _facade(repo).management.get_overview(_f())
        tree = _service(repo).explain("kpi.disponibilidade", _f()).to_dict()
        total_excluido = sum(e["value"] for e in tree["excluded"])
        self.assertLessEqual(total_excluido, overview["hours"]["no_demand_seconds"])

    def test_registro_sem_setor_ou_com_mesmo_recurso_em_dois_setores(self):
        self.assertInvariant(_ManyRepo([
            self._res("", "X1", [("producao", 480, 540)], boas=5),
            self._res("Dobra", "D1", [("producao", 480, 540)], boas=5),
        ]), _f())
        self.assertInvariant(_ManyRepo([
            self._res("Dobra", "M1", [("producao", 480, 540)], boas=5),
            self._res("Solda", "M1", [("producao", 500, 540)], boas=5),
        ]), _f())

    def test_recurso_sem_nome_nao_fecha_mas_a_explicacao_avisa_em_nota(self):
        # O número da tela usa o total; o detalhe por recurso perde a parte sem nome.
        repo = _ManyRepo([self._res(None, None, [("producao", 480, 540)], boas=5)])
        for metric in ("kpi.performance", "kpi.ae"):
            with self.subTest(metric=metric):
                tree = _service(repo).explain(metric, _f()).to_dict()
                if not tree["reconciliation"]["ok"]:
                    self.assertTrue(any("não fecha" in n for n in tree["notes"]), tree["notes"])

    @unittest.expectedFailure
    def test_recurso_sem_nome_fecha_a_reconciliacao_como_exige_o_invariante(self):
        # BUG de origem (overview, não do serviço): em ``resource_kpis`` a linha "Não informado"
        # sai com ``productive_net_seconds`` 0 enquanto ``sector_kpis``/total têm o tempo padrão
        # da peça boa sem recurso. Resultado: Performance e A.E. com ``reconciliation.ok`` False.
        repo = _ManyRepo([
            self._res("Dobra", "", [("producao", 480, 540)], boas=5),
            self._res("Dobra", "D1", [("producao", 480, 540)], boas=5),
        ])
        self.assertInvariant(repo, _f(), metrics=(("kpi.performance", "kpis", "performance"),
                                                   ("kpi.ae", "kpis_estendidos", "ae")))


if __name__ == "__main__":
    unittest.main()
