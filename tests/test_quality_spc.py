"""SPC da Qualidade (somente leitura): contas conferidas à mão, regras e endpoint."""

from __future__ import annotations

import inspect
import math
import os
import re
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.permissions import can_access_management_web
from app.database import quality_repository
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.services import quality_spc
from mes.services.quality_spc import (
    analisar_medicoes,
    dividir_em_blocos,
    indices_mesmo_lado,
)
from tests.fakes import FakeDatabase

T0 = datetime(2026, 10, 20, 8, 0)
URL = "/api/v1/quality/spc"


def _linhas(valores_por_inspecao, *, produto="PRD_A", sequencia=1, padrao="10,0 +/- 0,5",
            descricao="Comprimento", inicio_id=1):
    """Uma linha de repositório por medida; cada lista interna é uma inspeção (OP)."""

    linhas, peca = [], 0
    for numero, valores in enumerate(valores_por_inspecao):
        for valor in valores:
            peca += 1
            linhas.append({
                "produto_codigo": produto,
                "codigo_op": f"OP{inicio_id + numero}",
                "inspecao_id": inicio_id + numero,
                "template_revisao": 1,
                "peca_id": peca + inicio_id * 1000,
                "numero_peca": peca,
                "registrada_em": T0 + timedelta(minutes=peca + 100 * numero),
                "sequencia": sequencia,
                "descricao_snapshot": descricao,
                "padrao_snapshot": padrao,
                "medida": str(valor).replace(".", ","),
            })
    return linhas


# 5 subgrupos de 5 (X-barra/R). Médias = 10,0 e amplitudes 0,2 0,4 0,2 0,6 0,4.
SUBGRUPOS_XBAR = [
    [9.9, 10.0, 10.1, 10.0, 10.0],
    [10.0, 10.2, 9.8, 10.0, 10.0],
    [10.1, 10.1, 9.9, 10.0, 9.9],
    [10.0, 10.3, 9.7, 10.0, 10.0],
    [9.8, 10.2, 10.0, 10.1, 9.9],
]


class ConstantesTests(unittest.TestCase):
    def test_a2_d3_d4_batem_com_d2_d3_da_literatura(self):
        # A2 = 3/(d2*sqrt(n)); D4/D3 = 1 +/- 3*d3/d2. Pega erro de digitação na tabela.
        d3_literatura = {2: 0.853, 3: 0.888, 4: 0.880, 5: 0.864, 6: 0.848,
                         7: 0.833, 8: 0.820, 9: 0.808, 10: 0.797}
        for n, d3 in d3_literatura.items():
            d2 = quality_spc._D2[n]
            self.assertAlmostEqual(quality_spc._A2[n], 3 / (d2 * math.sqrt(n)), delta=0.002, msg=n)
            self.assertAlmostEqual(quality_spc._D4[n], 1 + 3 * d3 / d2, delta=0.003, msg=n)
            self.assertAlmostEqual(quality_spc._D3[n], max(0.0, 1 - 3 * d3 / d2), delta=0.003, msg=n)
        self.assertAlmostEqual(quality_spc._IMR_E2, 3 / quality_spc._IMR_D2, delta=0.001)


class XbarRTests(unittest.TestCase):
    def setUp(self):
        resultado = analisar_medicoes(_linhas(SUBGRUPOS_XBAR))
        self.assertEqual(len(resultado["series"]), 1)
        self.serie = resultado["series"][0]

    def test_numeros_calculados_a_mao(self):
        s = self.serie
        self.assertEqual(s["tipo_grafico"], "xbar_r")
        self.assertEqual((s["n_medidas"], s["n_subgrupos"]), (25, 5))
        self.assertTrue(s["suficiente"])
        self.assertAlmostEqual(s["media"], 10.0, places=9)
        # R-barra = (0,2+0,4+0,2+0,6+0,4)/5 = 0,36 ; sigma = 0,36/2,326
        self.assertAlmostEqual(s["sigma_dentro"], 0.36 / 2.326, places=9)
        # LC = 10 +/- A2(5)*R-barra = 10 +/- 0,577*0,36
        self.assertAlmostEqual(s["limites_x"]["ucl"], 10 + 0.577 * 0.36, places=9)
        self.assertAlmostEqual(s["limites_x"]["lcl"], 10 - 0.577 * 0.36, places=9)
        # Dispersão: UCL = D4*R-barra = 2,114*0,36 ; LCL = D3*R-barra = 0
        self.assertAlmostEqual(s["limites_dispersao"]["ucl"], 2.114 * 0.36, places=9)
        self.assertAlmostEqual(s["limites_dispersao"]["lcl"], 0.0, places=9)
        # Cpk = (10,5-10)/(3*sigma) = 1,0768... ; simétrico, então cpu == cpl
        self.assertAlmostEqual(s["cpk"]["value"], 0.5 / (3 * 0.36 / 2.326), places=9)
        self.assertAlmostEqual(s["cpk"]["value"], 1.0768, places=3)
        self.assertEqual(s["cpk"]["availability"], "disponivel")
        self.assertAlmostEqual(s["cpu"], s["cpl"], places=9)
        self.assertEqual([p["fora_de_controle"] for p in s["pontos"]], [[]] * 5)

    def test_constante_errada_mudaria_o_resultado(self):
        # Se alguém trocar d2(5)=2,326 pelo de n=4 (2,059), o Cpk sobe para ~0,95/1,2 e quebra aqui.
        self.assertNotAlmostEqual(self.serie["cpk"]["value"], 0.5 / (3 * 0.36 / 2.059), places=2)
        self.assertNotAlmostEqual(self.serie["limites_x"]["ucl"], 10 + 0.483 * 0.36, places=3)

    def test_rotulo_nunca_diz_capacidade_da_maquina(self):
        self.assertEqual(self.serie["escopo_cpk"], "dentro_da_op_lote")
        self.assertIn("dentro da OP/lote", self.serie["rotulo_cpk"])
        self.assertIn("não é a capacidade da máquina", self.serie["rotulo_cpk"])

    def test_media_fora_de_controle_e_marcada(self):
        # Um sexto subgrupo muito deslocado, mesma dispersão interna.
        subgrupos = SUBGRUPOS_XBAR + [[10.4, 10.5, 10.6, 10.5, 10.5]]
        serie = analisar_medicoes(_linhas(subgrupos))["series"][0]
        sinais = serie["pontos"][-1]["fora_de_controle"]
        self.assertIn({"grafico": "x", "regra": "fora_dos_limites"}, sinais)

    def test_inspecao_grande_vira_blocos_de_5(self):
        self.assertEqual([len(b) for b in dividir_em_blocos(list(range(10)))], [10])
        self.assertEqual([len(b) for b in dividir_em_blocos(list(range(12)))], [5, 5, 2])
        self.assertEqual([len(b) for b in dividir_em_blocos(list(range(11)))], [5, 6])
        # 30 peças de uma única OP: 6 subgrupos de 5 -> amostra suficiente.
        valores = [10 + ((i * 7) % 5 - 2) * 0.05 for i in range(30)]
        serie = analisar_medicoes(_linhas([valores]))["series"][0]
        self.assertEqual((serie["tipo_grafico"], serie["n_subgrupos"], serie["n_medidas"]), ("xbar_r", 6, 30))
        self.assertTrue(serie["suficiente"])


class IndividualAmplitudeMovelTests(unittest.TestCase):
    def test_numeros_calculados_a_mao(self):
        # 20 OPs de 1 peça, alternando 10,0 / 10,2: AM = 0,2 sempre.
        valores = [[10.0 if i % 2 == 0 else 10.2] for i in range(20)]
        s = analisar_medicoes(_linhas(valores))["series"][0]
        self.assertEqual(s["tipo_grafico"], "i_mr")
        self.assertTrue(s["suficiente"])
        self.assertAlmostEqual(s["media"], 10.1, places=9)
        self.assertAlmostEqual(s["limites_x"]["ucl"], 10.1 + 2.66 * 0.2, places=9)
        self.assertAlmostEqual(s["limites_x"]["lcl"], 10.1 - 2.66 * 0.2, places=9)
        self.assertAlmostEqual(s["limites_dispersao"]["ucl"], 3.267 * 0.2, places=9)
        self.assertAlmostEqual(s["sigma_dentro"], 0.2 / 1.128, places=9)
        # Cpk = min((10,5-10,1), (10,1-9,5)) / (3*sigma) = 0,4/(3*0,2/1,128)
        self.assertAlmostEqual(s["cpk"]["value"], 0.4 / (3 * 0.2 / 1.128), places=9)
        self.assertIsNone(s["pontos"][0]["amplitude"])
        self.assertEqual([p["fora_de_controle"] for p in s["pontos"]], [[]] * 20)
        self.assertEqual(s["escopo_cpk"], "curto_prazo_pecas_consecutivas")
        self.assertEqual(
            s["rotulo_cpk"],
            "Cpk de curto prazo entre peças consecutivas (pode cruzar OPs); "
            "não é a capacidade da máquina.",
        )

    def test_valor_fora_dos_limites(self):
        valores = [[10.0 if i % 2 == 0 else 10.1] for i in range(19)] + [[12.0]]
        s = analisar_medicoes(_linhas(valores))["series"][0]
        self.assertIn({"grafico": "x", "regra": "fora_dos_limites"}, s["pontos"][-1]["fora_de_controle"])
        self.assertIn({"grafico": "dispersao", "regra": "fora_dos_limites"}, s["pontos"][-1]["fora_de_controle"])
        # Os 19 primeiros ficam dentro dos limites (só há sinal no 20º ponto).
        self.assertFalse(any(
            sinal["regra"] == "fora_dos_limites"
            for p in s["pontos"][:-1] for sinal in p["fora_de_controle"]
        ))


class AmostraInsuficienteTests(unittest.TestCase):
    def test_menos_de_20_medidas_nao_calcula_cpk_nem_limites(self):
        s = analisar_medicoes(_linhas(SUBGRUPOS_XBAR[:3]))["series"][0]  # 15 medidas, 3 subgrupos
        self.assertFalse(s["suficiente"])
        self.assertIsNone(s["cpk"]["value"])
        self.assertEqual(s["cpk"]["availability"], "dados_insuficientes")
        self.assertIn("insuficiente", s["motivo_insuficiente"])
        self.assertIn("15 medidas", s["cpk"]["reason"])
        self.assertIsNone(s["limites_x"])
        self.assertIsNone(s["sigma_dentro"])
        self.assertEqual(s["n_medidas"], 15)
        self.assertAlmostEqual(s["media"], 10.0, places=9)  # a média descritiva existe
        self.assertTrue(all(p["fora_de_controle"] == [] for p in s["pontos"]))

    def test_muitas_medidas_em_poucos_subgrupos_tambem_e_insuficiente(self):
        # 4 subgrupos de 10 peças = 40 medidas, mas só 4 subgrupos (< 5).
        s = analisar_medicoes(_linhas([[10.0 + 0.01 * (i % 3) for i in range(10)] for _ in range(4)]))["series"][0]
        self.assertEqual((s["n_medidas"], s["n_subgrupos"]), (40, 4))
        self.assertFalse(s["suficiente"])
        self.assertIsNone(s["cpk"]["value"])

    def test_sem_variacao_nao_inventa_cpk(self):
        s = analisar_medicoes(_linhas([[10.0] * 5 for _ in range(5)]))["series"][0]
        self.assertTrue(s["suficiente"])
        self.assertIsNone(s["cpk"]["value"])
        self.assertIn("Sem variação", s["cpk"]["reason"])

    def test_variacao_zero_dentro_das_ops_fica_sem_limites_e_sem_sinais(self):
        # Paquímetro lê de 0,1 em 0,1: cada OP de 4 peças sai com a mesma leitura,
        # e as OPs diferem entre si (10,0 / 10,1 / 9,9). Dentro de cada OP não há variação.
        ops = [[v] * 4 for v in (10.0, 10.1, 9.9, 10.0, 10.1, 9.9)]
        s = analisar_medicoes(_linhas(ops))["series"][0]
        self.assertEqual((s["tipo_grafico"], s["n_medidas"], s["n_subgrupos"]), ("xbar_r", 24, 6))
        self.assertTrue(s["suficiente"])
        self.assertIsNone(s["limites_x"])
        self.assertIsNone(s["limites_dispersao"])
        self.assertEqual(s["sigma_dentro"], 0.0)
        self.assertIn("Sem variação dentro dos subgrupos", s["motivo_sem_limites"])
        self.assertIsNone(s["cpk"]["value"])
        self.assertIn("Sem variação", s["cpk"]["reason"])
        for ponto in s["pontos"]:
            self.assertEqual(ponto["fora_de_controle"], [])
            self.assertIsNone(ponto["limites_x"])
            self.assertIsNone(ponto["limites_dispersao"])

    def test_com_variacao_nao_ha_motivo_sem_limites(self):
        s = analisar_medicoes(_linhas(SUBGRUPOS_XBAR))["series"][0]
        self.assertIsNone(s["motivo_sem_limites"])

    def test_padrao_sem_margem_nao_calcula_cpk(self):
        s = analisar_medicoes(_linhas(SUBGRUPOS_XBAR, padrao="10"))["series"][0]
        self.assertTrue(s["suficiente"])
        self.assertIsNone(s["cpk"]["value"])
        self.assertEqual(s["cpk"]["availability"], "nao_aplicavel")


class AgrupamentoTests(unittest.TestCase):
    def test_revisoes_do_padrao_nao_se_misturam(self):
        rev1 = _linhas(SUBGRUPOS_XBAR, padrao="10,0 +/- 0,5", inicio_id=1)
        rev2 = _linhas(SUBGRUPOS_XBAR, padrao="10,0 +/- 0,2", inicio_id=10)
        resultado = analisar_medicoes(rev1 + rev2)
        self.assertEqual(len(resultado["series"]), 2)
        por_padrao = {s["padrao_snapshot"]: s for s in resultado["series"]}
        for s in por_padrao.values():
            self.assertEqual(s["n_medidas"], 25)  # nenhuma série recebeu as 50
        self.assertGreater(
            por_padrao["10,0 +/- 0,5"]["cpk"]["value"], por_padrao["10,0 +/- 0,2"]["cpk"]["value"]
        )

    def test_produtos_e_cotas_diferentes_sao_series_diferentes(self):
        linhas = (
            _linhas(SUBGRUPOS_XBAR, produto="A", sequencia=1, inicio_id=1)
            + _linhas(SUBGRUPOS_XBAR, produto="A", sequencia=2, inicio_id=10)
            + _linhas(SUBGRUPOS_XBAR, produto="B", sequencia=1, inicio_id=20)
        )
        chaves = [(s["produto"], s["cota"]["sequencia"]) for s in analisar_medicoes(linhas)["series"]]
        self.assertEqual(chaves, [("A", 1), ("A", 2), ("B", 1)])

    def test_padrao_nao_numerico_e_medida_invalida_sao_ignorados_e_contados(self):
        texto = _linhas([["OK", "OK"], ["NOK"]], padrao="Conforme/Não conforme", sequencia=3)
        lixo = _linhas(SUBGRUPOS_XBAR, sequencia=1)
        lixo[0]["medida"] = "abc"
        resultado = analisar_medicoes(texto + lixo)
        self.assertEqual(resultado["ignoradas"], {"padrao_nao_numerico": 3, "medida_invalida": 1})
        self.assertEqual([s["cota"]["sequencia"] for s in resultado["series"]], [1])
        self.assertEqual(resultado["series"][0]["n_medidas"], 24)

    def test_sem_nenhuma_medida_devolve_lista_vazia(self):
        resultado = analisar_medicoes([])
        self.assertEqual(resultado["series"], [])
        self.assertEqual(resultado["amostra_minima"], {"medidas": 20, "subgrupos": 5})

    def test_ordem_de_entrada_nao_importa(self):
        linhas = _linhas(SUBGRUPOS_XBAR)
        a = analisar_medicoes(linhas)["series"][0]
        b = analisar_medicoes(list(reversed(linhas)))["series"][0]
        self.assertEqual(a["cpk"], b["cpk"])
        self.assertEqual([p["media"] for p in a["pontos"]], [p["media"] for p in b["pontos"]])

    def test_pecas_reprovadas_tambem_entram(self):
        # O repositório não filtra por resultado; o domínio não pode filtrar o que não recebe.
        self.assertNotIn("resultado", inspect.getsource(quality_spc._especificacao))
        self.assertNotIn("APROVADA", inspect.getsource(quality_spc))


class RegraSeteMesmoLadoTests(unittest.TestCase):
    def test_seis_nao_sete_sim(self):
        self.assertEqual(indices_mesmo_lado([1, 1, 1, 1, 1, 1, -1], 0), [])
        self.assertEqual(indices_mesmo_lado([1, 1, 1, 1, 1, 1, 1], 0), list(range(7)))

    def test_lado_de_baixo_e_sequencia_longa_no_meio(self):
        self.assertEqual(indices_mesmo_lado([1, -1, -1, -1, -1, -1, -1, -1, -1, 1], 0), list(range(1, 9)))

    def test_ponto_no_centro_interrompe(self):
        self.assertEqual(indices_mesmo_lado([1, 1, 1, 0, 1, 1, 1, 1], 0), [])

    def test_integrado_na_serie_individual(self):
        # 7 valores acima de 10,00 seguidos, dentro dos limites; o restante alterna em volta.
        valores = [10.06, 10.07, 10.06, 10.07, 10.06, 10.07, 10.06] + [9.95, 10.05] * 6 + [9.95]
        s = analisar_medicoes(_linhas([[v] for v in valores]))["series"][0]
        self.assertEqual(len(valores), 20)
        sinais = [i for i, p in enumerate(s["pontos"])
                  if {"grafico": "x", "regra": "sete_do_mesmo_lado"} in p["fora_de_controle"]]
        self.assertEqual(sinais, list(range(7)))
        # nenhum ponto fora dos limites: o sinal vem só da regra dos 7
        self.assertFalse(any({"grafico": "x", "regra": "fora_dos_limites"} in p["fora_de_controle"]
                             for p in s["pontos"]))


# ---------------------------------------------------------------------------
# Endpoint: nível, filtros, resposta e ausência de escrita
# ---------------------------------------------------------------------------
class _BancoSomenteLeitura:
    """Expõe SÓ ``listar_medidas_spc``: qualquer outra chamada vira AttributeError."""

    def __init__(self, linhas):
        self.linhas = linhas
        self.chamadas = []

    def listar_medidas_spc(self, **filtros):
        self.chamadas.append(filtros)
        return list(self.linhas)


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role, uid=5):
    return SessionUser(
        id=uid, name=f"Conta {role}", role=role,
        management_access=can_access_management_web(role),
        andon_access=True, operator_access=role.startswith("operador_"),
    )


class SpcEndpointTests(unittest.TestCase):
    def setUp(self):
        self.banco = _BancoSomenteLeitura(_linhas(SUBGRUPOS_XBAR))
        self.app = create_app(settings=_settings(), database_factory=lambda: FakeDatabase())
        self.app.dependency_overrides[get_database] = lambda: self.banco
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, role):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role)

    def test_exige_nivel_qualidade_ou_admin(self):
        for role in ("gestor", "supervisor", "lider", "manufatura", "diretoria", "operador_dobra"):
            self._as(role)
            resposta = self.client.get(URL)
            self.assertEqual(resposta.status_code, 403, role)
            self.assertEqual(resposta.json()["code"], "quality_templates_access_denied", role)
        self.assertEqual(self.banco.chamadas, [])  # nem chegou a consultar
        for role in ("qualidade", "admin"):
            self._as(role)
            self.assertEqual(self.client.get(URL).status_code, 200, role)

    def test_resposta_traz_cpk_rotulado_e_filtros_chegam_ao_repositorio(self):
        self._as("qualidade")
        resposta = self.client.get(URL, params={
            "product": "PRD_A", "cota": 1, "start": "2026-10-01T00:00:00", "end": "2026-10-25T00:00:00",
        })
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        filtros = self.banco.chamadas[-1]
        self.assertEqual((filtros["produto"], filtros["sequencia"]), ("PRD_A", 1))
        self.assertEqual(filtros["inicio"], datetime(2026, 10, 1))
        self.assertEqual(filtros["fim"], datetime(2026, 10, 25))
        self.assertFalse(corpo["truncado"])
        self.assertIn("não é a capacidade da máquina", corpo["rotulo_cpk"])
        serie = corpo["series"][0]
        self.assertEqual(serie["escopo_cpk"], "dentro_da_op_lote")
        self.assertTrue(serie["suficiente"])
        self.assertAlmostEqual(serie["cpk"]["value"], 1.0768, places=3)
        self.assertEqual(len(serie["pontos"]), 5)
        self.assertEqual(serie["pontos"][0]["fora_de_controle"], [])

    def test_amostra_curta_volta_com_cpk_nulo_e_motivo(self):
        self.banco.linhas = _linhas(SUBGRUPOS_XBAR[:2])
        self._as("admin")
        serie = self.client.get(URL).json()["series"][0]
        self.assertFalse(serie["suficiente"])
        self.assertIsNone(serie["cpk"]["value"])
        self.assertIn("Amostra insuficiente", serie["cpk"]["reason"])
        self.assertIsNone(serie["limites_x"])

    def test_corte_por_limite_e_sinalizado(self):
        limite = quality_spc.LIMITE_PADRAO_LINHAS
        self.banco.linhas = _linhas(SUBGRUPOS_XBAR)[:5] * ((limite // 5) + 1)  # limite + 5 linhas
        self._as("admin")
        self.assertTrue(self.client.get(URL).json()["truncado"])

    def test_corte_descarta_a_inspecao_parcial_mais_antiga(self):
        from unittest import mock

        # 8 OPs de 5 peças; o repositório entrega as mais recentes primeiro.
        todas = list(reversed(_linhas([[10.0 + 0.01 * i for i in range(5)] for _ in range(8)])))
        self.banco.linhas = todas  # 40 linhas
        self._as("admin")
        with mock.patch("backend.api.routers.quality.LIMITE_PADRAO_LINHAS", 28):
            corpo = self.client.get(URL).json()
        self.assertTrue(corpo["truncado"])
        # 28 linhas = 5 OPs completas + 3 peças da 6ª; a 6ª (cortada ao meio) sai inteira.
        self.assertEqual(corpo["series"][0]["n_medidas"], 25)
        self.assertEqual(corpo["series"][0]["n_subgrupos"], 5)

    def test_nao_escreve_nada(self):
        # O banco de teste só tem a leitura; uma escrita levantaria AttributeError (500).
        self._as("qualidade")
        self.assertEqual(self.client.get(URL).status_code, 200)
        self.assertEqual(len(self.banco.chamadas), 1)
        # Não existe verbo de escrita para o caminho.
        self.assertEqual(self.client.post(URL, json={}).status_code, 405)
        self.assertEqual(self.client.delete(URL).status_code, 405)

    def test_sql_do_repositorio_so_le(self):
        codigo = inspect.getsource(quality_repository.QualityRepositoryMixin.listar_medidas_spc)
        self.assertIsNone(re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b", codigo))
        self.assertIn("SELECT", codigo)


# ---------------------------------------------------------------------------
# SQL real (só roda com TEST_DATABASE_URL, em schema descartável)
# ---------------------------------------------------------------------------
@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class SpcPostgresTests(unittest.TestCase):
    AGORA = datetime(2026, 10, 20, 9, 0)

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database
        from app.database.errors import DatabaseConfigurationError

        try:
            base = load_postgres_config(testing=True)
        except DatabaseConfigurationError as exc:  # banco de teste isolado ausente/recusado
            self.skipTest(str(exc))
        self.admin_dsn = base.dsn
        self.schema = "spc_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop_schema(self):
        import psycopg
        from psycopg import sql

        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_consulta_filtra_por_produto_cota_e_periodo(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            for produto, numero in (("PRD_A", 1), ("PRD_B", 2)):
                cursor.execute(
                    "INSERT INTO qualidade_inspecoes (codigo_op, numero_operacao, produto_codigo,"
                    " tipo_setor, codigo_recurso, quantidade_total, status, operador, iniciada_em)"
                    " VALUES (%s, '10', %s, 'Qualidade', 'Q1', 2, 'EM_INSPECAO', 'Op', %s) RETURNING id",
                    (f"OP{numero}", produto, self.AGORA),
                )
                inspecao = cursor.fetchone()["id"]
                cursor.execute(
                    "INSERT INTO qualidade_pecas_inspecionadas (inspecao_id, numero_peca, resultado,"
                    " operador, registrada_em) VALUES (%s, 1, 'APROVADA', 'Op', %s) RETURNING id",
                    (inspecao, self.AGORA),
                )
                peca = cursor.fetchone()["id"]
                for sequencia in (1, 2):
                    cursor.execute(
                        "INSERT INTO qualidade_resultados_cota (peca_id, sequencia, padrao_snapshot,"
                        " medida, status) VALUES (%s, %s, '10,0 +/- 0,5', '10,1', 'CONFORME')",
                        (peca, sequencia),
                    )
        self.assertEqual(len(self.db.listar_medidas_spc()), 4)
        self.assertEqual(len(self.db.listar_medidas_spc(produto="prd_a")), 2)
        self.assertEqual(len(self.db.listar_medidas_spc(produto="PRD_A", sequencia=2)), 1)
        self.assertEqual(len(self.db.listar_medidas_spc(inicio=self.AGORA + timedelta(hours=1))), 0)
        self.assertEqual(len(self.db.listar_medidas_spc(limite=1)), 2)  # limite + 1 (sinal de corte)


if __name__ == "__main__":
    unittest.main()
