"""QA adversarial da aba Diretoria (16/10/2026): casos de borda fora dos testes do autor."""

from __future__ import annotations

import json
import unittest
from unittest import mock
from datetime import datetime, timedelta
from decimal import Decimal

from mes.services.director_summary import DirectorSummaryService
from tests.test_director_api import BASE, _ApiCase
from tests.test_director_summary import NOW, _h, _Repo, _state, _with_rates


def _svc(states, *, participations=None, quantities=None, rates=True):
    repo = _Repo(states=states, quantities=quantities or [], participations=participations or [])
    if rates:
        _with_rates(repo)
    return repo, DirectorSummaryService(repo)


def _finite(testcase, payload):
    # allow_nan=False levanta se houver NaN/Infinity em qualquer lugar.
    testcase.assertTrue(json.dumps(payload, allow_nan=False))


class EmptyAndBoundaryTests(unittest.TestCase):
    def test_banco_totalmente_vazio_sem_nan_nem_divisao_por_zero(self):
        _repo, svc = _svc([], rates=False)
        for period in ("hoje", "semana", "mes"):
            _finite(self, svc.panel(period, NOW))
            for setor, recurso in ((None, None), ("Corte", None), (None, "LASER1"), ("nada", "nada")):
                sheet = svc.sheet(period, setor, recurso, NOW)
                _finite(self, sheet)
                self.assertEqual(sheet["custo_parada"], 0.0)

    def test_parada_atravessando_meia_noite_corta_no_inicio_do_periodo(self):
        # LASER1 parado dia0 22:00 -> dia1 03:00 (5 h); "hoje" do dia1 so enxerga 3 h.
        states = [_state(1, "LASER1", "Corte", "parada", _h(0, 22), _h(1, 3), motivo="quebra")]
        _repo, svc = _svc(states)
        now = _h(1, 18)
        sheet = svc.sheet("hoje", None, "LASER1", now)
        panel = svc.panel("hoje", now)
        self.assertAlmostEqual(sheet["parado_h"], 3.0)
        self.assertAlmostEqual(sum(r["horas"] for r in sheet["paradas_por_motivo"]), 3.0)
        self.assertEqual(sheet["custo_parada"], 3 * 150.0)  # sem pessoas
        self.assertAlmostEqual(panel["cards"]["horas_paradas"], 3.0)
        self.assertEqual(panel["cards"]["custo_parada"], 450.0)

    def test_parada_em_andamento_atravessando_meia_noite_conta_uma_vez(self):
        states = [_state(1, "LASER1", "Corte", "parada", _h(3, 22), None, motivo="quebra")]
        _repo, svc = _svc(states)
        now = _h(4, 3)
        # O repositorio em memoria corta estado aberto em NOW do modulo; alinha com o relogio do teste.
        patcher = mock.patch("tests.test_director_summary.NOW", now)
        patcher.start()
        self.addCleanup(patcher.stop)
        for period, expected in (("hoje", 3.0), ("semana", 5.0)):
            sheet = svc.sheet(period, None, "LASER1", now)
            self.assertAlmostEqual(sheet["parado_h"], expected, msg=period)
            self.assertEqual(sheet["custo_parada"], expected * 150.0, period)

    def test_parada_atravessando_virada_de_mes_e_de_semana(self):
        # Domingo 11/10 22:00 -> segunda 12/10 02:00
        states = [_state(1, "LASER1", "Corte", "parada", _h(0, -2), _h(0, 2), motivo="quebra")]
        _repo, svc = _svc(states)
        sheet = svc.sheet("semana", None, "LASER1", _h(0, 10))
        self.assertAlmostEqual(sheet["parado_h"], 2.0)
        # 30/09 22:00 -> 01/10 02:00
        states = [_state(1, "LASER1", "Corte", "parada", datetime(2026, 9, 30, 22), datetime(2026, 10, 1, 2),
                         motivo="quebra")]
        _repo, svc = _svc(states)
        sheet = svc.sheet("mes", None, "LASER1", datetime(2026, 10, 1, 10))
        self.assertAlmostEqual(sheet["parado_h"], 2.0)

    def test_motivos_sobrepostos_no_mesmo_recurso_horas_batem_com_o_custo(self):
        # Duas paradas simultaneas com motivos diferentes: tempo real parado = 3 h (8-11).
        states = [
            _state(1, "LASER1", "Corte", "parada", _h(0, 8), _h(0, 10), motivo="quebra", op="OP1"),
            _state(2, "LASER1", "Corte", "parada", _h(0, 9), _h(0, 11), motivo="falta de material", op="OP2"),
        ]
        _repo, svc = _svc(states)
        sheet = svc.sheet("semana", None, "LASER1", NOW)
        reasons_total = sum(r["horas"] for r in sheet["paradas_por_motivo"])
        self.assertAlmostEqual(sheet["parado_h"], reasons_total, msg=(sheet["parado_h"], sheet["paradas_por_motivo"]))
        self.assertEqual(sheet["custo_parada"], sheet["parado_h"] * 150.0)

    def test_pessoa_em_dois_recursos_com_inicio_identico_conta_uma_vez(self):
        states = [
            _state(1, "LASER1", "Corte", "producao", _h(0, 8), _h(0, 12)),
            _state(2, "DOBRA1", "Dobra", "producao", _h(0, 8), _h(0, 12)),
        ]

        def part(pid, recurso, setor):
            return {"id": pid, "cracha": "200", "cracha_resolvido": "200", "operador_id": 2, "nome": "Bruno",
                    "nome_resolvido": "Bruno", "recurso": recurso, "tipo_setor": setor,
                    "data_inicio": _h(0, 8), "data_fim": _h(0, 12)}

        _repo, svc = _svc(states, participations=[part(1, "LASER1", "Corte"), part(2, "DOBRA1", "Dobra")])
        fabrica = svc.sheet("semana", None, None, NOW)
        bruno = [p for p in fabrica["pessoas"] if p["nome"] == "Bruno"]
        self.assertEqual(len(bruno), 1)
        self.assertAlmostEqual(bruno[0]["horas"], 4.0)
        self.assertEqual(bruno[0]["custo"], 4 * 50.0)

    def test_participacao_aberta_nao_passa_de_agora(self):
        states = [_state(1, "LASER1", "Corte", "parada", _h(0, 8), None, motivo="quebra")]
        patcher = mock.patch("tests.test_director_summary.NOW", _h(0, 10))
        patcher.start()
        self.addCleanup(patcher.stop)
        part = {"id": 1, "cracha": "100", "cracha_resolvido": "100", "operador_id": 1, "nome": "Ana",
                "nome_resolvido": "Ana", "recurso": "LASER1", "tipo_setor": "Corte",
                "data_inicio": _h(0, 0), "data_fim": None}
        _repo, svc = _svc(states, participations=[part])
        sheet = svc.sheet("semana", None, "LASER1", _h(0, 10))  # agora = 10h: parada ja "terminou" no futuro
        self.assertAlmostEqual(sheet["parado_h"], 2.0)
        self.assertEqual(sheet["custo_parada"], 500.0)  # 2 h x (150 + Ana 100); Ana nao passa de agora

    def test_taxa_do_recurso_so_com_pessoa_sem_taxa(self):
        states = [_state(1, "LASER1", "Corte", "parada", _h(0, 8), _h(0, 10), motivo="quebra")]
        part = {"id": 1, "cracha": "200", "cracha_resolvido": "200", "operador_id": 2, "nome": "Bruno",
                "nome_resolvido": "Bruno", "recurso": "LASER1", "tipo_setor": "Corte",
                "data_inicio": _h(0, 0), "data_fim": _h(0, 23)}
        repo, svc = _svc(states, participations=[part])
        del repo.operator_rates[2]
        panel = svc.panel("semana", NOW)
        self.assertEqual(panel["cards"]["custo_parada"], 300.0)
        self.assertFalse(panel["custo_completo"])
        self.assertEqual(panel["custos_faltando"], 1)

    def test_custos_com_recurso_inexistente_gravado_aparece_sem_setor(self):
        repo, svc = _svc([])
        svc.set_resource_rate("naoexiste", 10, "dir")
        recursos = {r["recurso"]: r for r in svc.costs()["recursos"]}
        self.assertIn("NAOEXISTE", recursos)
        self.assertIsNone(recursos["NAOEXISTE"]["setor"])


class DirectorApiAdversarialTests(_ApiCase):
    def setUp(self):
        self._build(_with_rates(_Repo()))
        self._as("diretoria")

    def _put_raw(self, url, raw):
        return self.client.put(url, content=raw, headers={"content-type": "application/json"})

    def test_put_valores_hostis_nunca_500_e_nunca_gravam(self):
        before = (dict(self.db.resource_rates), dict(self.db.operator_rates))
        hostile = ["0", "-1", "-0.0", "NaN", "Infinity", "-Infinity", "1e308", "1e999", "true", "false",
                   "null", '"12"', '"NaN"', "[]", "{}", "1e-5", "0.004", "10000000000", "9999999999.995",
                   "1" + "0" * 400, "-" + "1" + "0" * 400, "[10]", '{"a":1}']
        for url in (f"{BASE}/custos/recurso/LASER1", f"{BASE}/custos/pessoa/1"):
            for raw in hostile:
                response = self._put_raw(url, '{"valor_hora": %s}' % raw)
                self.assertLess(response.status_code, 500, (url, raw, response.text[:200]))
                self.assertEqual(response.status_code, 422, (url, raw, response.status_code))
        self.assertEqual((self.db.resource_rates, self.db.operator_rates), before)

    def test_put_valores_limite_validos(self):
        for raw, expected in (("0.01", "0.01"), ("12.345", "12.35"), ("9999999999.99", "9999999999.99"),
                              ("1e2", "100.00")):
            response = self._put_raw(f"{BASE}/custos/recurso/LASER1", '{"valor_hora": %s}' % raw)
            self.assertEqual(response.status_code, 200, (raw, response.text))
            self.assertEqual(self.db.resource_rates["LASER1"], Decimal(expected), raw)

    def test_put_corpo_nao_json_ou_vazio(self):
        for raw in ("", "nao-json", "[]", '{"valor_hora": 10,'):
            response = self._put_raw(f"{BASE}/custos/recurso/LASER1", raw)
            self.assertIn(response.status_code, (400, 422), (raw, response.status_code, response.text[:200]))

    def test_put_recurso_inexistente_e_so_espacos(self):
        spaces = self.client.put(f"{BASE}/custos/recurso/%20%20", json={"valor_hora": 10})
        self.assertEqual(spaces.status_code, 422, spaces.text)
        ghost = self.client.put(f"{BASE}/custos/recurso/RECURSO_FANTASMA", json={"valor_hora": 10})
        # Documenta o comportamento: aceita e grava recurso fora do catalogo.
        self.assertIn(ghost.status_code, (200, 404, 422), ghost.text)
        long = self.client.put(f"{BASE}/custos/recurso/{'A' * 81}", json={"valor_hora": 10})
        self.assertEqual(long.status_code, 422, long.text)

    def test_put_pessoa_ids_extremos(self):
        for oid in ("0", "-1", "1.5", "9" * 30, "abc"):
            response = self.client.put(f"{BASE}/custos/pessoa/{oid}", json={"valor_hora": 10})
            self.assertIn(response.status_code, (404, 422), (oid, response.status_code, response.text[:200]))
        self.assertEqual(self.db.operator_rates, {1: Decimal("100"), 2: Decimal("50"), 3: Decimal("40")})

    def test_periodos_invalidos_e_filtros_hostis(self):
        for periodo in ("", " ", "ano", "hoje;drop", "a" * 21, "%00", "../x", "HOJE", " Mes "):
            for path in ("painel", "ficha"):
                response = self.client.get(f"{BASE}/{path}", params={"periodo": periodo})
                self.assertLess(response.status_code, 500, (path, periodo, response.text[:200]))
        for params in ({"setor": "x' OR 1=1 --"}, {"recurso": "%"}, {"setor": "a" * 61}, {"recurso": "a" * 81},
                       {"setor": "Corte", "recurso": "DOBRA1"}, {"setor": "  "}):
            response = self.client.get(f"{BASE}/ficha", params={"periodo": "semana", **params})
            self.assertLess(response.status_code, 500, (params, response.text[:200]))

    def test_ficha_painel_costs_sem_nan_no_json(self):
        for path in ("painel?periodo=mes", "ficha?periodo=mes", "ficha?periodo=hoje&setor=Solda", "custos"):
            response = self.client.get(f"{BASE}/{path}")
            self.assertEqual(response.status_code, 200, (path, response.text[:200]))
            self.assertNotIn("NaN", response.text)
            self.assertNotIn("Infinity", response.text)

    def test_niveis_gestor_lider_pcp_e_sem_sessao_nunca_veem_r(self):
        from backend.api.dependencies.auth import get_current_user
        before = (dict(self.db.resource_rates), dict(self.db.operator_rates))
        for level in ("gestor", "lider", "pcp"):
            self._as(level)
            for url in (f"{BASE}/painel", f"{BASE}/ficha", f"{BASE}/custos"):
                self.assertEqual(self.client.get(url).status_code, 403, (level, url))
            for url in (f"{BASE}/custos/recurso/LASER1", f"{BASE}/custos/pessoa/1"):
                self.assertEqual(self.client.put(url, json={"valor_hora": 1}).status_code, 403, (level, url))
        self.app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(self.client.get(f"{BASE}/custos").status_code, 401)
        self.assertEqual((self.db.resource_rates, self.db.operator_rates), before)


if __name__ == "__main__":
    unittest.main()
