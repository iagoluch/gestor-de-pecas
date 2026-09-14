"""Etapa 3.1 — contrato SigmaNEST → Gestor.

Os testes usam linhas fiéis à auditoria real de `SNDBase2026` (27/08/2026), sem
tocar no banco SigmaNEST. Eles provam a semântica funcional obrigatória: a OP
pertence ao produto/peça, e tarefa/programa/nesting apenas agrupam produtos.
"""

from datetime import datetime, timedelta
import os
from pathlib import Path
import re
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.schema import SCHEMA_VERSION
from mes.services.cut import CutService
from mes.services.sigmanest_sync import SigmaNestSyncService

from backend.integrations.sigmanest_sqlserver import (
    SigmaNestConfigurationError,
    SigmaNestSqlServerGateway,
    build_sigmanest_dsn,
    mask_dsn,
)
from mes.integrations.sigmanest import (
    SigmaNestPlanningService,
    SigmaNestPlanningSnapshot,
)


ROOT = Path(__file__).resolve().parents[1]


# Recorte fiel a linhas reais observadas na auditoria: a tarefa T2915 possui os
# programas 7040 e 7041; o programa 8501 agrupa peças de OPs diferentes.
PLANOS = [
    {
        "TaskName": "T2915", "ProgramName": "7040", "SheetName": "S197",
        "MachineName": "Messer_XPR_300", "RepeatID": 1, "ArchivePacketID": 15148,
        "UsedArea": 1.0, "ScrapFraction": 0.2, "CuttingTime": 900.0,
        "PostDateTime": datetime(2026, 5, 8, 8, 26, 26), "CompDate": None,
        "TransType": "SN100",
    },
    {
        "TaskName": "T2915", "ProgramName": "7040", "SheetName": "S197",
        "MachineName": "Messer_XPR_300", "RepeatID": 1, "ArchivePacketID": 15219,
        "UsedArea": 1.0, "ScrapFraction": 0.2, "CuttingTime": 900.0,
        "PostDateTime": datetime(2026, 5, 12, 11, 51, 11),
        "CompDate": datetime(2026, 5, 14, 7, 54, 57), "TransType": "SN102",
    },
    {
        "TaskName": "T2915", "ProgramName": "7041", "SheetName": "S198",
        "MachineName": "Messer_XPR_300", "RepeatID": 1, "ArchivePacketID": 15220,
        "UsedArea": 1.0, "ScrapFraction": 0.3, "CuttingTime": 600.0,
        "PostDateTime": datetime(2026, 5, 12, 12, 0, 0), "CompDate": None,
        "TransType": "SN100",
    },
    {
        "TaskName": "T3432", "ProgramName": "8501", "SheetName": "S420",
        "MachineName": "Amada_ensis", "RepeatID": 1, "ArchivePacketID": 16001,
        "UsedArea": 2.0, "ScrapFraction": 0.1, "CuttingTime": 1200.0,
        "PostDateTime": datetime(2026, 8, 10, 13, 55, 40),
        "CompDate": datetime(2026, 8, 11, 10, 52, 40), "TransType": "SN102",
    },
]

PECAS = [
    {
        "ProgramName": "7040", "SheetName": "S197", "PartName": "PNT002002003",
        "WONumber": "PCMDO701001", "QtyInProcess": 5, "MasterPartQty": 5,
        "CuttingTime": 100.0, "TrueArea": 0.5, "TransType": "SN100",
    },
    {
        "ProgramName": "7040", "SheetName": "S197", "PartName": "PNT002001012",
        "WONumber": "PCMCUV01002", "QtyInProcess": 2, "MasterPartQty": 2,
        "CuttingTime": 80.0, "TrueArea": 0.3, "TransType": "SN100",
    },
    {
        "ProgramName": "7041", "SheetName": "S198", "PartName": "PNT002002003",
        "WONumber": "PCMDO701001", "QtyInProcess": 3, "MasterPartQty": 3,
        "CuttingTime": 60.0, "TrueArea": 0.2, "TransType": "SN100",
    },
    {
        "ProgramName": "8501", "SheetName": "S420", "PartName": "PSM014003121",
        "WONumber": "00617399002", "QtyInProcess": 1, "MasterPartQty": 1,
        "CuttingTime": 40.0, "TrueArea": 0.1, "TransType": "SN102",
    },
]


def _snapshot(**kwargs) -> SigmaNestPlanningSnapshot:
    return SigmaNestSqlServerGateway.montar_snapshot(PLANOS, PECAS, **kwargs)


class SigmaNestMapeamentoTests(unittest.TestCase):
    def test_mapeamento_e_deterministico(self):
        self.assertEqual(_snapshot(), _snapshot())

    def test_tarefa_pode_conter_varios_programas(self):
        tarefas = {task.codigo_tarefa: task for task in _snapshot().tasks}
        self.assertEqual(tarefas["T2915"].programas, ("7040", "7041"))
        self.assertEqual(len(tarefas["T2915"].plans), 2)

    def test_programa_pode_conter_varias_ordens(self):
        plano = next(
            plan for plan in _snapshot().plans if plan.program_name == "7040"
        )
        self.assertEqual(
            sorted(plano.ordens_de_producao), ["PCMCUV01002", "PCMDO701001"]
        )
        self.assertEqual(len(plano.parts), 2)

    def test_uma_op_pode_estar_em_varios_nestings(self):
        snapshot = _snapshot()
        ocorrencias = [
            plan.program_name
            for plan in snapshot.plans
            if "PCMDO701001" in plan.ordens_de_producao
        ]
        self.assertEqual(sorted(ocorrencias), ["7040", "7041"])

    def test_agrupamentos_nao_possuem_op_propria(self):
        """Nem tarefa, nem plano, nem nesting expõem atributo de OP 1:1."""

        snapshot = _snapshot()
        task = snapshot.tasks[0]
        plan = snapshot.plans[0]
        for objeto in (task, plan):
            with self.subTest(objeto=type(objeto).__name__):
                self.assertFalse(hasattr(objeto, "codigo_op"))
                self.assertFalse(hasattr(objeto, "wo_number"))
        # A OP existe somente na linha de peça.
        self.assertTrue(hasattr(snapshot.part_lines[0], "codigo_op"))

    def test_maquina_do_sigmanest_e_preservada(self):
        maquinas = {plan.machine_name for plan in _snapshot().plans}
        self.assertEqual(maquinas, {"Messer_XPR_300", "Amada_ensis"})

    def test_conclusao_do_nesting_sobrevive_ao_pacote_mais_recente(self):
        plano = next(
            plan for plan in _snapshot().plans if plan.program_name == "7040"
        )
        self.assertEqual(plano.archive_packet_id, 15219)
        self.assertEqual(plano.completed_at, datetime(2026, 5, 14, 7, 54, 57))

    def test_reprocessamento_nao_duplica_nesting(self):
        primeiro = _snapshot()
        repetido = SigmaNestSqlServerGateway.montar_snapshot(
            PLANOS + PLANOS, PECAS, filtro_tarefas=None
        )
        self.assertEqual(len(repetido.plans), len(primeiro.plans))
        self.assertEqual(
            [plan.program_name for plan in repetido.plans],
            [plan.program_name for plan in primeiro.plans],
        )

    def test_filtro_por_tarefa_nao_vaza_outras_tarefas(self):
        snapshot = _snapshot(filtro_tarefas={"T2915"})
        self.assertEqual([task.codigo_tarefa for task in snapshot.tasks], ["T2915"])


class SigmaNestCorrelacaoTests(unittest.TestCase):
    class _GatewayFake:
        def __init__(self, snapshot):
            self.snapshot = snapshot
            self.chamadas = []

        def ler_planejamento(self, *, desde=None, tarefas=None):
            self.chamadas.append((desde, tuple(tarefas or ())))
            return self.snapshot

    def test_correlacao_usa_a_op_da_peca_e_nunca_cria_op_nova(self):
        snapshot = _snapshot()
        conhecidas = ["PCMDO701001", "00617399002"]
        correlacoes, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, conhecidas
        )
        self.assertEqual(sorted(correlacoes), ["00617399002", "PCMDO701001"])
        self.assertEqual(correlacoes["PCMDO701001"].tarefas, ("T2915",))
        self.assertEqual(correlacoes["PCMDO701001"].programas, ("7040", "7041"))
        self.assertEqual(correlacoes["00617399002"].maquinas, ("Amada_ensis",))
        # A OP vista no SigmaNEST e ausente do Gestor não é inventada.
        self.assertEqual(desconhecidas, ("PCMCUV01002",))

    def test_registro_desconhecido_nao_recebe_correlacao_inventada(self):
        correlacoes, desconhecidas = SigmaNestPlanningService.correlacionar(
            _snapshot(), []
        )
        self.assertEqual(correlacoes, {})
        self.assertEqual(
            sorted(desconhecidas), ["00617399002", "PCMCUV01002", "PCMDO701001"]
        )

    def test_comparacao_de_op_ignora_caixa_como_o_restante_do_gestor(self):
        correlacoes, _ = SigmaNestPlanningService.correlacionar(
            _snapshot(), ["pcmdo701001"]
        )
        self.assertIn("PCMDO701001", correlacoes)

    def test_servico_delega_a_leitura_ao_gateway(self):
        gateway = self._GatewayFake(_snapshot())
        servico = SigmaNestPlanningService(gateway)
        servico.snapshot(desde=datetime(2026, 8, 1), tarefas=["T2915"])
        self.assertEqual(gateway.chamadas, [(datetime(2026, 8, 1), ("T2915",))])


class SigmaNestSegurancaTests(unittest.TestCase):
    ADAPTADOR = ROOT / "backend/integrations/sigmanest_sqlserver.py"

    def test_adaptador_nao_possui_instrucao_de_escrita(self):
        fonte = self.ADAPTADOR.read_text(encoding="utf-8")
        codigo = "\n".join(
            linha for linha in fonte.splitlines() if not linha.strip().startswith("#")
        )
        for verbo in (
            "INSERT ", "UPDATE ", "DELETE ", "MERGE ", "DROP ", "ALTER ",
            "TRUNCATE", "CREATE TABLE", "EXEC ", "GRANT ",
        ):
            with self.subTest(verbo=verbo.strip()):
                self.assertNotIn(verbo, codigo.upper())

    def test_conexao_e_declarada_somente_leitura(self):
        fonte = self.ADAPTADOR.read_text(encoding="utf-8")
        self.assertIn("readonly=True", fonte)
        self.assertIn("ApplicationIntent=ReadOnly", fonte)
        self.assertIn("WITH (NOLOCK)", fonte)

    def test_dsn_exige_configuracao_e_nunca_expoe_a_senha(self):
        with self.assertRaises(SigmaNestConfigurationError):
            build_sigmanest_dsn({})
        dsn = build_sigmanest_dsn(
            {
                "SIGMANEST_SERVER": "servidor,1433",
                "SIGMANEST_DATABASE": "SNDBase2026",
                "SIGMANEST_USER": "ti_consulta",
                "SIGMANEST_PASSWORD": "segredo-super-secreto",
            }
        )
        self.assertIn("ApplicationIntent=ReadOnly", dsn)
        self.assertNotIn("segredo-super-secreto", mask_dsn(dsn))
        self.assertIn("PWD=***", mask_dsn(dsn))

    def test_dominio_do_gestor_nao_conhece_tabelas_do_sigmanest(self):
        tabelas = ("ProgArchive", "STPIPArc", "WONumber", "SNDBase")
        permitidos = {
            ROOT / "backend/integrations/sigmanest_sqlserver.py",
            ROOT / "scripts/auditar_sigmanest.py",
        }
        for pasta in ("mes", "backend", "app"):
            for arquivo in sorted((ROOT / pasta).rglob("*.py")):
                if "__pycache__" in arquivo.parts or arquivo in permitidos:
                    continue
                fonte = arquivo.read_text(encoding="utf-8")
                # models.py/gateway.py documentam a origem em docstring; o que
                # não pode existir é SQL do SigmaNEST fora do adaptador.
                codigo = re.sub(r'""".*?"""', "", fonte, flags=re.S)
                for tabela in tabelas:
                    with self.subTest(arquivo=str(arquivo.relative_to(ROOT)), tabela=tabela):
                        self.assertNotIn(f"FROM {tabela}", codigo)
                        self.assertNotIn(f"JOIN {tabela}", codigo)

    def test_fluxo_novo_nao_usa_qlik(self):
        for relativo in (
            "backend/integrations/sigmanest_sqlserver.py",
            "mes/integrations/sigmanest/models.py",
            "mes/integrations/sigmanest/gateway.py",
            "scripts/auditar_sigmanest.py",
        ):
            with self.subTest(arquivo=relativo):
                self.assertNotIn(
                    "qlik", (ROOT / relativo).read_text(encoding="utf-8").casefold()
                )


class _GatewayFixo:
    """Gateway determinístico no formato exato produzido pelo adaptador real."""

    def __init__(self, planos=PLANOS, pecas=PECAS):
        self.planos = planos
        self.pecas = pecas
        self.chamadas = []

    def ler_planejamento(self, *, desde=None, tarefas=None):
        self.chamadas.append(desde)
        planos = self.planos
        if desde is not None:
            planos = [item for item in planos if item["PostDateTime"] >= desde]
        programas = {item["ProgramName"] for item in planos}
        pecas = [item for item in self.pecas if item["ProgramName"] in programas]
        return SigmaNestSqlServerGateway.montar_snapshot(planos, pecas)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class SigmaNestSyncPostgresTests(unittest.TestCase):
    """Projeção incremental do planejamento até a fila canônica de Corte."""

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "sigmanest_sync_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as conexao:
            conexao.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
            )
        self.db = Database(
            make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        )
        # OPs canônicas, como se tivessem chegado do TOTVS.
        self.db.publicar_catalogo_pcp(
            [
                {
                    "codigo_op": "PCMDO701001", "produto_codigo": "PNT002002003",
                    "produto_descricao": "BRACO ARTICULACAO", "quantidade": 10,
                    "unidade": "UN", "data_emissao": "2026-05-01",
                },
                {
                    "codigo_op": "00617399002", "produto_codigo": "PSM014003121",
                    "produto_descricao": "SUPORTE", "quantidade": 4,
                    "unidade": "UN", "data_emissao": "2026-08-01",
                },
            ]
        )
        self.gateway = _GatewayFixo()
        self.service = SigmaNestSyncService(self.db, self.gateway)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as conexao:
            conexao.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )

    def _contar(self, tabela):
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM {tabela}")
            return int(cursor.fetchone()["total"])

    def test_migration_17_adiciona_procedencia_sem_quebrar_o_schema(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        # A migration 17 é o piso desta garantia; o schema segue evoluindo de
        # forma aditiva (18 preservou o marco terminal, 19 criou a outbox
        # outbound). Fixar o número exato quebraria a cada migration nova sem
        # dizer nada sobre a procedência SigmaNEST que este teste protege.
        self.assertGreaterEqual(SCHEMA_VERSION, 17)
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'catalogo_sigmanest_planos_corte'
                """
            )
            colunas = {linha["column_name"] for linha in cursor.fetchall()}
        for coluna in (
            "sigmanest_repeat_id", "sigmanest_archive_packet_id",
            "sigmanest_comp_date", "sigmanest_trans_type", "sigmanest_synced_at",
        ):
            with self.subTest(coluna=coluna):
                self.assertIn(coluna, colunas)

    def test_sincronizacao_projeta_tarefa_programa_nesting_e_pecas(self):
        resultado = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertEqual(resultado.tarefas, 2)
        self.assertEqual(resultado.nestings, 3)
        self.assertEqual(self._contar("catalogo_sigmanest_tarefas"), 2)
        self.assertEqual(self._contar("catalogo_sigmanest_planos_corte"), 3)
        # A granularidade da linha de peça é (tarefa, programa, OP, peça):
        # a peça PCMDO701001 é aninhada nos dois programas de T2915 e por isso
        # gera duas linhas. Colapsá-las apagava o vínculo plano -> OP.
        self.assertEqual(self._contar("catalogo_sigmanest_ops"), 4)
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo_tarefa, codigo_op, programa
                FROM catalogo_sigmanest_ops
                WHERE codigo_tarefa = 'T2915'
                ORDER BY programa, codigo_op
                """
            )
            linhas = [
                (linha["codigo_op"], linha["programa"]) for linha in cursor.fetchall()
            ]
        self.assertEqual(
            linhas,
            [
                ("PCMCUV01002", "7040"),
                ("PCMDO701001", "7040"),
                ("PCMDO701001", "7041"),
            ],
        )
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo_tarefa, COUNT(DISTINCT programa) AS programas
                FROM catalogo_sigmanest_planos_corte
                GROUP BY codigo_tarefa
                """
            )
            por_tarefa = {
                linha["codigo_tarefa"]: linha["programas"] for linha in cursor.fetchall()
            }
        self.assertEqual(por_tarefa["T2915"], 2)

    def test_nesting_preserva_varias_ops_e_a_maquina_real(self):
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT codigo_tarefa, COUNT(DISTINCT codigo_op) AS ops
                FROM catalogo_sigmanest_ops GROUP BY codigo_tarefa
                """
            )
            ops = {linha["codigo_tarefa"]: linha["ops"] for linha in cursor.fetchall()}
            cursor.execute(
                "SELECT DISTINCT maquina_sigmanest FROM catalogo_sigmanest_planos_corte"
            )
            maquinas = {linha["maquina_sigmanest"] for linha in cursor.fetchall()}
        self.assertEqual(ops["T2915"], 2)
        self.assertEqual(maquinas, {"Messer_XPR_300", "Amada_ensis"})

    def test_sincronizacao_e_idempotente(self):
        primeiro = self.service.sincronizar(desde=datetime(2026, 1, 1))
        tabelas = (
            "catalogo_sigmanest_tarefas", "catalogo_sigmanest_programas",
            "catalogo_sigmanest_planos_corte", "catalogo_sigmanest_ops",
        )
        contagens = {tabela: self._contar(tabela) for tabela in tabelas}
        segundo = self.service.sincronizar(desde=datetime(2026, 1, 1))
        for tabela, total in contagens.items():
            with self.subTest(tabela=tabela):
                self.assertEqual(self._contar(tabela), total)
        self.assertEqual(primeiro.nestings, segundo.nestings)

    def test_marca_dagua_torna_a_leitura_incremental(self):
        self.assertIsNone(self.service.marca_dagua())
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        marca = self.service.marca_dagua(overlap_days=7)
        self.assertEqual(marca, datetime(2026, 8, 10) - timedelta(days=7))
        self.service.sincronizar()
        self.assertIsNotNone(self.gateway.chamadas[-1])

    def test_janela_incremental_nao_inativa_o_que_ficou_de_fora(self):
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.service.sincronizar(desde=datetime(2026, 8, 1))
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM catalogo_sigmanest_planos_corte WHERE ativo IS TRUE"
            )
            self.assertEqual(int(cursor.fetchone()["total"]), 3)

    def test_sigmanest_nunca_cria_op_no_catalogo_canonico(self):
        antes = self._contar("catalogo_pcp_ops")
        resultado = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertEqual(self._contar("catalogo_pcp_ops"), antes)
        self.assertIn("PCMCUV01002", resultado.ordens_sem_op_no_gestor)
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("PCMCUV01002",),
            )
            self.assertEqual(int(cursor.fetchone()["total"]), 0)

    def test_correlacao_wonumber_com_op_totvs(self):
        resultado = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertEqual(resultado.ordens_correlacionadas, 2)
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT o.codigo_op, o.codigo_tarefa
                FROM catalogo_sigmanest_ops o
                JOIN catalogo_pcp_ops pcp ON pcp.codigo_op = o.codigo_op
                ORDER BY o.codigo_op
                """
            )
            correlacionadas = [
                (linha["codigo_op"], linha["codigo_tarefa"]) for linha in cursor.fetchall()
            ]
        self.assertEqual(
            correlacionadas, [("00617399002", "T3432"), ("PCMDO701001", "T2915")]
        )

    def test_fila_de_corte_recebe_o_planejamento_sincronizado(self):
        """Somente o que ainda não foi concluído no SigmaNEST vira trabalho.

        Na fixture real, o programa 7040 possui ``CompDate`` e o 7041 não; o
        8501 (Laser) também já está concluído na origem.
        """

        self.service.sincronizar(desde=datetime(2026, 1, 1))
        cut = CutService(self.db, "Operador", cutoff_date="2026-01-01")

        plasma = cut.listar_fila("Plasma TerraBlade 4")
        self.assertEqual([linha["codigo_tarefa"] for linha in plasma], ["T2915"])
        self.assertEqual(plasma[0]["status"], "Aguardando")
        # 7040 saiu da fila por já estar concluído na origem; 7041 permanece.
        self.assertEqual(plasma[0]["nesting_count"], 1)
        self.assertEqual(plasma[0]["programa"], "7041")

        # Todo o nesting do Laser já estava concluído no SigmaNEST.
        self.assertEqual(cut.listar_fila("Laser Ensis 3015"), [])

    def test_nesting_concluido_no_sigmanest_sai_da_fila_sem_efeito_colateral(self):
        """Correção complementar da Etapa 3.1.

        ``sigmanest_comp_date`` preenchido oculta o nesting da fila ativa. Ele
        continua persistido e auditável, nenhum apontamento é criado, o
        ``apontamentos_corte`` não é marcado como finalizado e o roteiro da OP
        não avança.
        """

        self.service.sincronizar(desde=datetime(2026, 1, 1))
        cut = CutService(self.db, "Operador", cutoff_date="2026-01-01")

        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT programa, plano_hash, sigmanest_comp_date, ativo
                FROM catalogo_sigmanest_planos_corte ORDER BY programa
                """
            )
            planos = {linha["programa"]: dict(linha) for linha in cursor.fetchall()}

        # 1. CompDate NULL pode aparecer na fila.
        self.assertIsNone(planos["7041"]["sigmanest_comp_date"])
        visiveis = {
            hash_
            for linha in cut.listar_fila("Plasma TerraBlade 4")
            for hash_ in linha["plano_hashes"]
        }
        self.assertIn(planos["7041"]["plano_hash"], visiveis)

        # 2. CompDate preenchido não aparece na fila ativa.
        for programa in ("7040", "8501"):
            with self.subTest(programa=programa):
                self.assertIsNotNone(planos[programa]["sigmanest_comp_date"])
                self.assertNotIn(planos[programa]["plano_hash"], visiveis)
        self.assertEqual(cut.listar_fila("Laser Ensis 3015"), [])

        # 3. O registro concluído continua persistido, ativo e auditável.
        self.assertEqual(len(planos), 3)
        for programa in ("7040", "8501"):
            with self.subTest(programa=programa):
                self.assertTrue(planos[programa]["ativo"])

        # 4. Nenhum apontamento foi criado por causa da conclusão na origem.
        for tabela in (
            "apontamentos_corte", "apontamentos_operacionais",
            "eventos_apontamento_operador", "eventos_estado_recurso",
            "eventos_quantidade_producao",
        ):
            with self.subTest(tabela=tabela):
                self.assertEqual(self._contar(tabela), 0)

        # 5. Nenhuma OP avançou: a tarefa continua sem status de Destaque e o
        #    roteiro não foi concluído automaticamente.
        tarefa = self.db.materializar_tarefa_catalogo("T2915")
        self.assertIsNone(tarefa["status"])
        self.assertEqual(self._contar("historico"), 0)

    def test_conclusao_na_origem_e_idempotente_e_reversivel_pela_origem(self):
        """Reprocessar não duplica, e a fila acompanha o dado da origem."""

        self.service.sincronizar(desde=datetime(2026, 1, 1))
        cut = CutService(self.db, "Operador", cutoff_date="2026-01-01")
        self.assertEqual(self._contar("catalogo_sigmanest_planos_corte"), 3)
        self.assertEqual(cut.listar_fila("Laser Ensis 3015"), [])

        self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertEqual(self._contar("catalogo_sigmanest_planos_corte"), 3)
        self.assertEqual(cut.listar_fila("Laser Ensis 3015"), [])

        # Se a origem deixar de informar a conclusão, o nesting volta à fila
        # sem qualquer intervenção manual no Gestor.
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogo_sigmanest_planos_corte SET sigmanest_comp_date = NULL"
            )
        self.assertEqual(
            [linha["codigo_tarefa"] for linha in cut.listar_fila("Laser Ensis 3015")],
            ["T3432"],
        )

    def test_materializacao_leva_a_op_correlacionada_para_o_fluxo_canonico(self):
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        tarefa = self.db.materializar_tarefa_catalogo("T2915")
        self.assertIsNotNone(tarefa)
        ops = self.db.listar_ops_por_tarefa(tarefa["id"])
        self.assertEqual(
            sorted(item["codigo_op"] for item in ops),
            ["PCMCUV01002", "PCMDO701001"],
        )

    def test_transtype_e_procedencia_ficam_como_dado_bruto(self):
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT sigmanest_trans_type, sigmanest_comp_date,
                       sigmanest_archive_packet_id, sigmanest_synced_at
                FROM catalogo_sigmanest_planos_corte WHERE programa = '7040'
                """
            )
            linha = dict(cursor.fetchone())
            cursor.execute(
                "SELECT DISTINCT status_programa FROM catalogo_sigmanest_planos_corte"
            )
            status = {item["status_programa"] for item in cursor.fetchall()}
        self.assertEqual(linha["sigmanest_trans_type"], "SN102")
        self.assertEqual(linha["sigmanest_comp_date"], datetime(2026, 5, 14, 7, 54, 57))
        self.assertEqual(linha["sigmanest_archive_packet_id"], 15219)
        self.assertIsNotNone(linha["sigmanest_synced_at"])
        # Nenhum status de negócio foi derivado do TransType.
        self.assertEqual(status, {None})

    def test_sincronizacao_nao_cria_apontamento(self):
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        for tabela in (
            "apontamentos_corte", "apontamentos_operacionais",
            "eventos_apontamento_operador", "eventos_estado_recurso",
        ):
            with self.subTest(tabela=tabela):
                self.assertEqual(self._contar(tabela), 0)


    def test_tarefa_nova_entra_na_fila_sozinha_no_ciclo_seguinte(self):
        """Wave 2: o operador do Corte não pesquisa para descobrir tarefa nova.

        O primeiro ciclo materializa o que existia. Quando o SigmaNEST passa a
        publicar um plano novo, o ciclo seguinte — automático, com a mesma
        janela incremental — já o coloca na fila local. Nenhuma pesquisa,
        nenhum refresh e nenhuma OP criada a partir do SigmaNEST.
        """

        cut = CutService(self.db, "Operador", cutoff_date="2026-01-01")
        self.service.sincronizar(desde=datetime(2026, 1, 1))
        antes = {linha["codigo_tarefa"] for linha in cut.listar_fila("Laser Ensis 3015")}
        self.assertEqual(antes, set())
        ops_antes = self._contar("catalogo_pcp_ops")

        novo_plano = {
            "TaskName": "T3432", "ProgramName": "8777", "SheetName": "S777",
            "MachineName": "Amada_ensis", "RepeatID": 1, "ArchivePacketID": 16777,
            "UsedArea": 1.5, "ScrapFraction": 0.15, "CuttingTime": 540.0,
            "PostDateTime": datetime(2026, 8, 20, 9, 0, 0), "CompDate": None,
            "TransType": "SN100",
        }
        nova_peca = {
            "ProgramName": "8777", "SheetName": "S777", "PartName": "PSM014003121",
            "WONumber": "00617399002", "QtyInProcess": 2, "MasterPartQty": 2,
            "CuttingTime": 70.0, "TrueArea": 0.2, "TransType": "SN100",
        }
        self.gateway.planos = [*PLANOS, novo_plano]
        self.gateway.pecas = [*PECAS, nova_peca]

        self.service.sincronizar(overlap_days=7)

        fila = cut.listar_fila("Laser Ensis 3015")
        self.assertEqual([linha["codigo_tarefa"] for linha in fila], ["T3432"])
        self.assertEqual(fila[0]["programa"], "8777")
        self.assertEqual(fila[0]["status"], "Aguardando")
        # A correlação com o TOTVS continua sendo a autoridade sobre a OP.
        self.assertEqual(self._contar("catalogo_pcp_ops"), ops_antes)

    def test_assinatura_distingue_ciclo_sem_novidade_de_ciclo_com_tarefa_nova(self):
        """Sinal barato usado pelo ciclo automático para não publicar à toa."""

        primeiro = self.service.sincronizar(desde=datetime(2026, 1, 1))
        repetido = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertTrue(primeiro.assinatura)
        self.assertEqual(primeiro.assinatura, repetido.assinatura)
        self.assertEqual(
            self._contar("catalogo_sigmanest_planos_corte"), primeiro.nestings
        )

        self.gateway.planos = [
            *PLANOS,
            {
                "TaskName": "T2915", "ProgramName": "7042", "SheetName": "S199",
                "MachineName": "Messer_XPR_300", "RepeatID": 1,
                "ArchivePacketID": 15300, "UsedArea": 1.0, "ScrapFraction": 0.2,
                "CuttingTime": 300.0,
                "PostDateTime": datetime(2026, 5, 13, 8, 0, 0), "CompDate": None,
                "TransType": "SN100",
            },
        ]
        depois = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertNotEqual(primeiro.assinatura, depois.assinatura)
        self.assertEqual(depois.nestings, primeiro.nestings + 1)


    def test_repeticao_da_chapa_vira_nesting_proprio_e_conta_como_chapa(self):
        """Wave 3: `1 nesting = 1 chapa` deixa de ser suposição.

        O nesting é `ProgramName + SheetName + RepeatID` — a chapa física do
        programa. Duas repetições do mesmo programa/chapa são duas chapas, e a
        quantidade tem de vir do SigmaNEST, não de uma contagem inventada.
        """

        base = {
            "TaskName": "T3432", "ProgramName": "8777", "SheetName": "S777",
            "MachineName": "Amada_ensis", "UsedArea": 1.5, "ScrapFraction": 0.1,
            "CuttingTime": 300.0, "CompDate": None, "TransType": "SN100",
        }
        self.gateway.planos = [
            *PLANOS,
            {**base, "RepeatID": 1, "ArchivePacketID": 17001,
             "PostDateTime": datetime(2026, 8, 20, 9, 0, 0)},
            {**base, "RepeatID": 2, "ArchivePacketID": 17002,
             "PostDateTime": datetime(2026, 8, 20, 9, 5, 0)},
            {**base, "RepeatID": 3, "ArchivePacketID": 17003,
             "PostDateTime": datetime(2026, 8, 20, 9, 9, 0)},
            # Mesmo programa/chapa/repetição em outro pacote de arquivo: é o
            # MESMO nesting reaparecendo, e não pode virar uma quarta chapa.
            {**base, "RepeatID": 3, "ArchivePacketID": 17004,
             "PostDateTime": datetime(2026, 8, 20, 9, 12, 0)},
        ]
        self.gateway.pecas = [
            *PECAS,
            {"ProgramName": "8777", "SheetName": "S777", "PartName": "PSM014003121",
             "WONumber": "00617399002", "QtyInProcess": 2, "MasterPartQty": 2,
             "CuttingTime": 70.0, "TrueArea": 0.2, "TransType": "SN100"},
        ]

        resultado = self.service.sincronizar(desde=datetime(2026, 1, 1))
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                SELECT sigmanest_repeat_id, plano_hash
                FROM catalogo_sigmanest_planos_corte
                WHERE programa = '8777'
                ORDER BY sigmanest_repeat_id
                """
            )
            linhas = [dict(item) for item in cursor.fetchall()]

        # Três chapas, uma por repetição, com identidades distintas.
        self.assertEqual([linha["sigmanest_repeat_id"] for linha in linhas], [1, 2, 3])
        self.assertEqual(len({linha["plano_hash"] for linha in linhas}), 3)

        # A fila do Corte enxerga as três como chapas do mesmo programa.
        cut = CutService(self.db, "Operador", cutoff_date="2026-01-01")
        fila = cut.listar_fila("Laser Ensis 3015")
        tarefa = next(item for item in fila if item["codigo_tarefa"] == "T3432")
        self.assertEqual(tarefa["quantidade_chapas"], 3)
        self.assertEqual(tarefa["nesting_count"], 3)
        por_programa = {item["programa"]: item["chapas"] for item in tarefa["chapas_por_programa"]}
        self.assertEqual(por_programa["8777"], 3)

        # Reprocessar a mesma janela não cria chapa nova.
        repetido = self.service.sincronizar(desde=datetime(2026, 1, 1))
        self.assertEqual(repetido.nestings, resultado.nestings)
        self.assertEqual(repetido.assinatura, resultado.assinatura)
        self.assertEqual(self._contar("catalogo_sigmanest_planos_corte"), resultado.nestings)


if __name__ == "__main__":
    unittest.main()
