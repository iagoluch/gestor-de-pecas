"""Gestão enxerga a dispensa de inspeção e o aproveitamento da chapa (somente leitura).

Cobre os campos novos: ``inspection_waivers`` (rastreabilidade da OP e lista do
período em ``/traceability/inspection-waivers``) e ``area_usada`` /
``fracao_sucata`` / ``aproveitamento_percentual`` + ``aproveitamento`` em
``/traceability/nestings`` e ``cutting_nestings``.
"""

from __future__ import annotations

import os
import unittest
import uuid
from datetime import datetime

from fastapi.testclient import TestClient

from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.services.cut_utilization import (
    aproveitamento_percentual,
    resumir_aproveitamento,
)
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.traceability import TraceabilityService
from tests.fakes import FakeDatabase
from tests.test_standard_time import _settings

DISPENSA = {
    "inspecao_id": 11,
    "codigo_op": "OP-1",
    "numero_operacao": "40",
    "produto_codigo": "P-9",
    "produto_descricao": "Suporte",
    "codigo_recurso": "DOBRA1",
    "setor_origem": "Dobra",
    "quantidade_total": 12,
    "operador": "Ana",
    "dispensada_em": datetime(2026, 10, 28, 14, 30),
    "dispensa_motivo": "Peça de amostra do cliente",
    "dispensa_autorizada_por": "Carlos Qualidade",
    "dispensa_cracha": "00123",
}


class _DbDispensa(FakeDatabase):
    def __init__(self, rows=None):
        super().__init__()
        self.rows = [dict(DISPENSA)] if rows is None else rows
        self.chamadas = []

    def listar_dispensas_inspecao(self, **kwargs):
        self.chamadas.append(kwargs)
        return list(self.rows)


def _corte(id_, tarefa, nesting, fracao, area, inicio_h):
    return {
        "id": id_, "plano_hash": f"h{id_}", "codigo_tarefa": tarefa,
        "programa": f"PRG{id_}", "sequencia_nesting": nesting, "maquina": "LASER1",
        "material": "Aço", "espessura": 3, "status": "Finalizado",
        "tempo_previsto_segundos": 600, "tempo_real_segundos": 700,
        "operador_inicio": "Rui", "operador_fim": "Rui",
        "data_inicio": datetime(2026, 10, 28, inicio_h, 0),
        "data_fim": datetime(2026, 10, 28, inicio_h, 10),
        "area_usada": area, "fracao_sucata": fracao,
    }


def _db_corte():
    db = FakeDatabase()
    db.cut_appointments = [
        _corte(1, "T1", 1, 0.25, 1000.0, 8),
        _corte(2, "T1", 2, 0.35, 2000.0, 9),
        _corte(3, "T2", 1, None, None, 10),
        _corte(4, "T2", 2, 7.0, 500.0, 11),  # fração fora de 0..1: sem dado
    ]
    return db


class AproveitamentoDaChapaTests(unittest.TestCase):
    def test_aproveitamento_e_um_menos_a_fracao_de_sucata(self):
        self.assertEqual(aproveitamento_percentual(0.25), 75.0)
        self.assertEqual(aproveitamento_percentual("0.1"), 90.0)
        self.assertEqual(aproveitamento_percentual(0), 100.0)

    def test_dado_ausente_ou_fora_de_0_a_1_nao_vira_numero(self):
        for bruto in (None, "", "abc", -0.1, 1.5, 25):
            self.assertIsNone(aproveitamento_percentual(bruto), bruto)

    def test_resumo_total_e_por_tarefa(self):
        itens = [
            {"tarefa": "T1", "fracao_sucata": 0.25, "area_usada": 1000},
            {"tarefa": "T1", "fracao_sucata": 0.35, "area_usada": 2000},
            {"tarefa": "T2", "fracao_sucata": None, "area_usada": None},
        ]
        resumo = resumir_aproveitamento(itens)
        self.assertEqual(resumo["nestings"], 3)
        self.assertEqual(resumo["nestings_com_dado"], 2)
        self.assertEqual(resumo["nestings_sem_dado"], 1)
        self.assertEqual(resumo["area_usada_total"], 3000.0)
        self.assertEqual(resumo["aproveitamento_medio_percentual"], 70.0)
        por_tarefa = {t["tarefa"]: t for t in resumo["por_tarefa"]}
        self.assertEqual(por_tarefa["T1"]["aproveitamento_medio_percentual"], 70.0)
        self.assertEqual(por_tarefa["T1"]["area_usada"], 3000.0)
        self.assertIsNone(por_tarefa["T2"]["aproveitamento_medio_percentual"])
        self.assertEqual(por_tarefa["T2"]["nestings_com_dado"], 0)

    def test_resumo_vazio_nao_inventa_media(self):
        resumo = resumir_aproveitamento([])
        self.assertEqual(resumo["nestings"], 0)
        self.assertIsNone(resumo["aproveitamento_medio_percentual"])
        self.assertEqual(resumo["por_tarefa"], [])

    def test_facade_entrega_campos_crus_e_aproveitamento_por_nesting(self):
        facade = FrontendBackendFacade(_db_corte())
        filtro = AnalyticsFilter(datetime(2026, 10, 28, 0, 0), datetime(2026, 10, 28, 23, 59))
        itens = {(i["tarefa"], i["nesting"]): i for i in facade.nestings(filtro)["items"]}
        self.assertEqual(itens[("T1", 1)]["fracao_sucata"], 0.25)
        self.assertEqual(itens[("T1", 1)]["area_usada"], 1000.0)
        self.assertEqual(itens[("T1", 1)]["aproveitamento_percentual"], 75.0)
        self.assertEqual(itens[("T1", 2)]["aproveitamento_percentual"], 65.0)
        self.assertIsNone(itens[("T2", 1)]["aproveitamento_percentual"])
        self.assertIsNone(itens[("T2", 2)]["aproveitamento_percentual"])
        self.assertEqual(itens[("T2", 2)]["fracao_sucata"], 7.0)

    def test_rastreabilidade_da_op_traz_aproveitamento_dos_nestings(self):
        class Db(FakeDatabase):
            def listar_nestings_corte_por_op(self, op):
                return [{"apontamento_id": 1, "tarefa": "T1", "nesting": 1,
                         "area_usada": 900.0, "fracao_sucata": 0.2,
                         "inicio": datetime(2026, 10, 28, 8, 0)}]

        nesting = TraceabilityService(Db()).trace_op("OP-1")["cutting_nestings"][0]
        self.assertEqual(nesting["area_usada"], 900.0)
        self.assertEqual(nesting["fracao_sucata"], 0.2)
        self.assertEqual(nesting["aproveitamento_percentual"], 80.0)


class DispensaNaRastreabilidadeTests(unittest.TestCase):
    def test_trace_op_lista_a_dispensa_com_todos_os_campos(self):
        db = _DbDispensa()
        trace = TraceabilityService(db).trace_op("op-1")
        self.assertTrue(trace["inspection_waived"])
        self.assertEqual(db.chamadas[-1], {"op": "op-1", "op_exata": True})
        item = trace["inspection_waivers"][0]
        self.assertTrue(item["dispensada"])
        self.assertEqual(item["motivo"], "Peça de amostra do cliente")
        self.assertEqual(item["autorizado_por"], "Carlos Qualidade")
        self.assertEqual(item["cracha"], "00123")
        self.assertEqual(item["dispensada_em"], datetime(2026, 10, 28, 14, 30))
        self.assertEqual(
            (item["op"], item["operacao"], item["recurso"], item["setor"]),
            ("OP-1", "40", "DOBRA1", "Dobra"),
        )
        self.assertEqual(item["registrada_por"], "Ana")

    def test_op_sem_dispensa_e_repositorio_antigo_nao_quebram(self):
        sem = TraceabilityService(_DbDispensa(rows=[])).trace_op("OP-1")
        self.assertFalse(sem["inspection_waived"])
        self.assertEqual(sem["inspection_waivers"], [])
        antigo = TraceabilityService(FakeDatabase()).trace_op("OP-1")
        self.assertEqual(antigo["inspection_waivers"], [])


def _usuario(role="gestor", gestao=True, escopo=None):
    return SessionUser(
        id=5, name="Conta", role=role, management_access=gestao,
        andon_access=True, operator_access=not gestao, sector_scope=escopo,
    )


class RotasDeGestaoTests(unittest.TestCase):
    def _client(self, db, usuario=None):
        app = create_app(settings=_settings(), database_factory=lambda: None)
        app.dependency_overrides[get_frontend_facade] = lambda: FrontendBackendFacade(db)
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: usuario or _usuario()
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def test_nestings_devolve_campos_crus_aproveitamento_e_resumo(self):
        client = self._client(_db_corte())
        corpo = client.get(
            "/api/v1/traceability/nestings",
            params={"inicio": "2026-10-28T00:00:00", "fim": "2026-10-28T23:59:59"},
        ).json()
        primeiro = next(i for i in corpo["items"] if i["tarefa"] == "T1" and i["nesting"] == 1)
        self.assertEqual(primeiro["aproveitamento_percentual"], 75.0)
        self.assertEqual(primeiro["area_usada"], 1000.0)
        resumo = corpo["aproveitamento"]
        self.assertEqual(resumo["nestings"], 4)
        self.assertEqual(resumo["nestings_com_dado"], 2)
        self.assertEqual(resumo["aproveitamento_medio_percentual"], 70.0)
        self.assertEqual({t["tarefa"] for t in resumo["por_tarefa"]}, {"T1", "T2"})
        # Os totais de tempo anteriores continuam presentes.
        self.assertIn("real_segundos", corpo["totals"])

    def test_resumo_de_aproveitamento_acompanha_a_busca(self):
        client = self._client(_db_corte())
        corpo = client.get(
            "/api/v1/traceability/nestings",
            params={"inicio": "2026-10-28T00:00:00", "fim": "2026-10-28T23:59:59", "search": "T2"},
        ).json()
        self.assertEqual(corpo["aproveitamento"]["nestings"], 2)
        self.assertIsNone(corpo["aproveitamento"]["aproveitamento_medio_percentual"])

    def test_lista_de_dispensadas_devolve_os_campos_e_repassa_os_filtros(self):
        db = _DbDispensa()
        client = self._client(db)
        resposta = client.get(
            "/api/v1/traceability/inspection-waivers",
            params={"inicio": "2026-10-28T00:00:00", "fim": "2026-10-28T23:59:59",
                    "setor": "Dobra", "recurso": "DOBRA1", "op": "OP-1"},
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertEqual(corpo["count"], 1)
        self.assertEqual(corpo["availability"], "disponivel")
        item = corpo["items"][0]
        self.assertIs(item["dispensada"], True)
        self.assertEqual(item["motivo"], "Peça de amostra do cliente")
        self.assertEqual(item["autorizado_por"], "Carlos Qualidade")
        self.assertEqual(item["cracha"], "00123")
        self.assertEqual(item["dispensada_em"], "2026-10-28T14:30:00")
        self.assertEqual((item["op"], item["operacao"], item["recurso"]), ("OP-1", "40", "DOBRA1"))
        filtros = db.chamadas[-1]
        self.assertEqual(filtros["setor_origem"], "Dobra")
        self.assertEqual(filtros["recurso"], "DOBRA1")
        self.assertEqual(filtros["op"], "OP-1")
        self.assertEqual(filtros["inicio"], datetime(2026, 10, 28, 0, 0))
        self.assertEqual(filtros["fim"], datetime(2026, 10, 28, 23, 59, 59))

    def test_lider_tem_o_setor_travado_no_proprio_escopo(self):
        db = _DbDispensa()
        client = self._client(db, _usuario("lider", escopo=["Pintura"]))
        client.get("/api/v1/traceability/inspection-waivers", params={"setor": "Solda"})
        self.assertEqual(db.chamadas[-1]["setor_origem"], "Pintura")

    def test_busca_e_paginacao(self):
        outra = {**DISPENSA, "inspecao_id": 12, "codigo_op": "OP-2",
                 "dispensa_autorizada_por": "Maria", "dispensa_cracha": "9"}
        client = self._client(_DbDispensa([dict(DISPENSA), outra]))
        por_busca = client.get(
            "/api/v1/traceability/inspection-waivers", params={"search": "maria"}
        ).json()
        self.assertEqual([i["op"] for i in por_busca["items"]], ["OP-2"])
        paginado = client.get(
            "/api/v1/traceability/inspection-waivers", params={"page": 1, "page_size": 1}
        ).json()
        self.assertEqual((len(paginado["items"]), paginado["count"]), (1, 2))

    def test_so_gestao_le_a_lista(self):
        client = self._client(_DbDispensa(), _usuario("operador_dobra", gestao=False))
        resposta = client.get("/api/v1/traceability/inspection-waivers")
        self.assertEqual(resposta.status_code, 403)
        self.assertNotIn("items", resposta.json())


class _DbFatos(FakeDatabase):
    def __init__(self, fatos):
        super().__init__()
        self.fatos = fatos

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return [dict(f) for f in self.fatos]


class RecursoDivergenteNaAuditoriaTests(unittest.TestCase):
    def _itens(self, fatos):
        client = RotasDeGestaoTests._client(self, _DbFatos(fatos))
        corpo = client.get("/api/v1/audit/appointments").json()
        return {i["apontamento_id"]: i for i in corpo["items"]}

    def test_deriva_da_divergencia_gravada_nos_eventos(self):
        itens = self._itens([
            {"id": 1, "op": "OP1", "codigo_recurso": "DOBRA1", "maquina": "DOBRA2", "eventos": [
                {"recurso_divergente": False, "recurso_apontado": "DOBRA1"},
                {"recurso_divergente": True, "recurso_apontado": "DOBRA2"},
            ]},
            {"id": 2, "op": "OP2", "codigo_recurso": "DOBRA1", "maquina": "DOBRA1", "eventos": [
                {"recurso_divergente": False, "recurso_apontado": "DOBRA1"},
            ]},
            {"id": 3, "op": "OP3", "codigo_recurso": "DOBRA1", "maquina": "DOBRA1", "eventos": []},
        ])
        self.assertIs(itens[1]["recurso_divergente"], True)
        self.assertEqual(itens[1]["recurso_apontado"], "DOBRA2")
        self.assertEqual(itens[1]["recurso_planejado"], "DOBRA1")
        self.assertIs(itens[2]["recurso_divergente"], False)
        self.assertEqual(itens[2]["recurso_apontado"], "DOBRA1")
        self.assertIs(itens[3]["recurso_divergente"], False)
        self.assertIsNone(itens[3]["recurso_apontado"])


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class SqlContraPostgresTests(unittest.TestCase):
    """Executa o SQL novo em schema isolado do banco de TESTE (nunca o REAL)."""

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database

        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "gestao_disp_" + uuid.uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop(self):
        import psycopg
        from psycopg import sql

        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _dispensar(self, op, setor_origem, recurso, em, autorizada_por="Chefe"):
        return self.db.dispensar_inspecao_qualidade(
            codigo_op=op, numero_operacao="40", produto_codigo="P-9",
            produto_descricao="Suporte", tipo_setor="Qualidade",
            tipo_setor_origem=setor_origem, codigo_recurso=recurso,
            quantidade_total=3, operador="Ana", dispensada_em=em,
            motivo="Amostra", autorizada_por=autorizada_por, cracha="123",
        )

    def test_listar_dispensas_filtra_por_op_setor_recurso_e_periodo(self):
        self._dispensar("OP1", "Dobra", "DOBRA1", datetime(2026, 10, 28, 10, 0))
        self._dispensar("OP1", "Dobra", "DOBRA1", datetime(2026, 10, 28, 12, 0), "Outro")
        self._dispensar("OP2", "Solda", "SOLDA1", datetime(2026, 10, 20, 9, 0))

        todas = self.db.listar_dispensas_inspecao()
        self.assertEqual([r["codigo_op"] for r in todas], ["OP1", "OP1", "OP2"])
        self.assertEqual(todas[0]["dispensa_autorizada_por"], "Outro")  # mais recente primeiro
        self.assertEqual(todas[0]["dispensa_cracha"], "123")
        self.assertEqual(todas[0]["dispensa_motivo"], "Amostra")
        self.assertEqual(todas[0]["setor_origem"], "Dobra")

        self.assertEqual(len(self.db.listar_dispensas_inspecao(op="op1", op_exata=True)), 2)
        self.assertEqual(len(self.db.listar_dispensas_inspecao(op="OP", op_exata=True)), 0)
        self.assertEqual(len(self.db.listar_dispensas_inspecao(op="OP")), 3)
        self.assertEqual(
            [r["codigo_op"] for r in self.db.listar_dispensas_inspecao(setor_origem="solda")],
            ["OP2"],
        )
        self.assertEqual(len(self.db.listar_dispensas_inspecao(recurso="dobra1")), 2)
        periodo = self.db.listar_dispensas_inspecao(
            inicio=datetime(2026, 10, 28, 0, 0), fim=datetime(2026, 10, 28, 23, 59)
        )
        self.assertEqual(len(periodo), 2)

    def test_listas_de_corte_trazem_area_usada_e_fracao_de_sucata(self):
        agora = datetime(2026, 10, 28, 9, 0)
        self.db._now = lambda: agora
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO catalogo_sigmanest_tarefas (codigo_tarefa, sincronizado_em)"
                " VALUES ('T1', %s)",
                (agora,),
            )
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                    area_usada, fracao_sucata, maquina_sigmanest, sincronizado_em
                ) VALUES ('h1', 'T1', 'PRG1', 'CH', 1, 1234.5, 0.2, 'LASER1', %s)
                """,
                (agora,),
            )
            cursor.execute(
                """
                INSERT INTO apontamentos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                    maquina, area_usada, fracao_sucata, status, operador_inicio,
                    data_inicio, operador_fim, data_fim
                ) VALUES ('h1', 'T1', 'PRG1', 'CH', 1, 'LASER1', 1234.5, 0.2,
                          'Finalizado', 'Rui', %s, 'Rui', %s)
                """,
                (datetime(2026, 10, 28, 8, 0), datetime(2026, 10, 28, 8, 30)),
            )
            cursor.execute(
                "INSERT INTO catalogo_sigmanest_ops (linha_hash, codigo_tarefa, codigo_op,"
                " setor_destino, quantidade, ativo, sincronizado_em)"
                " VALUES ('l1', 'T1', 'OP1', 'Dobra', 1, TRUE, %s)",
                (agora,),
            )
        por_periodo = self.db.listar_tempos_nesting_corte(
            inicio=datetime(2026, 10, 28, 0, 0), fim=datetime(2026, 10, 28, 23, 59)
        )
        self.assertEqual(float(por_periodo[0]["area_usada"]), 1234.5)
        self.assertEqual(float(por_periodo[0]["fracao_sucata"]), 0.2)
        por_op = self.db.listar_nestings_corte_por_op("op1")
        self.assertEqual(float(por_op[0]["area_usada"]), 1234.5)
        self.assertEqual(float(por_op[0]["fracao_sucata"]), 0.2)


if __name__ == "__main__":
    unittest.main()
