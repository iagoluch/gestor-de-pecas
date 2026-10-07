"""Tempo padrão manual e estimado (06/10/2026): domínio, serviço, gestão e API.

Sem banco: o SQL real (migration 56, consulta de fatos, repositório) é coberto
por ``tests/test_standard_time_postgres.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import unittest

from fastapi.testclient import TestClient

from app.core.permissions import can_manage_standard_time
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import _recalculate_standard_time_estimates_if_due, create_app
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.domain.standard_time import (
    drop_outliers,
    estimate_standard_seconds,
    normalize_key,
    official_standard_seconds,
    estimated_view_standard_seconds,
    percentile,
    resolve_fact_standard,
)
from mes.services.display_labels import role_label
from mes.services.industrial_analytics import IndustrialAnalyticsService
from mes.services.management import ManagementService
from mes.services import standard_time as standard_time_module
from mes.services.standard_time import (
    ESTIMATE_EVENT_TYPE,
    RECALCULATION_BUSY_CODE,
    StandardTimeRecalculationBusy,
    StandardTimeRuleError,
    StandardTimeService,
)
from tests.fakes import FakeDatabase
from tests.test_industrial_analytics import _ManagementRepo

NOW = datetime(2026, 10, 6, 9, 0)


class StandardTimeDomainTests(unittest.TestCase):
    def test_percentil_25_por_interpolacao_linear(self):
        self.assertEqual(percentile([50, 10, 30, 20, 40], 25), 20)
        self.assertAlmostEqual(percentile([10, 20, 30, 40], 25), 17.5)

    def test_outlier_fora_de_1_5_iqr_e_descartado(self):
        self.assertEqual(drop_outliers([10, 10, 10, 10, 10, 100]), [10, 10, 10, 10, 10])

    def test_estimativa_exige_5_amostras_depois_do_descarte(self):
        self.assertIsNone(estimate_standard_seconds([10, 12, 14, 16]))
        # 5 valores brutos, mas 1 outlier: sobram 4, não vira padrão.
        self.assertIsNone(estimate_standard_seconds([10, 11, 12, 13, 500]))
        estimate = estimate_standard_seconds([10, 12, 14, 16, 18])
        self.assertEqual(estimate.segundos_por_peca, 12)
        self.assertEqual((estimate.amostras, estimate.amostras_brutas), (5, 5))

    def test_estimativa_ignora_valores_nao_positivos(self):
        self.assertIsNone(estimate_standard_seconds([0, -3, None, 10, 12, 14, 16]))

    def test_prioridade_e_visoes_oficial_e_estimada(self):
        protheus = {"tempo_padrao_segundos": 30.0, "tempo_padrao_fonte": "protheus"}
        manual = {"tempo_padrao_segundos": 31.0, "tempo_padrao_fonte": "manual"}
        estimado = {"tempo_padrao_segundos": 32.0, "tempo_padrao_fonte": "estimado"}
        vazio = {"tempo_padrao_segundos": None, "tempo_padrao_fonte": None}
        self.assertEqual(official_standard_seconds(protheus), 30.0)
        self.assertEqual(official_standard_seconds(manual), 31.0)
        self.assertIsNone(official_standard_seconds(estimado))
        self.assertEqual(estimated_view_standard_seconds(estimado), 32.0)
        self.assertEqual(resolve_fact_standard(vazio), (None, None))

    def test_fato_legado_so_com_tempo_medio_vale_como_protheus(self):
        self.assertEqual(resolve_fact_standard({"tempo_medio_segundos": 500.0}), (500.0, "protheus"))
        self.assertEqual(resolve_fact_standard({"tempo_medio_segundos": None}), (None, None))

    def test_chave_so_remove_espaco_ascii_como_o_btrim_do_sql(self):
        # BTRIM tira só o espaço; tab/NBSP/quebra ficam (a chave do banco os mantém).
        self.assertEqual(normalize_key("  abc  ", " 20 ", " dobra1 "), ("ABC", "20", "DOBRA1"))
        self.assertEqual(normalize_key("\tabc\u00a0", "20\n", "x"), ("\tABC\u00a0", "20\n", "X"))
        self.assertEqual(normalize_key(None, None, None), ("", "", ""))

    def test_permissao_de_edicao_so_manufatura_e_admin(self):
        self.assertTrue(can_manage_standard_time("manufatura"))
        self.assertTrue(can_manage_standard_time("admin"))
        for level in ("gestor", "supervisor", "lider", "diretoria", "operador_dobra", None):
            self.assertFalse(can_manage_standard_time(level), level)

    def test_rotulo_humano_do_nivel(self):
        self.assertEqual(role_label("manufatura"), "Engenharia de manufatura")


class _MemoryDb:
    """Dublê em memória do contrato que ``StandardTimeService`` usa."""

    def __init__(self, catalog=None, facts=None):
        # chave normalizada -> {"setores": [...], "protheus": float | None}
        self.catalog = catalog or {}
        self.facts = facts or []
        self.manual = {}
        self.historico = []
        self.estimados = {}
        self.eventos = []

    def obter_contexto_tempo_padrao(self, produto, operacao, recurso):
        entry = self.catalog.get((produto, operacao, recurso))
        if entry is None:
            return None
        return {
            "setores": entry["setores"],
            "tempo_protheus_segundos": entry.get("protheus"),
            "tempo_manual_segundos": self.manual.get((produto, operacao, recurso)),
        }

    def definir_tempo_padrao_manual(self, produto, operacao, recurso, segundos, *,
                                    observacao=None, usuario_id=None, usuario_nome=None):
        key = (produto, operacao, recurso)
        acao = "alterado" if key in self.manual else "definido"
        self.historico.append((key, acao, segundos, usuario_id, usuario_nome))
        self.manual[key] = segundos
        return {"produto_codigo": produto, "numero_operacao": operacao,
                "codigo_recurso": recurso, "segundos_por_peca": segundos}

    def remover_tempo_padrao_manual(self, produto, operacao, recurso, *,
                                    usuario_id=None, usuario_nome=None):
        key = (produto, operacao, recurso)
        if key not in self.manual:
            return False
        self.historico.append((key, "removido", None, usuario_id, usuario_nome))
        del self.manual[key]
        return True

    def listar_tempos_padrao(self, **_kwargs):
        return {"items": [], "total": 0, "sem_produto": 0}

    def listar_historico_tempo_padrao_manual(self, *_key):
        return [{"acao": h[1], "segundos_novo": h[2]} for h in self.historico]

    def substituir_tempos_padrao_estimados(self, registros, calculado_em):
        self.estimados = {
            (r["produto"], r["operacao"], r["recurso"]): r for r in registros
        }

    def registrar_evento_sistema(self, tipo, origem, mensagem, data_hora=None, **_kw):
        self.eventos.append({"tipo": tipo, "origem": origem, "data_hora": data_hora})

    def ultimo_evento_sistema(self, tipos=None, origem=None):
        matching = [e for e in self.eventos if not tipos or e["tipo"] in tipos]
        return matching[-1] if matching else None

    # Contrato mínimo de IndustrialAnalyticsService.
    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return list(self.facts)

    def possui_calendario_produtivo(self, *_a):
        return False

    def listar_tempos_nesting_corte(self, **_k):
        return []

    def listar_inconsistencias_dados(self, **_k):
        return []


def _fact(idx, *, seconds, good=10, day_offset=1, setor="Dobra", status="Finalizado",
          produto="PROD1", operacao="20", recurso="DOBRA1"):
    start = datetime(2026, 10, 6) - timedelta(days=day_offset) + timedelta(hours=8)
    finish = start + timedelta(seconds=seconds)
    return {
        "id": idx, "op": f"OP{idx}", "tipo_setor": setor, "maquina": recurso,
        "status": status, "data_inicio": start, "data_fim": finish,
        "quantidade_boa": good, "quantidade_refugo": 0, "quantidade_retrabalho": 0,
        "produto_codigo": produto, "numero_operacao": operacao, "codigo_recurso": recurso,
        "catalogo_operacao_id": 100 + idx,
        "tempo_padrao_segundos": None, "tempo_padrao_fonte": None,
        "eventos": [
            {"id": idx * 10 + 1, "estado": "producao", "data_hora": start},
            {"id": idx * 10 + 2, "estado": "finalizado", "data_hora": finish},
        ],
    }


KEY = ("PROD1", "20", "DOBRA1")


class StandardTimeServiceManualTests(unittest.TestCase):
    def setUp(self):
        self.db = _MemoryDb(catalog={
            KEY: {"setores": ["Dobra"], "protheus": None},
            ("PROD1", "30", "SOLDA1"): {"setores": ["Solda"], "protheus": 42.0},
            ("PROD2", "10", "LASER1"): {"setores": ["Corte"], "protheus": None},
        })
        self.service = StandardTimeService(self.db, now_func=lambda: NOW)

    def test_define_altera_e_remove_com_historico(self):
        self.service.set_manual(" prod1 ", "20", "dobra1", 55, usuario_id=7, usuario_nome="Eng")
        self.service.set_manual("PROD1", "20", "DOBRA1", 60, usuario_id=7, usuario_nome="Eng")
        self.assertEqual(self.db.manual[KEY], 60.0)
        self.service.remove_manual("PROD1", "20", "DOBRA1", usuario_id=7, usuario_nome="Eng")
        self.assertEqual([h[1] for h in self.db.historico], ["definido", "alterado", "removido"])
        self.assertNotIn(KEY, self.db.manual)

    def test_protheus_real_vence_e_recusa_o_manual_com_409(self):
        with self.assertRaises(StandardTimeRuleError) as raised:
            self.service.set_manual("PROD1", "30", "SOLDA1", 10)
        self.assertEqual((raised.exception.code, raised.exception.status_code),
                         ("standard_time_defined_by_protheus", 409))

    def test_corte_nao_recebe_tempo_manual(self):
        with self.assertRaises(StandardTimeRuleError) as raised:
            self.service.set_manual("PROD2", "10", "LASER1", 10)
        self.assertEqual((raised.exception.code, raised.exception.status_code),
                         ("standard_time_sector_without_standard", 409))

    def test_operacao_inexistente_404_e_chave_vazia_422(self):
        with self.assertRaises(StandardTimeRuleError) as missing:
            self.service.set_manual("PROD9", "1", "X", 10)
        self.assertEqual(missing.exception.status_code, 404)
        with self.assertRaises(StandardTimeRuleError) as empty:
            self.service.set_manual("", "20", "DOBRA1", 10)
        self.assertEqual(empty.exception.status_code, 422)

    def test_valor_invalido_ou_acima_do_teto_422(self):
        for value in (0, -1, 86401, float("nan"), float("inf"), "abc", None):
            with self.assertRaises(StandardTimeRuleError, msg=repr(value)) as raised:
                self.service.set_manual("PROD1", "20", "DOBRA1", value)
            self.assertEqual(raised.exception.code, "invalid_standard_time")
            self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(self.db.manual, {})

    def test_remover_inexistente_404(self):
        with self.assertRaises(StandardTimeRuleError) as raised:
            self.service.remove_manual("PROD1", "20", "DOBRA1")
        self.assertEqual(raised.exception.status_code, 404)


class StandardTimeEstimateTests(unittest.TestCase):
    def _db(self, extra=()):
        # 5 execuções boas: 60, 70, 80, 90 e 100 s/peça -> P25 = 70.
        facts = [_fact(i, seconds=600 + 100 * (i - 1), day_offset=i) for i in range(1, 6)]
        facts.extend(extra)
        return _MemoryDb(facts=facts)

    def test_p25_das_execucoes_boas_e_idempotente(self):
        db = self._db()
        service = StandardTimeService(db, now_func=lambda: NOW)
        summary = service.recalculate_estimates()
        self.assertEqual(summary["chaves_estimadas"], 1)
        record = db.estimados[KEY]
        self.assertEqual((record["segundos_por_peca"], record["amostras"]), (70.0, 5))
        service.recalculate_estimates()
        self.assertEqual(db.estimados[KEY]["segundos_por_peca"], 70.0)
        self.assertEqual(len(db.estimados), 1)
        self.assertEqual(service.last_estimate_run(), NOW)
        self.assertEqual(db.eventos[-1]["tipo"], ESTIMATE_EVENT_TYPE)

    def test_outlier_corte_e_nao_finalizada_ficam_fora(self):
        extra = [
            _fact(20, seconds=20000, day_offset=6),                    # outlier
            _fact(21, seconds=500, day_offset=2, setor="Corte", recurso="LASER1"),
            _fact(22, seconds=500, day_offset=3, status="Em andamento", recurso="DOBRA2"),
            _fact(23, seconds=500, day_offset=0, recurso="DOBRA3"),     # hoje: fora da janela
        ]
        db = self._db(extra)
        service = StandardTimeService(db, now_func=lambda: NOW)
        summary = service.recalculate_estimates()
        self.assertEqual(db.estimados[KEY]["segundos_por_peca"], 70.0)
        self.assertEqual(db.estimados[KEY]["amostras"], 5)
        self.assertEqual(summary["execucoes_elegiveis"], 6)  # 5 + o outlier (cortado só no P25)

    def test_menos_de_5_amostras_nao_gera_estimado_e_limpa_o_antigo(self):
        db = _MemoryDb(facts=[_fact(i, seconds=600, day_offset=i) for i in range(1, 5)])
        db.estimados[KEY] = {"produto": "PROD1"}
        StandardTimeService(db, now_func=lambda: NOW).recalculate_estimates()
        self.assertEqual(db.estimados, {})

    def test_gatilho_diario_roda_uma_vez_por_dia(self):
        db = self._db()
        self.assertTrue(_recalculate_standard_time_estimates_if_due(db, NOW))
        self.assertFalse(_recalculate_standard_time_estimates_if_due(db, NOW + timedelta(hours=3)))
        self.assertTrue(_recalculate_standard_time_estimates_if_due(db, NOW + timedelta(days=1)))
        self.assertFalse(_recalculate_standard_time_estimates_if_due(object(), NOW))


class StandardTimeRecalculationLockTests(unittest.TestCase):
    def setUp(self):
        self.db = _MemoryDb(facts=[_fact(i, seconds=600 + 100 * (i - 1), day_offset=i) for i in range(1, 6)])
        self.service = StandardTimeService(self.db, now_func=lambda: NOW)
        self.assertTrue(standard_time_module._RECALCULATION_LOCK.acquire(blocking=False))
        self.held = True
        self.addCleanup(self._release)

    def _release(self):
        if self.held:
            standard_time_module._RECALCULATION_LOCK.release()
            self.held = False

    def test_recalculo_concorrente_recebe_409_estruturado_e_nao_roda(self):
        with self.assertRaises(StandardTimeRecalculationBusy) as raised:
            self.service.recalculate_estimates()
        self.assertEqual((raised.exception.code, raised.exception.status_code), (RECALCULATION_BUSY_CODE, 409))
        self.assertEqual(self.db.estimados, {})
        self.assertEqual(self.db.eventos, [])

    def test_tick_diario_pula_enquanto_ha_recalculo_em_curso(self):
        self.assertFalse(_recalculate_standard_time_estimates_if_due(self.db, NOW))
        self.assertEqual(self.db.estimados, {})
        self._release()
        self.assertTrue(_recalculate_standard_time_estimates_if_due(self.db, NOW))
        self.assertIn(KEY, self.db.estimados)

    def test_lock_e_liberado_depois_do_recalculo_e_apos_erro(self):
        self._release()
        self.service.recalculate_estimates()
        self.service.recalculate_estimates()  # não ficou preso

        def boom(*_a, **_k):
            raise RuntimeError("falha no repositório")

        self.db.substituir_tempos_padrao_estimados = boom
        with self.assertRaises(RuntimeError):
            self.service.recalculate_estimates()
        self.assertTrue(standard_time_module._RECALCULATION_LOCK.acquire(blocking=False))
        standard_time_module._RECALCULATION_LOCK.release()


class _FactRepo(_ManagementRepo):
    """Mesmo fato do teste de gestão, com a fonte do padrão escolhida."""

    def __init__(self, fonte, valor):
        self.fonte, self.valor = fonte, valor

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        fact = super().listar_fatos_operacionais_periodo()[0]
        fact.pop("tempo_medio_segundos")
        fact["tempo_padrao_segundos"] = self.valor
        fact["tempo_padrao_fonte"] = self.fonte
        return [fact]


class ManagementPayloadTests(unittest.TestCase):
    FILTERS = AnalyticsFilter(datetime(2026, 8, 19, 0, 0), datetime(2026, 8, 19, 23, 59))

    def _overview(self, fonte, valor):
        service = ManagementService(_FactRepo(fonte, valor), now_func=lambda: datetime(2026, 8, 19, 11, 0))
        return service.get_overview(self.FILTERS)

    def test_somente_estimado_nao_altera_a_performance_oficial(self):
        payload = self._overview("estimado", 500.0)
        self.assertIsNone(payload["kpis"]["performance"]["value"])
        self.assertEqual(payload["kpis"]["performance"]["availability"], "nao_configurado")
        estimados = payload["kpis_estimados"]
        self.assertTrue(estimados["usa_tempo_estimado"])
        self.assertEqual(estimados["pecas_boas_tempo_estimado"], 10)
        self.assertAlmostEqual(estimados["performance"]["value"], 10 * 500 / 6000 * 100)

    def test_manual_e_protheus_entram_na_performance_oficial(self):
        for fonte in ("manual", "protheus"):
            payload = self._overview(fonte, 500.0)
            self.assertAlmostEqual(payload["kpis"]["performance"]["value"], 10 * 500 / 6000 * 100)
            self.assertFalse(payload["kpis_estimados"]["usa_tempo_estimado"])
            self.assertEqual(payload["kpis_estimados"]["pecas_boas_tempo_estimado"], 0)

    def test_sem_nenhuma_fonte_as_duas_performances_ficam_indisponiveis(self):
        payload = self._overview(None, None)
        self.assertIsNone(payload["kpis"]["performance"]["value"])
        self.assertIsNone(payload["kpis_estimados"]["performance"]["value"])

    def test_padrao_x_real_separa_oficial_de_estimado(self):
        service = IndustrialAnalyticsService(_FactRepo("estimado", 500.0))
        row = service.standard_vs_actual(self.FILTERS)["items"][0]
        self.assertIsNone(row["tempo_padrao_unitario_segundos"])
        self.assertEqual(row["tempo_padrao_unitario_estimado_segundos"], 500.0)
        self.assertEqual(row["tempo_padrao_fonte"], "estimado")


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role, uid=5):
    return SessionUser(
        id=uid, name=f"Conta {role}", role=role, management_access=True,
        andon_access=True, operator_access=False,
    )


BODY = {"produto_codigo": "prod1", "numero_operacao": "20", "codigo_recurso": "dobra1",
        "segundos_por_peca": 55.5}
QUERY = {"produto_codigo": "PROD1", "numero_operacao": "20", "codigo_recurso": "DOBRA1"}


class StandardTimeApiTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.memory = _MemoryDb(catalog={
            KEY: {"setores": ["Dobra"], "protheus": None},
            ("PROD1", "30", "SOLDA1"): {"setores": ["Solda"], "protheus": 42.0},
            ("PROD2", "10", "LASER1"): {"setores": ["Corte"], "protheus": None},
        }, facts=[_fact(i, seconds=600 + 100 * (i - 1), day_offset=i) for i in range(1, 6)])
        for name in (
            "obter_contexto_tempo_padrao", "definir_tempo_padrao_manual",
            "remover_tempo_padrao_manual", "listar_tempos_padrao",
            "listar_historico_tempo_padrao_manual", "substituir_tempos_padrao_estimados",
            "registrar_evento_sistema", "ultimo_evento_sistema",
            "listar_fatos_operacionais_periodo", "possui_calendario_produtivo",
            "listar_tempos_nesting_corte", "listar_inconsistencias_dados",
        ):
            setattr(self.db, name, getattr(self.memory, name))
        self.app = create_app(settings=_settings(), database_factory=lambda: self.db)
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)

    def _as(self, role, uid=5):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    def test_so_manufatura_e_admin_leem_e_escrevem(self):
        for role in ("gestor", "supervisor", "diretoria"):
            self._as(role)
            self.assertEqual(self.client.get("/api/v1/management/standard-times").status_code, 403, role)
            self.assertEqual(
                self.client.put("/api/v1/management/standard-times/manual", json=BODY).status_code, 403, role)
            self.assertEqual(
                self.client.delete("/api/v1/management/standard-times/manual", params=QUERY).status_code, 403, role)
            self.assertEqual(
                self.client.post("/api/v1/management/standard-times/estimates/recalculate").status_code, 403, role)
            denied = self.client.get("/api/v1/management/standard-times").json()
            self.assertEqual(denied["code"], "standard_time_access_denied")
        self._as("operador_dobra")
        self.assertEqual(self.client.get("/api/v1/management/standard-times").status_code, 403)
        for role in ("manufatura", "admin"):
            self._as(role)
            self.assertEqual(self.client.get("/api/v1/management/standard-times").status_code, 200, role)

    def test_put_grava_com_autoria_e_delete_remove(self):
        self._as("manufatura", uid=77)
        saved = self.client.put("/api/v1/management/standard-times/manual", json=BODY)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["item"]["segundos_por_peca"], 55.5)
        self.assertEqual(self.memory.manual[KEY], 55.5)
        self.assertEqual(self.memory.historico[-1][3:], (77, "Conta manufatura"))
        removed = self.client.delete("/api/v1/management/standard-times/manual", params=QUERY)
        self.assertEqual(removed.status_code, 200, removed.text)
        again = self.client.delete("/api/v1/management/standard-times/manual", params=QUERY)
        self.assertEqual(again.status_code, 404)

    def test_erros_de_regra_viram_codigos_http_estaveis(self):
        self._as("admin")
        url = "/api/v1/management/standard-times/manual"
        casos = [
            ({**BODY, "segundos_por_peca": 0}, 422, "invalid_standard_time"),
            ({**BODY, "segundos_por_peca": 90000}, 422, "invalid_standard_time"),
            ({**BODY, "produto_codigo": "PROD1", "numero_operacao": "30", "codigo_recurso": "SOLDA1"},
             409, "standard_time_defined_by_protheus"),
            ({**BODY, "produto_codigo": "PROD2", "numero_operacao": "10", "codigo_recurso": "LASER1"},
             409, "standard_time_sector_without_standard"),
            ({**BODY, "produto_codigo": "NAOEXISTE"}, 404, "standard_time_operation_not_found"),
        ]
        for body, status, code in casos:
            resposta = self.client.put(url, json=body)
            self.assertEqual(resposta.status_code, status, (body, resposta.text))
            self.assertEqual(resposta.json()["code"], code)
        extra = self.client.put(url, json={**BODY, "campo_extra": 1})
        self.assertEqual(extra.status_code, 422)

    def test_recalculo_manual_devolve_resumo(self):
        self._as("manufatura")
        resposta = self.client.post("/api/v1/management/standard-times/estimates/recalculate")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertTrue(corpo["ok"])
        self.assertEqual(corpo["chaves_estimadas"], 1)
        self.assertIn(KEY, self.memory.estimados)

    def test_recalculo_manual_usa_o_relogio_da_aplicacao(self):
        # Em simulação o relógio da aplicação (não datetime.now) fixa o "agora"
        # do recálculo, como no tick diário.
        class _Clock:
            simulation_mode = True

            def now(self):
                return NOW

        self.app.state.settings = replace(self.app.state.settings, simulation_mode=True)
        self.app.state.clock = _Clock()
        self._as("manufatura")
        resposta = self.client.post("/api/v1/management/standard-times/estimates/recalculate")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(self.memory.eventos[-1]["data_hora"], NOW)

    def test_recalculo_manual_concorrente_devolve_409_estruturado(self):
        self._as("manufatura")
        url = "/api/v1/management/standard-times/estimates/recalculate"
        self.assertTrue(standard_time_module._RECALCULATION_LOCK.acquire(blocking=False))
        try:
            ocupado = self.client.post(url)
        finally:
            standard_time_module._RECALCULATION_LOCK.release()
        self.assertEqual(ocupado.status_code, 409, ocupado.text)
        self.assertEqual(ocupado.json()["code"], RECALCULATION_BUSY_CODE)
        self.assertEqual(self.memory.estimados, {})
        self.assertEqual(self.client.post(url).status_code, 200)

    def test_filtros_da_lista_tem_tamanho_maximo(self):
        self._as("admin")
        url = "/api/v1/management/standard-times"
        for campo, limite in (("produto", 80), ("setor", 40), ("recurso", 80)):
            self.assertEqual(self.client.get(url, params={campo: "x" * limite}).status_code, 200, campo)
            self.assertEqual(self.client.get(url, params={campo: "x" * (limite + 1)}).status_code, 422, campo)

    def test_historico_e_filtros_da_lista(self):
        self._as("admin")
        self.client.put("/api/v1/management/standard-times/manual", json=BODY)
        historico = self.client.get("/api/v1/management/standard-times/manual/history", params=QUERY)
        self.assertEqual(historico.status_code, 200)
        self.assertEqual(historico.json()["items"][0]["acao"], "definido")
        lista = self.client.get(
            "/api/v1/management/standard-times",
            params={"produto": "PROD1", "somente_sem_padrao": "false", "limit": 10},
        )
        self.assertEqual(lista.json()["somente_sem_padrao"], False)
        self.assertEqual(lista.json()["limit"], 10)

    def test_gestao_de_usuarios_aceita_manufatura(self):
        self._as("admin", uid=900)
        criado = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Eng Manufatura", "nivel": "manufatura", "ativo": True, "senha": "senha-forte-123"},
        )
        self.assertEqual(criado.status_code, 200, criado.text)
        self.assertEqual(criado.json()["item"]["nivel"], "manufatura")


if __name__ == "__main__":
    unittest.main()
