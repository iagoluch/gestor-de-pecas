"""QA adversarial do Lote 4 (``dir.*``, 20/10/2026): tenta quebrar a conta aberta da Diretoria.

Foco em dinheiro: custo faltando nunca vira número inventado, valor 0 cadastrado
não se confunde com "não cadastrado", os filhos somam o total mostrado, o painel
e a conta aberta concordam, entradas hostis viram erro estruturado (nunca 500) e
quem não é da Diretoria nunca recebe R$.
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal

from app.core.permissions import USER_LEVELS
from backend.api.dependencies.auth import get_current_user
from mes.services.director_explanation import METRICS, DirectorExplanationService
from mes.services.director_summary import DirectorSummaryError, DirectorSummaryService
from tests.test_director_api import BASE, _ApiCase
from tests.test_director_summary import NOW, _Repo, _with_rates

PERIODS = ("hoje", "semana", "mes")


def _kwargs(metric):
    if metric == "dir.custo_setor":
        return {"setor": "Corte"}
    if metric == "dir.valor_hora":
        return {"recurso": "LASER1"}
    return {}


def _explain(repo, metric, period="semana", **kwargs):
    return DirectorExplanationService(repo).explain(metric, period, now=NOW, **kwargs).to_dict()


def _error(repo, period="semana", **kwargs):
    with unittest.TestCase().assertRaises(DirectorSummaryError) as raised:
        DirectorExplanationService(repo).explain(period=period, now=NOW, **kwargs)
    return raised.exception


def _walk(node):
    yield node
    for child in node.get("children") or ():
        yield from _walk(child)


class MoneyIntegrityTests(unittest.TestCase):
    def test_conferencia_fecha_em_todos_os_periodos_com_e_sem_cadastro(self):
        repos = (_with_rates(_Repo()), _Repo(), _Repo(states=[], quantities=[], participations=[]))
        for repo in repos:
            for period in PERIODS:
                for metric in METRICS:
                    tree = _explain(repo, metric, period, **_kwargs(metric))
                    self.assertTrue(tree["reconciliation"]["ok"], (period, metric, tree["reconciliation"]))

    def test_cada_no_de_custo_soma_seus_filhos_ao_centavo(self):
        repo = _with_rates(_Repo())
        for metric in ("dir.custo_parada", "dir.custo_trabalho"):
            tree = _explain(repo, metric)
            for node in _walk({"children": tree["children"], "value": tree["value"]}):
                kids = node.get("children") or []
                if kids:
                    self.assertAlmostEqual(
                        node["value"], sum(k["value"] for k in kids), delta=0.01 * len(kids),
                        msg=(metric, node.get("label")),
                    )

    def test_arredondamento_com_valores_quebrados_continua_conferindo(self):
        for rate in ("33.333", "0.015", "99999.995", "0.01", "1234.5678"):
            repo = _with_rates(_Repo())
            repo.resource_rates["LASER1"] = Decimal(rate)
            repo.operator_rates[1] = Decimal(rate) / 3
            repo.operator_rates[2] = Decimal(rate) / 7
            repo.operator_rates[3] = Decimal("0.005")
            for metric in ("dir.custo_parada", "dir.custo_trabalho", "dir.custo_setor"):
                tree = _explain(repo, metric, **_kwargs(metric))
                self.assertTrue(tree["reconciliation"]["ok"], (rate, metric, tree["reconciliation"]))

    def test_conta_aberta_bate_com_o_painel(self):
        repo = _with_rates(_Repo())
        for period in PERIODS:
            panel = DirectorSummaryService(repo).panel(period, NOW)
            self.assertEqual(_explain(repo, "dir.custo_parada", period)["value"], panel["cards"]["custo_parada"], period)
            self.assertEqual(_explain(repo, "dir.horas_paradas", period)["value"], panel["cards"]["horas_paradas"], period)
            self.assertEqual(_explain(repo, "dir.produzido", period)["value"], panel["cards"]["produzido"], period)
            for sector in panel["onde_perdemos"]:
                tree = _explain(repo, "dir.custo_setor", period, setor=sector["setor"])
                self.assertEqual(tree["value"], sector["custo"], (period, sector["setor"]))

    def test_soma_dos_setores_do_painel_e_o_custo_da_parada(self):
        repo = _with_rates(_Repo())
        panel = DirectorSummaryService(repo).panel("semana", NOW)
        total = sum(_explain(repo, "dir.custo_setor", setor=s["setor"])["value"] for s in panel["onde_perdemos"])
        self.assertAlmostEqual(total, _explain(repo, "dir.custo_parada")["value"], places=2)


class MissingRateTests(unittest.TestCase):
    def test_maquina_sem_valor_nao_inventa_numero_e_avisa(self):
        repo = _with_rates(_Repo())
        full = _explain(repo, "dir.custo_parada")
        del repo.resource_rates["LASER1"]
        tree = _explain(repo, "dir.custo_parada")
        self.assertLess(tree["value"], full["value"])
        self.assertGreater(tree["value"], 0)
        self.assertTrue(tree["reconciliation"]["ok"])
        laser = [n for n in _walk({"children": tree["children"]}) if n.get("kind") == "resource" and "Laser" in n["label"]]
        self.assertEqual(len(laser), 1)
        machine = [k for k in laser[0]["children"] if k["label"].startswith("Máquina")]
        self.assertEqual(machine[0]["value"], 0.0)
        self.assertIn("não cadastrado", machine[0]["label"])
        notes = " ".join(tree["notes"])
        self.assertIn("Sem valor da hora cadastrado", notes)
        self.assertIn("Laser", notes)

    def test_pessoa_sem_valor_e_citada_pelo_nome(self):
        repo = _with_rates(_Repo())
        del repo.operator_rates[1]  # Ana
        tree = _explain(repo, "dir.custo_parada")
        self.assertIn("Ana", " ".join(tree["notes"]))
        self.assertTrue(tree["reconciliation"]["ok"])

    def test_sem_nenhum_valor_o_total_e_zero_nunca_negativo_ou_nulo(self):
        repo = _Repo()
        for metric in ("dir.custo_parada", "dir.custo_trabalho", "dir.custo_setor"):
            tree = _explain(repo, metric, **_kwargs(metric))
            self.assertEqual(tree["value"], 0)
            self.assertIsNotNone(tree["value"])
            self.assertTrue(any("valor da hora" in n.lower() for n in tree["notes"]), (metric, tree["notes"]))
            for top in tree["children"]:
                for node in _walk(top):
                    self.assertIsNotNone(node.get("value"), (metric, node.get("label")))
                    self.assertGreaterEqual(node["value"], 0)

    def test_valor_zero_cadastrado_nao_e_o_mesmo_que_nao_cadastrado(self):
        repo = _with_rates(_Repo())
        repo.resource_rates["LASER1"] = Decimal("0")
        zero = _explain(repo, "dir.valor_hora", recurso="LASER1")
        self.assertEqual(zero["value"], 0.0)
        self.assertIsNotNone(zero["value"])
        del repo.resource_rates["LASER1"]
        none = _explain(repo, "dir.valor_hora", recurso="LASER1")
        self.assertIsNone(none["value"])
        self.assertIn("Nenhum valor da hora cadastrado", none["reason"])
        self.assertNotIn("R$ 0", none["reason"])

    def test_valor_hora_recurso_desconhecido_ou_pessoa_sem_valor_e_nulo(self):
        repo = _with_rates(_Repo())
        self.assertIsNone(_explain(repo, "dir.valor_hora", recurso="NAO_EXISTE_9")["value"])
        del repo.operator_rates[1]
        person = _explain(repo, "dir.valor_hora", pessoa="1")
        self.assertIsNone(person["value"])
        self.assertTrue(all("sem valor cadastrado" in c["label"] for c in person["children"]), person["children"])

    def test_valor_hora_e_o_do_cadastro_com_recurso_em_minusculas(self):
        repo = _with_rates(_Repo())
        self.assertEqual(_explain(repo, "dir.valor_hora", recurso=" laser1 ")["value"], 150.0)


class HostileInputTests(unittest.TestCase):
    def setUp(self):
        self.repo = _with_rates(_Repo())

    def test_custo_setor_e_valor_hora_sem_alvo(self):
        for setor in (None, "", "   "):
            err = _error(self.repo, metric="dir.custo_setor", setor=setor)
            self.assertEqual((err.code, err.status_code), ("SECTOR_REQUIRED", 422), setor)
        for kwargs in ({}, {"recurso": "  ", "pessoa": " "}, {"recurso": None, "pessoa": None}):
            err = _error(self.repo, metric="dir.valor_hora", **kwargs)
            self.assertEqual((err.code, err.status_code), ("RATE_TARGET_REQUIRED", 422), kwargs)

    def test_pessoa_inexistente_ou_nao_numerica_e_404_nunca_500(self):
        for person in ("999", "abc", "01", "1.0", "-1", "1; DROP TABLE x", "１", "0", "1 2", "١"):
            err = _error(self.repo, metric="dir.valor_hora", pessoa=person)
            self.assertEqual((err.code, err.status_code), ("UNKNOWN_PERSON", 404), person)

    def test_periodo_invalido(self):
        for period in ("", "ano", "ontem", "hoje;", "semana semana", None, "../x"):
            err = _error(self.repo, period=period, metric="dir.produzido")
            self.assertEqual((err.code, err.status_code), ("INVALID_PERIOD", 422), period)

    def test_periodo_aceita_caixa_e_espacos(self):
        self.assertEqual(
            _explain(self.repo, "dir.custo_parada", " SEMANA ")["value"],
            _explain(self.repo, "dir.custo_parada", "semana")["value"],
        )

    def test_metric_desconhecida(self):
        for metric in ("kpi.oee", "qtd.boa", "DIR.PRODUZIDO", "dir.", "dir.custo_parada;", "dir.custo parada", None, "x" * 500):
            err = _error(self.repo, metric=metric)
            self.assertEqual((err.code, err.status_code), ("UNKNOWN_METRIC", 422), metric)

    def test_metric_com_espacos_nas_pontas_e_aceita(self):
        self.assertEqual(_explain(self.repo, " dir.produzido ")["metric"], "dir.produzido")

    def test_setor_com_caracteres_estranhos_nao_quebra_nem_inventa_custo(self):
        for setor in ("Co'rte; DROP TABLE x;--", "%", "_", "Corte\x00", "Çorte​", "<script>alert(1)</script>",
                      "\\", "../../etc", "Corte\nDobra", "😀", "x" * 60):
            tree = _explain(self.repo, "dir.custo_setor", setor=setor)
            self.assertEqual(tree["value"], 0, setor)
            self.assertTrue(tree["reconciliation"]["ok"], setor)

    def test_setor_e_recurso_estranhos_nos_outros_numeros(self):
        for metric in ("dir.custo_parada", "dir.custo_trabalho", "dir.produzido", "dir.horas_paradas",
                       "dir.trabalhou", "dir.parado_motivo", "dir.eficiencia"):
            for extra in ({"setor": "Co'rte;--"}, {"recurso": "%_\\"}, {"setor": "😀", "recurso": "\x00"}):
                tree = _explain(self.repo, metric, **extra)
                self.assertTrue(tree["reconciliation"]["ok"], (metric, extra))

    def test_recurso_e_pessoa_juntos_recurso_vence_sem_misturar(self):
        tree = _explain(self.repo, "dir.valor_hora", recurso="LASER1", pessoa="2")
        self.assertEqual(tree["value"], 150.0)

    def test_setor_em_caixa_diferente_acha_o_mesmo_custo(self):
        # Regressão: ``setor=corte`` já devolveu R$ 0 por comparar com ``==``.
        self.assertEqual(_explain(self.repo, "dir.custo_setor", setor="corte")["value"], 2250.0)


class DirectorExplanationApiAdversarialTests(_ApiCase):
    def setUp(self):
        self._build(_with_rates(_Repo()))
        self._as("diretoria")

    def _get(self, **params):
        return self.client.get(f"{BASE}/explicacao", params=params)

    def test_erros_estruturados_com_codigo_na_rota(self):
        cases = (
            (dict(metric="dir.custo_setor"), 422, "SECTOR_REQUIRED"),
            (dict(metric="dir.custo_setor", setor="   "), 422, "SECTOR_REQUIRED"),
            (dict(metric="dir.valor_hora"), 422, "RATE_TARGET_REQUIRED"),
            (dict(metric="dir.valor_hora", pessoa="abc"), 404, "UNKNOWN_PERSON"),
            (dict(metric="dir.valor_hora", pessoa="999"), 404, "UNKNOWN_PERSON"),
            (dict(metric="dir.produzido", periodo="ano"), 422, "INVALID_PERIOD"),
            (dict(metric="dir.produzido", periodo=""), 422, "INVALID_PERIOD"),
            (dict(metric="kpi.oee"), 422, "UNKNOWN_METRIC"),
            (dict(metric="dir.nada"), 422, "UNKNOWN_METRIC"),
        )
        for params, status, code in cases:
            response = self._get(**params)
            self.assertEqual(response.status_code, status, (params, response.text))
            self.assertEqual(response.json().get("code"), code, (params, response.text))
            self.assertNotIn("Traceback", response.text)

    def test_limites_de_tamanho_viram_422_de_validacao(self):
        for params in (
            dict(metric="x" * 65),
            dict(metric="dir.produzido", periodo="p" * 21),
            dict(metric="dir.custo_setor", setor="s" * 61),
            dict(metric="dir.valor_hora", recurso="r" * 81),
            dict(metric="dir.valor_hora", pessoa="1" * 21),
            dict(metric=""),
        ):
            response = self._get(**params)
            self.assertEqual(response.status_code, 422, (params, response.text))

    def test_parametros_hostis_na_url_nao_geram_500(self):
        for setor in ("Co'rte;--", "%25", "%00", "<b>", "😀", "..%2F..", "Corte%0AX"):
            response = self.client.get(f"{BASE}/explicacao?metric=dir.custo_setor&setor={setor}")
            self.assertIn(response.status_code, (200, 422), (setor, response.text))
            if response.status_code == 200:
                self.assertEqual(response.json()["value"], 0, setor)
        response = self.client.get(f"{BASE}/explicacao?metric=dir.valor_hora&pessoa=1%27%20OR%201%3D1")
        self.assertEqual(response.status_code, 404, response.text)

    def test_resposta_de_valor_hora_sem_cadastro_nao_vira_zero_no_json(self):
        self._build(_Repo())
        self._as("diretoria")
        body = self._get(metric="dir.valor_hora", recurso="LASER1").json()
        self.assertIsNone(body["value"])
        self.assertEqual(body["kind"], "value")

    def test_custo_incompleto_via_rota_avisa_e_confere(self):
        self._build(_Repo())
        self._as("diretoria")
        for params in (dict(metric="dir.custo_parada"), dict(metric="dir.custo_setor", setor="Corte")):
            body = self._get(**params, periodo="semana").json()
            self.assertEqual(body["value"], 0)
            self.assertTrue(body["reconciliation"]["ok"])
            self.assertTrue(any("valor da hora" in n.lower() for n in body["notes"]), body["notes"])

    def test_todo_nivel_sem_diretoria_recebe_403_em_qualquer_metrica_e_sem_valor(self):
        others = [level for level in USER_LEVELS if level not in ("admin", "diretoria")]
        for level in others:
            self._as(level)
            for params in (
                dict(metric="dir.custo_parada"),
                dict(metric="dir.valor_hora", recurso="LASER1"),
                dict(metric="dir.valor_hora", pessoa="1"),
                dict(metric="dir.custo_setor", setor="Corte"),
                dict(metric="dir.invalida"),   # a porta barra antes de validar
                dict(),                         # nem a validação vaza antes da porta
            ):
                response = self._get(**params)
                self.assertEqual(response.status_code, 403, (level, params, response.text))
                # request_id é UUID aleatório: pode conter "8110" por acaso e não é valor vazado.
                body = {k: v for k, v in response.json().items() if k != "request_id"}
                text = json.dumps(body, ensure_ascii=False)
                for leaked in ("2460", "2250", "8110", "valor_hora", '"value"', "R$"):
                    self.assertNotIn(leaked, text, (level, params))

    def test_operador_explicitamente_recebe_403(self):
        self._as("operador")
        response = self._get(metric="dir.custo_parada")
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "director_access_denied")

    def test_sem_sessao_401_mesmo_com_parametro_invalido(self):
        self.app.dependency_overrides.pop(get_current_user, None)
        self.assertEqual(self._get(metric="dir.custo_parada").status_code, 401)
        self.assertEqual(self.client.get(f"{BASE}/explicacao").status_code, 401)

    def test_rota_de_gestao_recusa_dir_para_todo_nivel_e_nunca_devolve_r(self):
        for level in USER_LEVELS:
            self._as(level)
            for metric in METRICS:
                response = self.client.get(
                    "/api/v1/management/explicacao", params={"metric": metric, "periodo": "semana"}
                )
                self.assertIn(response.status_code, (403, 422), (level, metric, response.status_code))
                if response.status_code == 422 and level in ("admin", "diretoria"):
                    self.assertEqual(response.json().get("code"), "unknown_metric", (level, metric, response.text))
                for leaked in ("2460", "8110", '"value"', "R$"):
                    self.assertNotIn(leaked, response.text.split('"request_id"')[0], (level, metric))

    def test_diretoria_abre_todas_as_metricas_pela_rota_e_confere(self):
        for metric in METRICS:
            params = {"metric": metric, "periodo": "semana", **_kwargs(metric)}
            response = self._get(**params)
            self.assertEqual(response.status_code, 200, (metric, response.text))
            body = response.json()
            self.assertTrue(body["reconciliation"]["ok"], (metric, body["reconciliation"]))
            self.assertEqual(body["metric"], metric)


if __name__ == "__main__":
    unittest.main()
