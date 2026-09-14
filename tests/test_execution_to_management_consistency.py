"""Etapa 4A — consistência entre execução e dados gerenciais.

Prova que o que nasce na Tela do Operador chega íntegro a histórico, estado do
recurso, quantidades, tempos e indicadores, por uma única fonte canônica, e que
a origem da OP (TOTVS, SigmaNEST ou manual) não altera o cálculo.
"""

from datetime import datetime, time, timedelta
import os
from pathlib import Path
import re
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import DEFAULT_SESSION_TIMEZONE, load_postgres_config
from app.database.database import Database
from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory
from mes.services.cut import CutService
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.management import ManagementService
from mes.services.operator_flow import OperatorFlowService
from tests.wave5_helpers import liberar_primeira_peca


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ExecutionToManagementTests(unittest.TestCase):
    """Ciclo completo do operador e sua leitura pelos serviços gerenciais."""

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "etapa4a_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as conexao:
            conexao.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))
        self.agora = datetime.now().replace(microsecond=0)
        self._seed()

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as conexao:
            conexao.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    # ------------------------------------------------------------------
    def _seed(self):
        self.db.publicar_recursos_pcfactory([
            {"codigo": "CNC-01", "nome": "Romi D 1000", "tipo_setor": "Usinagem"},
        ])
        self.db.publicar_catalogo_pcp([{
            "codigo_op": "OP-4A", "produto_codigo": "PROD-1",
            "produto_descricao": "PEÇA DE AUDITORIA", "quantidade": 10,
            "unidade": "UN", "data_emissao": self.agora.date().isoformat(),
        }])
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, ordem, fonte,
                    ativo, sincronizado_em
                ) VALUES (
                    'OP-4A', 'PROD-1', 'PEÇA DE AUDITORIA', '10',
                    'CNC-01', 'USINAGEM', 'Usinagem', 1, 'teste_etapa4a', TRUE, %s
                )
                """,
                (self.agora,),
            )
            cursor.executemany(
                """
                INSERT INTO catalogo_status_recursos (
                    codigo, nome, grupo_codigo, grupo_nome, habilitado,
                    setup, retrabalho, oculto, requer_comentario, sincronizado_em
                ) VALUES (%s, %s, %s, %s, TRUE, %s, %s, FALSE, FALSE, %s)
                """,
                [
                    ("0201", "FALTA DE MATERIAL", "0002", "PARADAS", False, False, self.agora),
                    ("0301", "SETUP", "0003", "SETUP", True, False, self.agora),
                    ("0401", "RETRABALHO", "0004", "RETRABALHO", False, True, self.agora),
                ],
            )
            cursor.execute(
                # Wave 6B: refugo exige crachá de responsável autorizado.
                "INSERT INTO operadores_apontamento"
                " (cracha, nome, ativo, fonte, autorizador_retrabalho)"
                " VALUES ('7001', 'OPERADOR 4A', TRUE, 'teste', TRUE)"
            )
        self.flow = OperatorFlowService(self.db, "OPERADOR 4A")
        self.operacao = self.db.listar_operacoes_para_op("OP-4A")[0]

    def _contexto(self):
        return dict(op="OP-4A", setor="Usinagem", recurso="Romi D 1000", operacao=self.operacao)

    def _executar(self, acao, **extra):
        resultado = self.flow.executar(acao, **self._contexto(), **extra)
        self.assertTrue(resultado.ok, f"{acao}: {resultado.message}")
        return resultado

    def _liberar_primeira_peca(self):
        """Wave 5: o lote só fecha depois da primeira peça aprovada."""

        resultado = liberar_primeira_peca(
            self.db, "OPERADOR 4A", **self._contexto()
        )
        self.assertTrue(resultado.ok, resultado.message)
        return resultado

    def _filtros(self):
        return AnalyticsFilter(
            inicio=self.agora - timedelta(hours=1),
            fim=self.agora + timedelta(hours=1),
        )

    def _rows(self, query, params=()):
        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(linha) for linha in cursor.fetchall()]

    # ------------------------------------------------------------------
    def test_ciclo_completo_alimenta_uma_unica_fonte_por_informacao(self):
        """Início → Setup → Retorno → Parada → Retomada → Retrabalho → Fim."""

        # Wave 6B — em Usinagem o Iniciar passa pelo portão Setup/Qualidade.
        self._liberar_primeira_peca()
        self._executar("Início")
        self._executar("Setup")
        self._executar("Retornar")
        self._executar("Parada", motivo_codigo="0201", comentario="sem chapa")
        self._executar("Retomar")
        self._executar("Retrabalho")
        # Wave 4: boas + refugo têm o planejado como teto. 6 boas + 2 refugos
        # atendem 8 de 10 e a OP permanece aberta; a parcial devolve a OP à
        # fila, então o operador precisa reabrir antes de encerrar as 2
        # restantes. Boa e refugo continuam grandezas separadas.
        parcial = self._executar(
            "Finalizado", pecas_boas=6, refugo=2, operadores_cracha=["7001"]
        )
        self.assertEqual(parcial.code, "finalizacao_parcial")
        self._executar("Início")
        self._executar("Finalizado", pecas_boas=2, operadores_cracha=["7001"])

        apontamento = self._rows("SELECT * FROM apontamentos_operacionais WHERE op = 'OP-4A'")[0]
        self.assertEqual(apontamento["status"], "Finalizado")
        self.assertEqual(int(apontamento["quantidade_boa"]), 8)
        self.assertEqual(int(apontamento["quantidade_refugo"]), 2)
        self.assertEqual(apontamento["codigo_recurso"], "CNC-01")
        self.assertEqual(apontamento["maquina"], "Romi D 1000")

        # 1. Histórico de execução: eventos_apontamento_operador é a fonte.
        estados = [
            linha["estado"]
            for linha in self.db.listar_eventos_apontamento_operador(apontamento["id"])
        ]
        self.assertEqual(
            estados,
            ["fila", "producao", "setup", "producao", "parada", "producao",
             "retrabalho", "parcial", "producao", "finalizado"],
        )

        # 2. Motivo da parada preservado com o código do catálogo.
        parada = self._rows(
            "SELECT motivo, codigo_status_recurso, comentario FROM eventos_apontamento_operador"
            " WHERE apontamento_id = %s AND estado = 'parada'",
            (apontamento["id"],),
        )[0]
        self.assertIn("0201", str(parada["motivo"]))
        self.assertEqual(parada["codigo_status_recurso"], "0201")
        self.assertEqual(parada["comentario"], "sem chapa")

        # 3. Quantidades: eventos_quantidade_producao é a fonte canônica e
        #    mantém boa/refugo separados.
        quantidades = {
            linha["tipo"]: int(linha["quantidade"])
            for linha in self._rows(
                "SELECT tipo, SUM(quantidade) AS quantidade FROM eventos_quantidade_producao"
                " WHERE op = 'OP-4A' GROUP BY tipo"
            )
        }
        self.assertEqual(quantidades.get("boa"), 8)
        self.assertEqual(quantidades.get("refugo"), 2)

        # 4. Estado físico do recurso: eventos_estado_recurso é a fonte.
        estados_recurso = self._rows(
            "SELECT categoria FROM eventos_estado_recurso WHERE recurso = 'Romi D 1000'"
            " ORDER BY id"
        )
        self.assertTrue(estados_recurso)
        self.assertIn(EventCategory.DOWNTIME.value, {linha["categoria"] for linha in estados_recurso})

        # 5. Auditoria/histórico legível.
        historico = self._rows("SELECT tipo, setor FROM historico WHERE op = 'OP-4A'")
        self.assertTrue(any(linha["tipo"] == "Apontamento Operador" for linha in historico))

    def test_gerencial_le_a_mesma_verdade_da_execucao(self):
        # Wave 6B — em Usinagem o Iniciar passa pelo portão Setup/Qualidade.
        self._liberar_primeira_peca()
        self._executar("Início")
        # Wave 4: o planejado (10) é teto de boas + refugo, então 9 boas e 1
        # refugo encerram a operação sem estourar a OP.
        self._executar("Finalizado", pecas_boas=9, refugo=1, operadores_cracha=["7001"])

        management = ManagementService(self.db)
        overview = management.get_overview(self._filtros())
        producao = overview["production"]

        # Quantidades vêm da fonte canônica, não da coluna do apontamento.
        self.assertEqual(producao["source"], "eventos_quantidade_producao")
        self.assertEqual(int(producao["good"]), 9)
        self.assertEqual(int(producao["scrap"]), 1)
        # Refugo não vira peça boa em nenhum ponto do caminho.
        self.assertNotEqual(int(producao["good"]), 10)

        # A leitura gerencial bate com a execução persistida.
        apontamento = self._rows("SELECT * FROM apontamentos_operacionais WHERE op = 'OP-4A'")[0]
        self.assertEqual(int(apontamento["quantidade_boa"]), int(producao["good"]))
        self.assertEqual(int(apontamento["quantidade_refugo"]), int(producao["scrap"]))

    def test_andon_projeta_o_mesmo_estado_e_kpi_sem_recalcular(self):
        self._liberar_primeira_peca()
        self._executar("Início")

        facade = FrontendBackendFacade(self.db)
        filtros = self._filtros()
        operacional = facade.consulta_operacional(filtros)
        andon = facade.andon(filtros)

        recurso_operacional = next(
            linha for linha in operacional["resources"]
            if str(linha.get("recurso") or "") == "Romi D 1000"
        )
        # A consulta operacional declara a fonte canônica do estado.
        self.assertEqual(recurso_operacional["fonte"], "eventos_estado_recurso")

        recursos_andon = [
            recurso
            for setor in andon["sectors"]
            for recurso in setor["resources"]
            if str(recurso.get("name") or "") == "Romi D 1000"
            or str(recurso.get("code") or "") == "CNC-01"
        ]
        self.assertTrue(recursos_andon)
        # O Andon reaproveita a mesma categoria de estado, sem cálculo próprio.
        self.assertEqual(
            recursos_andon[0]["state"]["category"],
            recurso_operacional["categoria"],
        )

    def test_op_de_origem_totvs_usa_exatamente_o_mesmo_calculo(self):
        """Depois de entrar no domínio, a origem não altera nada."""

        with self.db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET fonte = 'totvs_production_order_v1'"
                " WHERE codigo_op = 'OP-4A'"
            )
            cursor.execute(
                "UPDATE catalogo_pcp_ops SET totvs_unique_id = '01|010004|OP-4A'"
                " WHERE codigo_op = 'OP-4A'"
            )
        self.operacao = self.db.listar_operacoes_para_op("OP-4A")[0]
        # Wave 6B — em Usinagem o Iniciar passa pelo portão Setup/Qualidade.
        self._liberar_primeira_peca()
        self._executar("Início")
        self._executar("Finalizado", pecas_boas=10, operadores_cracha=["7001"])

        overview = ManagementService(self.db).get_overview(self._filtros())
        self.assertEqual(int(overview["production"]["good"]), 10)
        # Nenhuma coluna de origem corporativa aparece na execução.
        colunas = {
            linha["column_name"]
            for linha in self._rows(
                "SELECT column_name FROM information_schema.columns"
                " WHERE table_schema = current_schema()"
                " AND table_name IN ('apontamentos_operacionais',"
                " 'eventos_quantidade_producao', 'eventos_estado_recurso')"
            )
        }
        self.assertFalse({c for c in colunas if "totvs" in c or "sigmanest" in c})

    def test_duracao_de_execucao_aberta_e_igual_em_sql_e_em_python(self):
        """Divergência da Etapa 4A: relógio do banco x relógio da aplicação."""

        hoje = self.agora.date().isoformat()
        self.db.publicar_catalogo_sigmanest(
            tarefas=[{"codigo_tarefa": "T-4A", "material": "A36", "espessura": 6.0}],
            programas=[{"codigo_tarefa": "T-4A", "programa": "P1"}],
            ops=[{"linha_hash": "L1", "codigo_tarefa": "T-4A", "codigo_op": "OP-4A",
                  "id_peca": "PROD-1", "setor_destino": "Almoxarifado", "quantidade": 5}],
            planos_corte=[{"plano_hash": "H1", "codigo_tarefa": "T-4A", "programa": "P1",
                           "sequencia_nesting": 1, "maquina_sigmanest": "AMADA_ENSIS",
                           "data_programa": hoje, "quantidade_processo": 1}],
        )
        cut = CutService(self.db, "OPERADOR 4A", cutoff_date=hoje)
        self.assertTrue(cut.iniciar("H1", "Laser Ensis 3015").ok)

        inicio = self._rows(
            "SELECT data_inicio FROM apontamentos_corte ORDER BY id DESC LIMIT 1"
        )[0]["data_inicio"]
        python_segundos = (datetime.now() - inicio).total_seconds()
        sql_segundos = float(
            self.db.listar_tempos_nesting_corte(
                inicio=self.agora - timedelta(hours=1),
                fim=self.agora + timedelta(hours=1),
            )[0]["real_segundos"]
        )
        # Tolerância de 60s cobre o tempo do próprio teste; um desalinhamento
        # de fuso apareceria como múltiplo de hora.
        self.assertLess(
            abs(sql_segundos - python_segundos), 60,
            f"SQL={sql_segundos:.0f}s e Python={python_segundos:.0f}s divergem: "
            "o fuso da sessão PostgreSQL não acompanha o da aplicação.",
        )

        # A tela envia `fim` como 23:59:59 do dia escolhido. Uma janela que
        # termina no futuro não pode transformar tempo que ainda não passou em
        # tempo de corte de um nesting aberto.
        fim_do_dia = float(
            self.db.listar_tempos_nesting_corte(
                inicio=self.agora - timedelta(hours=1),
                fim=datetime.combine(self.agora.date(), time(23, 59, 59)),
            )[0]["real_segundos"]
        )
        self.assertLess(
            abs(fim_do_dia - python_segundos), 60,
            f"Janela até o fim do dia devolveu {fim_do_dia:.0f}s para uma "
            f"execução de {python_segundos:.0f}s: o recorte da janela está "
            "contando tempo futuro.",
        )

    def test_sessao_postgresql_usa_o_mesmo_fuso_da_aplicacao(self):
        agora_python = datetime.now()
        linha = self._rows("SELECT LOCALTIMESTAMP AS agora, current_setting('TimeZone') AS tz")[0]
        self.assertLess(abs((linha["agora"] - agora_python).total_seconds()), 60)
        self.assertTrue(str(linha["tz"]).strip())


class Etapa4AFonteUnicaTests(unittest.TestCase):
    """Garantias estáticas de que não há cálculo duplicado entre telas."""

    def test_andon_nao_recalcula_indicadores(self):
        fonte = (ROOT / "mes/services/andon.py").read_text(encoding="utf-8")
        for termo in ("calculate_oee", "consolidate_physical_time", "build_operator_timeline"):
            with self.subTest(termo=termo):
                self.assertNotIn(termo, fonte)

    def test_frontend_nao_calcula_indicador_industrial(self):
        """O frontend formata; quem calcula indicador é o backend."""

        proibidos = (
            "calculate_oee",
            "disponibilidade *",
            "performance *",
            "* 100 /",
            "quantidade_boa +",
            "quantidade_boa -",
        )
        for arquivo in sorted((ROOT / "web/src/pages").rglob("*.tsx")):
            fonte = arquivo.read_text(encoding="utf-8")
            for termo in proibidos:
                with self.subTest(arquivo=arquivo.name, termo=termo):
                    self.assertNotIn(termo, fonte)

    def test_conversao_de_tempo_tem_formatador_compartilhado(self):
        """Divergência registrada na Etapa 4A.

        ``utils/format.ts`` é o formatador único de segundos. A Management View
        ainda mantém um ``hours()`` local que renderiza o mesmo valor em outro
        formato (``1,5 h`` contra ``1h 30m``). É divergência de apresentação,
        não de cálculo, e a consolidação depende de decisão visual.
        """

        formatador = (ROOT / "web/src/utils/format.ts").read_text(encoding="utf-8")
        self.assertIn("export function formatHours", formatador)
        overview = (ROOT / "web/src/pages/ManagementOverviewPage.tsx").read_text(
            encoding="utf-8"
        )
        duplicadas = overview.count("/ 3600")
        self.assertLessEqual(
            duplicadas, 1,
            "nova conversão local de segundos: use formatHours do utils/format",
        )

    def test_fuso_da_sessao_e_configuravel_com_padrao_explicito(self):
        self.assertTrue(DEFAULT_SESSION_TIMEZONE)
        fonte = (ROOT / "app/database/connection.py").read_text(encoding="utf-8")
        self.assertIn("set_config('TimeZone'", fonte)

    def test_execucao_nao_conhece_origem_corporativa(self):
        for relativo in (
            "mes/services/operator_flow.py",
            "mes/services/production.py",
            "mes/services/management.py",
            "mes/services/andon.py",
            "mes/analytics/oee.py",
        ):
            fonte = (ROOT / relativo).read_text(encoding="utf-8")
            codigo = re.sub(r'""".*?"""', "", fonte, flags=re.S)
            for termo in ("totvs", "sigmanest"):
                with self.subTest(arquivo=relativo, termo=termo):
                    self.assertNotIn(termo, codigo.casefold())


if __name__ == "__main__":
    unittest.main()
