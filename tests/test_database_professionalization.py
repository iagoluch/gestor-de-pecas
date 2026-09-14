"""PostgreSQL integration tests; require an explicitly isolated TEST_DATABASE_URL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import os
import threading
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.migrations import (
    EXPECTED_TABLES,
    OPERATOR_RETURN_CONTEXT_STATEMENTS,
    SCHEMA_VERSION,
)
from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.operator_flow import OperatorFlowService
from mes.services.production import ProductionService
from tests.wave5_helpers import liberar_primeira_peca


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class DatabaseProfessionalizationTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        isolated_dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(isolated_dsn)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_schema_vazio_recebe_baseline_idempotente_com_indices_e_fks(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        self.db.create_tables()
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
            tables = {row["table_name"] for row in cursor.fetchall()}
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            indexes = {row["indexname"] for row in cursor.fetchall()}
            cursor.execute("SELECT COUNT(*) AS total FROM schema_migrations WHERE version = %s", (SCHEMA_VERSION,))
            versions = int(cursor.fetchone()["total"])
            cursor.execute(
                """
                SELECT conname, confdeltype FROM pg_constraint
                WHERE connamespace = current_schema()::regnamespace AND contype = 'f'
                """
            )
            delete_actions = {row["conname"]: row["confdeltype"] for row in cursor.fetchall()}
        self.assertTrue(set(EXPECTED_TABLES).issubset(tables))
        self.assertEqual(versions, 1)
        self.assertIn("idx_apontamento_ativo_op_setor", indexes)
        self.assertIn("idx_historico_data_hora", indexes)
        self.assertIn("c", delete_actions.values())  # CASCADE
        self.assertGreaterEqual(list(delete_actions.values()).count("n"), 2)  # SET NULL

    def test_migration_13_mantem_contexto_historico_nulo(self):
        item = self._appointment("OP-MIGRATION-13")
        self.assertIsNotNone(
            self.db.transicionar_apontamento_operador(item["id"], "retrabalho", "IAGO")
        )
        stopped = self.db.transicionar_apontamento_operador(
            item["id"], "parada", "IAGO", motivo="0029 - PARADA DE TESTE"
        )
        self.assertEqual(stopped["estado_retorno"], "retrabalho")

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE eventos_apontamento_operador DROP COLUMN estado_retorno"
            )
            cursor.execute(
                "ALTER TABLE apontamentos_operacionais DROP COLUMN estado_retorno"
            )
            cursor.execute("DELETE FROM schema_migrations WHERE version = 13")

        self.assertEqual(self.db.create_tables(), SCHEMA_VERSION)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT estado_retorno FROM apontamentos_operacionais WHERE id = %s",
                (item["id"],),
            )
            appointment_return = cursor.fetchone()["estado_retorno"]
            cursor.execute(
                """
                SELECT estado_retorno
                FROM eventos_apontamento_operador
                WHERE apontamento_id = %s
                ORDER BY id
                """,
                (item["id"],),
            )
            event_returns = [row["estado_retorno"] for row in cursor.fetchall()]

        self.assertIsNone(appointment_return)
        self.assertTrue(event_returns)
        self.assertTrue(all(value is None for value in event_returns))
        self.assertTrue(
            all(
                not statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE "))
                for statement in OPERATOR_RETURN_CONTEXT_STATEMENTS
            )
        )

    def test_tarefa_insere_normaliza_e_faz_upsert_sem_apagar_valores(self):
        task_id = self.db.inserir_tarefa(" t100\n", "Aço", 2.75)
        same_id = self.db.inserir_tarefa("T100", None, 3.0)
        task = self.db.buscar_tarefa_por_codigo("t100")
        self.assertEqual(task_id, same_id)
        self.assertEqual(task["material"], "Aço")
        self.assertEqual(task["espessura"], 3.0)
        self.db.atualizar_tarefa_status(task_id, "Destacando")
        self.assertIsNotNone(self.db.buscar_tarefa_por_id(task_id)["data_inicio_destaque"])

    def test_op_e_unica_por_tarefa_e_preserva_correcao_manual(self):
        task_id = self.db.inserir_tarefa("T-OP")
        op_id = self.db.inserir_op_na_tarefa(task_id, "OP1", "Peça", "Aguardando Dobra", 2)
        self.db.atualizar_op(op_id, "Romi 300", 4)
        same_id = self.db.inserir_op_na_tarefa(task_id, "OP1", "Fonte", "Aguardando Usinagem", 8)
        row = self.db.listar_ops_por_tarefa(task_id)[0]
        self.assertEqual(same_id, op_id)
        self.assertEqual(len(self.db.listar_ops_por_tarefa(task_id)), 1)
        self.assertEqual((row["setor_destino_atual"], row["quantidade_atual"]), ("Romi 300", 4))
        self.assertTrue(row["editado"])
        self.assertEqual(self.db.get_first_op_codes_by_task([task_id]), {task_id: "OP1"})

    def test_snapshot_pcp_eh_atomico_inativa_ausentes_e_preserva_operacional(self):
        task_id = self.db.inserir_tarefa("T-PCP-PRESERVADA")
        op_id = self.db.inserir_op_na_tarefa(
            task_id, "OP-OPERACIONAL", "Peca editada", "Aguardando Dobra", 2
        )
        self.db.atualizar_op(op_id, "Romi 300", 4)
        self.db.inserir_historico(
            "OP-OPERACIONAL", "Movimentacao", "Romi 300", "", 1, "IAGO",
            "Peca editada", task_id,
        )
        first = [
            {
                "codigo_op": "OP-PCP-1", "produto_codigo": "P1",
                "produto_descricao": "Produto 1", "quantidade": 10,
                "unidade": "PC", "data_emissao": "2026-01-02",
            },
            {
                "codigo_op": "OP-PCP-2", "produto_codigo": "P2",
                "produto_descricao": "Produto 2", "quantidade": 20,
                "unidade": "PC", "data_emissao": "2026-01-03",
            },
        ]
        self.db.publicar_catalogo_pcp(first)
        self.db.publicar_catalogo_pcp([first[0]])

        self.assertIsNotNone(self.db.buscar_op_catalogo("OP-PCP-1"))
        self.assertIsNone(self.db.buscar_op_catalogo("OP-PCP-2"))
        with self.assertRaises(ValueError):
            self.db.publicar_catalogo_pcp([first[0], first[0]])
        self.assertIsNotNone(self.db.buscar_op_catalogo("OP-PCP-1"))
        operational = self.db.buscar_op_por_codigo("OP-OPERACIONAL")
        self.assertEqual(
            (operational["setor_destino_atual"], operational["quantidade_atual"], operational["editado"]),
            ("Romi 300", 4, True),
        )
        self.assertEqual(len(self.db.get_op_timeline("OP-OPERACIONAL")), 1)

    def test_roteiro_importado_continua_visivel_quando_catalogo_inativa_op(self):
        now = datetime.now().replace(microsecond=0)
        self.db.publicar_catalogo_pcp(
            [{
                "codigo_op": "OP-ROTEIRO-INATIVO",
                "produto_codigo": "P1",
                "produto_descricao": "Produto de teste",
                "quantidade": 2,
                "unidade": "PC",
                "data_emissao": "2026-08-18",
            }],
            sincronizado_em=now,
        )
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, ordem,
                    fonte, ativo, sincronizado_em
                ) VALUES (
                    'OP-ROTEIRO-INATIVO', 'P1', 'Produto de teste', '10',
                    'SERRA4', 'CORTE', 'Serra', 10, 'teste', TRUE, %s
                )
                """,
                (now,),
            )
            cursor.execute(
                "UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = 'OP-ROTEIRO-INATIVO'"
            )

        route = self.db.listar_operacoes_para_op("OP-ROTEIRO-INATIVO")
        self.assertEqual(len(route), 1)
        self.assertEqual((route[0]["numero_operacao"], route[0]["codigo_recurso"]), ("10", "SERRA4"))

    def test_snapshot_sigmanest_materializa_sem_reescrever_correcao(self):
        tasks = [{"codigo_tarefa": "T-CATALOGO", "material": "ACO", "espessura": 2.5}]
        programs = [{"codigo_tarefa": "T-CATALOGO", "programa": "PRG-1"}]
        operations = [{
            "linha_hash": "hash-1", "codigo_tarefa": "T-CATALOGO", "codigo_op": "OP-CAT",
            "id_peca": "Peca catalogo", "setor_destino": "Aguardando Dobra", "quantidade": 3,
            "dobra": "Sim", "usinagem": "Nao", "solda": "Nao", "chanfro": "Nao",
        }]
        self.db.publicar_catalogo_sigmanest(tasks, programs, operations)
        self.assertEqual(self.db.listar_ops_catalogo_tarefa("T-CATALOGO")[0]["dobra"], "Sim")
        task = self.db.materializar_tarefa_catalogo("T-CATALOGO")
        op = self.db.listar_ops_por_tarefa(task["id"])[0]
        self.db.atualizar_op(op["id"], "Romi 300", 7)

        changed = [{**operations[0], "quantidade": 99, "setor_destino": "Aguardando Usinagem"}]
        self.db.publicar_catalogo_sigmanest(tasks, programs, changed)
        operational = self.db.listar_ops_por_tarefa(task["id"])[0]

        self.assertEqual(
            (operational["setor_destino_atual"], operational["quantidade_atual"], operational["editado"]),
            ("Romi 300", 7, True),
        )

    def test_fila_corte_snapshot_inicio_fim_concorrencia_e_preservacao(self):
        tasks = [{"codigo_tarefa": "T-CORTE", "material": "ACO 304", "espessura": 3}]
        programs = [
            {"codigo_tarefa": "T-CORTE", "programa": "P-CORTE-1"},
            {"codigo_tarefa": "T-CORTE", "programa": "P-CORTE-2"},
        ]
        plans = [{
            "plano_hash": "plano-corte-1",
            "codigo_tarefa": "T-CORTE",
            "programa": "P-CORTE-1",
            "nome_chapa": "S420",
            "sequencia_nesting": 1,
            "area_usada": 4_500_000,
            "fracao_sucata": 0.25,
            "quantidade_processo": 1,
            "maquina_sigmanest": "Amada_ensis",
            "tempo_previsto_segundos": 82.5,
            "tempo_previsto_formatado": "00:01:22",
            "data_programa": "2026-08-11",
            "status_programa": "Em Andamento",
        }, {
            "plano_hash": "plano-corte-2",
            "codigo_tarefa": "T-CORTE",
            "programa": "P-CORTE-2",
            "nome_chapa": "S420",
            "sequencia_nesting": 2,
            "area_usada": 4_200_000,
            "fracao_sucata": 0.30,
            "quantidade_processo": 1,
            "maquina_sigmanest": "Amada_ensis",
            "tempo_previsto_segundos": 90,
            "tempo_previsto_formatado": "00:01:30",
            "data_programa": "2026-08-11",
            "status_programa": "Em Andamento",
        }]
        self.db.publicar_catalogo_sigmanest(
            tasks, programs, [], planos_corte=plans
        )

        waiting = self.db.listar_fila_corte("2026-08-01", "Amada_ensis")
        self.assertEqual(len(waiting), 2)
        self.assertEqual(waiting[0]["status"], "Aguardando")
        self.assertEqual(waiting[0]["material"], "ACO 304")

        barrier = threading.Barrier(2)

        def start_cut():
            barrier.wait()
            return self.db.iniciar_apontamento_corte(
                "plano-corte-1", "Laser Ensis 3015", "IAGO", "2026-08-01"
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _value: start_cut(), range(2)))
        first_started = next(result for result in results if result)
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(first_started["status"], "Em processo")

        advance_barrier = threading.Barrier(2)

        def advance_cut():
            advance_barrier.wait()
            return self.db.avancar_nesting_corte(
                first_started["id"],
                "plano-corte-2",
                "ANALISTA",
                "2026-08-01",
                momento=first_started["data_inicio"] + timedelta(minutes=4),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            advance_results = list(executor.map(lambda _value: advance_cut(), range(2)))
        self.assertEqual(sum(result is not None for result in advance_results), 1)
        advanced = next(result for result in advance_results if result is not None)
        first_finished = advanced["finalizado"]
        second_started = advanced["iniciado"]
        self.assertEqual(first_finished["status"], "Finalizado")
        self.assertEqual(int(first_finished["tempo_real_segundos"]), 240)
        self.assertEqual(second_started["status"], "Em processo")
        self.assertEqual(second_started["data_inicio"], first_finished["data_fim"])

        progress = self.db.listar_fila_corte("2026-08-01")
        self.assertEqual(len(progress), 2)
        self.assertEqual({row["status"] for row in progress}, {"Em processo", "Finalizado"})

        second_finished = self.db.finalizar_apontamento_corte(
            second_started["id"],
            "ANALISTA",
            data_fim=second_started["data_inicio"] + timedelta(minutes=4),
        )
        self.assertEqual(second_finished["status"], "Finalizado")
        self.assertIsNone(
            self.db.finalizar_apontamento_corte(second_started["id"], "OUTRO")
        )
        self.assertEqual(self.db.listar_fila_corte("2026-08-01"), [])

        # Uma nova sincronização pode atualizar as métricas sem tocar no
        # snapshot operacional que foi gravado no momento do clique.
        changed = [
            {
                **plan,
                "tempo_previsto_segundos": 999,
                "fracao_sucata": 0.75,
                "status_programa": "Finalizado",
            }
            for plan in plans
        ]
        self.db.publicar_catalogo_sigmanest(
            tasks, programs, [], planos_corte=changed
        )
        history = self.db.listar_apontamentos_corte(status="Finalizado")
        self.assertEqual(len(history), 2)
        self.assertEqual(
            sorted(float(row["tempo_previsto_segundos"]) for row in history),
            [82.5, 90.0],
        )
        self.assertTrue(all(int(row["tempo_real_segundos"]) == 240 for row in history))

    def test_advisory_lock_impede_segunda_sincronizacao(self):
        with self.db.catalog_sync_lock() as first:
            with self.db.catalog_sync_lock() as second:
                self.assertTrue(first)
                self.assertFalse(second)

    def test_correcao_de_op_e_historico_sao_atomicos_e_condicionais(self):
        task_id = self.db.inserir_tarefa("T-OP-ATOMIC")
        op_id = self.db.inserir_op_na_tarefa(task_id, "OP-ATOMIC", "Peça", "Dobra", 2)
        self.assertTrue(self.db.corrigir_op_com_historico(
            op_id, "OP-ATOMIC", "Dobra", 2, "Usinagem", 3, "IAGO", task_id
        ))
        self.assertFalse(self.db.corrigir_op_com_historico(
            op_id, "OP-ATOMIC", "Dobra", 2, "Almoxarifado", 4, "IAGO", task_id
        ))
        self.assertEqual(len(self.db.get_op_timeline("OP-ATOMIC")), 1)

        self.db._after_op_correction = lambda *_args: (
            _ for _ in ()
        ).throw(RuntimeError("falha forçada"))
        with self.assertRaises(RuntimeError):
            self.db.corrigir_op_com_historico(
                op_id, "OP-ATOMIC", "Usinagem", 3, "Almoxarifado", 4, "IAGO", task_id
            )
        op = self.db.buscar_op_por_codigo("OP-ATOMIC")
        self.assertEqual((op["setor_destino_atual"], op["quantidade_atual"]), ("Usinagem", 3))
        self.assertEqual(len(self.db.get_op_timeline("OP-ATOMIC")), 1)

    def test_historico_timeline_periodo_localizacao_e_eventos_separados(self):
        task_id = self.db.inserir_tarefa("T-HIST")
        self.db.inserir_historico("0010", "Movimentação", "Dobra", "", 1, "IAGO", "Peça", task_id, "2026-08-10 10:00:00")
        self.db.inserir_historico("0010", "Movimentação", "Almoxarifado", "", 1, "IAGO", "Peça", task_id, "2026-08-10 11:00:00")
        self.db.registrar_evento_sistema("integracao_falha", "Teste", "timeout")
        self.assertEqual(len(self.db.get_op_timeline("10")), 2)
        self.assertEqual(self.db.get_current_ops()[0]["setor"], "Almoxarifado")
        self.assertEqual(len(self.db.buscar_movimentacoes_periodo(
            datetime_from("2026-08-10 10:30:00"), datetime_from("2026-08-10 11:30:00")
        )), 1)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM historico")
            history_count = int(cursor.fetchone()["total"])
            cursor.execute("SELECT COUNT(*) AS total FROM eventos_sistema")
            event_count = int(cursor.fetchone()["total"])
        self.assertEqual((history_count, event_count), (2, 1))

    def test_movimentos_por_dia_agrega_intervalo_e_preenche_dias_sem_evento(self):
        hoje = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        ontem = hoje - timedelta(days=1)
        for momento in (ontem, hoje, hoje):
            self.db.inserir_historico(
                "OP-DIA", "Movimentação", "Dobra", "", 1, "IAGO", data_hora=momento
            )
        self.db.inserir_historico(
            "T-IGNORADA", "Movimentação", "Destaque", "", 0, "IAGO", data_hora=hoje
        )

        movimentos = dict(self.db.movimentos_por_dia(3))

        self.assertEqual(len(movimentos), 3)
        self.assertEqual(movimentos[ontem.strftime("%d/%m/%Y")], 1)
        self.assertEqual(movimentos[hoje.strftime("%d/%m/%Y")], 2)
        self.assertIn(0, movimentos.values())

    def test_usuarios_criar_autenticar_alterar_resetar_e_ativar(self):
        user_id = self.db.criar_usuario("Admin", "senha-forte", "admin")
        self.assertIsNone(self.db.criar_usuario("Admin", "outra", "admin"))
        self.assertEqual(self.db.autenticar_usuario("Admin", "senha-forte")["id"], user_id)
        self.db.atualizar_nivel_usuario(user_id, "supervisor")
        self.db.resetar_senha_usuario(user_id, "nova-senha")
        self.assertEqual(self.db.autenticar_usuario("Admin", "nova-senha")["nivel"], "supervisor")
        self.db.ativar_desativar_usuario(user_id, False)
        self.assertIsNone(self.db.autenticar_usuario("Admin", "nova-senha"))
        serra_id = self.db.criar_usuario("Operador Serra", "senha-serra", "operador_serra")
        self.assertIsNotNone(serra_id)
        self.assertEqual(self.db.autenticar_usuario("Operador Serra", "senha-serra")["nivel"], "operador_serra")
        corte_id = self.db.criar_usuario("Operador Corte", "senha-corte", "operador_corte")
        self.assertIsNotNone(corte_id)
        self.assertEqual(self.db.autenticar_usuario("Operador Corte", "senha-corte")["nivel"], "operador_corte")
        andon_id = self.db.criar_usuario("Andon", "senha-andon", "andon")
        self.assertIsNotNone(andon_id)
        self.assertEqual(self.db.autenticar_usuario("Andon", "senha-andon")["nivel"], "andon")

    def test_hash_legado_eh_aceito_e_atualizado_apos_login(self):
        user_id = self.db.criar_usuario("Legado", "temporaria", "admin")
        salt = bytes.fromhex("00112233445566778899aabbccddeeff")
        legacy_digest = hashlib.pbkdf2_hmac("sha256", b"senha-legada", salt, 100_000)
        legacy_hash = f"{salt.hex()}:{legacy_digest.hex()}"
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE usuarios SET senha_hash = %s WHERE id = %s", (legacy_hash, user_id)
            )

        self.assertEqual(self.db.autenticar_usuario("Legado", "senha-legada")["id"], user_id)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT senha_hash FROM usuarios WHERE id = %s", (user_id,))
            upgraded_hash = cursor.fetchone()["senha_hash"]
        self.assertTrue(upgraded_hash.startswith("pbkdf2_sha256$600000$"))
        self.assertNotIn("senha-legada", upgraded_hash)

    def _appointment(self, code="OP-FILA"):
        task_id = self.db.inserir_tarefa("T-" + code)
        self.db.inserir_op_na_tarefa(task_id, code, "Peça", "Aguardando Dobra", 2)
        return self.db.enfileirar_apontamento_operacional(code, "Peça", task_id, "Dobra", "1303", "IAGO", 2)

    def test_apontamento_impede_duplicado_e_grava_transicoes_com_historico(self):
        item = self._appointment()
        duplicate = self.db.enfileirar_apontamento_operacional("op-fila", "Peça", item["tarefa_id"], "dobra", "2204", "IAGO", 2)
        started = self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO"
        )
        finished = self.db.transicionar_apontamento_operador(
            item["id"],
            "finalizado",
            "IAGO",
            quantidade_boa=2,
            quantidade_refugo=0,
            setor_destino="Almoxarifado",
        )
        self.assertIsNone(duplicate)
        self.assertEqual(started["status"], "Em processo")
        self.assertEqual(finished["status"], "Finalizado")
        timeline = self.db.get_op_timeline("OP-FILA")
        self.assertEqual(
            [row["tipo"] for row in timeline],
            [
                "Apontamento Operador",
                "Movimentação",
                "Apontamento Operador",
                "Movimentação",
            ],
        )

    def test_catalogos_pcfactory_alimentam_parada_e_evento_do_operador(self):
        now = datetime.now().replace(microsecond=0)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_recursos_pcfactory (
                    codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
                ) VALUES ('DOBRA3', 'EGB1303', 'Dobra', TRUE, 'teste', %s)
                """,
                (now,),
            )
            cursor.execute(
                """
                INSERT INTO catalogo_status_recursos (
                    codigo, nome, grupo_codigo, grupo_nome, habilitado, oculto,
                    requer_comentario, fonte, sincronizado_em
                ) VALUES (
                    '0029', 'AGUARDANDO PONTE', '0004', 'PARADAS DA FABRICA',
                    TRUE, FALSE, FALSE, 'teste', %s
                )
                """,
                (now,),
            )

        self.assertEqual(self.db.listar_recursos_pcfactory("Dobra")[0]["codigo"], "DOBRA3")
        self.assertEqual(
            self.db.listar_status_recursos(somente_paradas=True)[0]["codigo"],
            "0029",
        )

        item = self._appointment("OP-CATALOGO-STATUS")
        self.assertIsNotNone(
            self.db.transicionar_apontamento_operador(item["id"], "producao", "IAGO")
        )
        stopped = self.db.transicionar_apontamento_operador(
            item["id"],
            "parada",
            "IAGO",
            motivo="0029 - AGUARDANDO PONTE",
            codigo_status_recurso="0029",
        )
        self.assertEqual(stopped["codigo_status_recurso"], "0029")
        self.assertEqual(
            self.db.listar_eventos_apontamento_operador(item["id"])[-1]["codigo_status_recurso"],
            "0029",
        )

    def test_andon_usa_catalogo_e_estado_fisico_reais_sem_alterar_dados(self):
        now = datetime.now().replace(microsecond=0)
        self.db.publicar_recursos_pcfactory([
            {"codigo": "R-ANDON-P", "nome": "Recurso Andon Produção", "tipo_setor": "Dobra"},
            {"codigo": "R-ANDON-S", "nome": "Recurso Andon Sem Estado", "tipo_setor": "Dobra"},
        ], fonte="teste_andon")
        state = self.db.transicionar_estado_recurso(
            "R-ANDON-P",
            "parada",
            tipo_setor="Dobra",
            motivo="Falta de material",
            data_hora=now - timedelta(minutes=12),
            origem="teste_andon",
        )
        facade = FrontendBackendFacade(self.db, now_func=lambda: now)
        snapshot = facade.andon(AnalyticsFilter(now - timedelta(hours=1), now))
        resources = {
            item["code"]: item
            for sector in snapshot["sectors"]
            for item in sector["resources"]
        }

        self.assertEqual(snapshot["resource_count"], 1)
        self.assertEqual(resources["R-ANDON-P"]["state"]["category"], "parada")
        self.assertEqual(resources["R-ANDON-P"]["state"]["reason"], "Falta de material")
        self.assertNotIn("R-ANDON-S", resources)
        self.assertEqual(resources["R-ANDON-P"]["state"]["duration_seconds"], 720)
        self.assertEqual(
            self.db.buscar_estado_recurso_atual("R-ANDON-P")["id"],
            state["id"],
        )

    def test_andon_descreve_o_corte_ativo_com_a_repeticao_vinda_do_catalogo(self):
        """Regressão da Wave 4: o contexto de Corte quebrava contra PostgreSQL.

        ``apontamentos_corte`` nunca teve ``sigmanest_repeat_id`` — a coluna é
        do catálogo de planos. A consulta do Andon lia a coluna no apontamento
        e derrubava o snapshot inteiro com ``UndefinedColumn``; os fakes não
        pegavam porque devolviam o campo direto do apontamento.
        """

        now = datetime.now().replace(microsecond=0)
        self.db.publicar_recursos_pcfactory(
            [{"codigo": "LASER1", "nome": "Laser Ensis 3015", "tipo_setor": "Corte"}],
            fonte="teste_andon_corte",
        )
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_tarefas
                    (codigo_tarefa, material, espessura, ativo, sincronizado_em)
                VALUES ('T-ANDON-CORTE', 'A36', 6.35, TRUE, %s)
                """,
                (now,),
            )
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa,
                    sequencia_nesting, quantidade_processo, maquina_sigmanest,
                    sigmanest_repeat_id, data_programa, ativo, sincronizado_em
                ) VALUES (
                    'HASH-ANDON-CORTE', 'T-ANDON-CORTE', '8501',
                    'CHAPA 3000 x 1500', 1, 3, 'AMADA_ENSIS', 2, %s, TRUE, %s
                )
                """,
                (now.date(), now),
            )

        started = self.db.iniciar_apontamento_corte(
            "HASH-ANDON-CORTE",
            "Laser Ensis 3015",
            "Cortador",
            "2026-01-01",
            data_inicio=now - timedelta(minutes=8),
        )
        self.assertIsNotNone(started)
        self.db.transicionar_estado_recurso(
            "LASER1",
            "producao",
            tipo_setor="Corte",
            data_hora=now - timedelta(minutes=8),
            origem="teste_andon_corte",
        )

        # A consulta é o ponto exato que falhava; o contrato de saída é neutro.
        rows = self.db.listar_cortes_ativos_andon()
        self.assertEqual([row["repeticao"] for row in rows], [2])
        self.assertNotIn("sigmanest_repeat_id", rows[0])

        facade = FrontendBackendFacade(self.db, now_func=lambda: now)
        snapshot = facade.andon(AnalyticsFilter(now - timedelta(hours=1), now))
        card = next(
            item
            for sector in snapshot["sectors"]
            for item in sector["resources"]
            if item["code"] == "LASER1"
        )
        self.assertEqual(card["group"], "Laser")
        self.assertEqual(
            card["state"]["activity_description"],
            "Tarefa T-ANDON-CORTE • Programa 8501 "
            "• Chapa CHAPA 3000 x 1500 · repetição 2",
        )

    def test_servico_operador_executa_todos_os_botoes_no_postgresql(self):
        now = datetime.now().replace(microsecond=0)
        # Wave 6B: refugo exige crachá de responsável autorizado.
        self.db.cadastrar_operador_apontamento(
            "1", "Iago", fonte="teste", autorizador_retrabalho=True
        )
        status_rows = (
            ("0029", "AGUARDANDO PONTE", "0004", False, False),
            ("1005", "Set-Up", "0001", True, False),
            ("0040", "AGUARDANDO RETRABALHO PRODUÇÃO", "0004", False, True),
        )
        with self.db.connection() as connection, connection.cursor() as cursor:
            for code, name, group_code, setup, rework in status_rows:
                cursor.execute(
                    """
                    INSERT INTO catalogo_status_recursos (
                        codigo, nome, grupo_codigo, grupo_nome, habilitado, setup,
                        retrabalho, oculto, fonte, sincronizado_em
                    ) VALUES (%s, %s, %s, 'TESTE', TRUE, %s, %s, FALSE, 'teste', %s)
                    """,
                    (code, name, group_code, setup, rework, now),
                )

        operation = {
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA3",
            "descricao_operacao": "DOBRA",
            "produto_codigo": "P-TESTE",
            "produto_descricao": "Peça de teste",
            # Wave 4: boas + refugo têm o planejado como teto. Com 3 previstas,
            # 1 boa + 1 refugo continuam sendo finalização parcial e a última
            # peça boa encerra a operação, que é o ciclo exercitado aqui.
            "quantidade": 3,
        }
        service = OperatorFlowService(self.db, "OPERADOR TESTE")

        # Wave 6B: em Dobra o Iniciar passa pelo portão Setup/Qualidade, e sem
        # a primeira peça aprovada o backend recusa produzir e finalizar.
        liberar_primeira_peca(
            self.db,
            "OPERADOR TESTE",
            op="OP-BOTOES",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        start = service.executar(
            "Início", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        stop = service.executar(
            "Parada",
            op="OP-BOTOES",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            motivo_codigo="0029",
        )
        resume_after_stop = service.executar(
            "Início", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        setup = service.executar(
            "Setup", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        resume_after_setup = service.executar(
            "Início", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        rework = service.executar(
            "Retrabalho", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        stop_during_rework = service.executar(
            "Parada",
            op="OP-BOTOES",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            motivo_codigo="0029",
        )
        return_after_rework_stop = service.executar(
            "Retomar", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        setup_during_rework = service.executar(
            "Setup", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        return_after_rework_setup = service.executar(
            "Retornar", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        blocked_start_from_rework = service.executar(
            "Início", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        partial = service.executar(
            "Finalizado",
            op="OP-BOTOES",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=1,
            refugo=1,
            operadores_cracha=["1"],
        )
        # A parcial devolve a OP à fila: o operador reabre antes de encerrar.
        resume_after_partial = service.executar(
            "Início", op="OP-BOTOES", setor="Dobra", recurso="1303", operacao=operation
        )
        finish = service.executar(
            "Finalizado",
            op="OP-BOTOES",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=1,
            refugo=0,
            operadores_cracha=["1"],
        )

        self.assertTrue(
            all(
                result.ok
                for result in (
                    start,
                    stop,
                    resume_after_stop,
                    setup,
                    resume_after_setup,
                    rework,
                    stop_during_rework,
                    return_after_rework_stop,
                    setup_during_rework,
                    return_after_rework_setup,
                    partial,
                    resume_after_partial,
                    finish,
                )
            )
        )
        self.assertFalse(blocked_start_from_rework.ok)
        self.assertEqual(blocked_start_from_rework.code, "transicao_invalida")
        self.assertEqual(partial.code, "finalizacao_parcial")
        self.assertEqual(partial.data["status"], "Aguardando")
        self.assertEqual(partial.data["saldo_restante"], 1)
        self.assertEqual(return_after_rework_stop.data["status"], "Retrabalho")
        self.assertEqual(return_after_rework_setup.data["status"], "Retrabalho")
        events = self.db.listar_eventos_apontamento_operador(start.data["id"])
        self.assertEqual(
            [event["estado"] for event in events],
            [
                "fila",
                "producao",
                "parada",
                "producao",
                "setup",
                "producao",
                "retrabalho",
                "parada",
                "retrabalho",
                "setup",
                "retrabalho",
                "parcial",
                "producao",
                "finalizado",
            ],
        )
        self.assertEqual(
            [event["codigo_status_recurso"] for event in events if event["codigo_status_recurso"]],
            ["0029", "1005", "0040", "0029", "1005"],
        )
        self.assertEqual((finish.data["quantidade_boa"], finish.data["quantidade_refugo"]), (2, 1))
        self.assertEqual(events[-1]["operadores"], [{"cracha": "1", "nome": "Iago"}])

    def test_recurso_divergente_exige_cracha_e_fica_auditado_no_postgresql(self):
        self.db.cadastrar_operador_apontamento("1", "Iago", fonte="teste")
        operation = {
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA1",
            "recurso_nome": "GASPARINI",
            "descricao_operacao": "DOBRA",
            "produto_codigo": "P-DIVERGENTE",
            "produto_descricao": "Peça divergente",
            "quantidade": 1,
        }
        service = OperatorFlowService(self.db, "OPERADOR TESTE")
        pending = service.executar(
            "Início",
            op="OP-DIVERGENTE",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        self.assertEqual(pending.code, "confirmacao_recurso_obrigatoria")
        # Wave 6B: o portão Setup/Qualidade vem antes de produzir em Dobra.
        liberar_primeira_peca(
            self.db,
            "OPERADOR TESTE",
            op="OP-DIVERGENTE",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        accepted = service.executar(
            "Início",
            op="OP-DIVERGENTE",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            confirmar_recurso_divergente=True,
            operadores_cracha=["1"],
        )
        self.assertTrue(accepted.ok)
        event = self.db.listar_eventos_apontamento_operador(accepted.data["id"])[-1]
        self.assertTrue(event["recurso_divergente"])
        self.assertEqual(event["recurso_roteiro_codigo"], "DOBRA1")
        self.assertEqual(event["recurso_roteiro_nome"], "Gasparini")
        self.assertEqual(event["recurso_apontado"], "1303")
        self.assertEqual(event["operadores"], [{"cracha": "1", "nome": "Iago"}])

    def test_finalizacao_parcial_multioperador_e_tempo_local_do_posto(self):
        now = datetime.now().replace(microsecond=0)
        self.db.cadastrar_operador_apontamento("1", "Iago", fonte="teste")
        self.db.cadastrar_operador_apontamento("2", "Maria", fonte="teste")
        operation = {
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA3",
            "descricao_operacao": "DOBRA",
            "produto_codigo": "P-PARCIAL",
            "produto_descricao": "Peça parcial",
            "quantidade": 3,
        }
        service = OperatorFlowService(self.db, "OPERADOR TESTE")
        liberar_primeira_peca(
            self.db,
            "OPERADOR TESTE",
            op="OP-PARCIAL",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        started = service.executar(
            "Início", op="OP-PARCIAL", setor="Dobra", recurso="1303", operacao=operation
        )
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE apontamentos_operacionais SET data_inicio = %s WHERE id = %s",
                (now - timedelta(seconds=30), started.data["id"]),
            )

        cards = service.listar_cartoes("Dobra", "1303")
        self.assertEqual(len(cards["production"]), 1)
        self.assertTrue(cards["production"][0]["elapsed"].startswith("0min "))
        history = self.db.listar_historico_operador("Dobra", "1303")
        self.assertTrue(history[0]["elapsed"].startswith("0min "))

        partial = service.executar(
            "Finalizado",
            op="OP-PARCIAL",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=1,
            refugo=0,
            operadores_cracha=["1", "2"],
        )
        self.assertTrue(partial.ok)
        # A finalização parcial devolve a OP à fila com as quantidades já
        # acumuladas; ela não permanece em execução por conta própria.
        self.assertEqual((partial.data["status"], partial.data["saldo_restante"]), ("Aguardando", 2))
        partial_event = self.db.listar_eventos_apontamento_operador(started.data["id"])[-1]
        self.assertEqual(partial_event["estado"], "parcial")
        self.assertEqual(
            partial_event["operadores"],
            [{"cracha": "1", "nome": "Iago"}, {"cracha": "2", "nome": "Maria"}],
        )

        self.assertTrue(
            service.executar(
                "Início", op="OP-PARCIAL", setor="Dobra", recurso="1303", operacao=operation
            ).ok
        )
        finished = service.executar(
            "Finalizado",
            op="OP-PARCIAL",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            pecas_boas=2,
            refugo=0,
            operadores_cracha=["1"],
        )
        self.assertTrue(finished.ok)
        self.assertEqual(finished.data["status"], "Finalizado")
        self.assertEqual(finished.data["quantidade_boa"], 3)

    def test_serra_persiste_maquina_status_e_filtros_operacionais(self):
        task_id = self.db.inserir_tarefa("T-SERRA")
        self.db.inserir_op_na_tarefa(task_id, "OP-SERRA", "Perfil", "Aguardando Serra", 1)
        item = self.db.enfileirar_apontamento_operacional(
            "OP-SERRA", "Perfil", task_id, "Serra", "SFG-330", "IAGO", 1
        )

        started = self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO"
        )
        current = self.db.get_current_ops(
            setor_filter="MAQUINAS_SERRA",
            maquinas_serra=["SFG-330", "S4220", "SFHA-10"],
        )
        overview = self.db.counts_overview(maquinas_serra=["SFG-330", "S4220", "SFHA-10"])

        self.assertEqual(started["status"], "Em processo")
        self.assertEqual((current[0]["op"], current[0]["setor"]), ("OP-SERRA", "SFG-330"))
        self.assertEqual(overview["ops_em_serra"], 1)
        finished = self.db.transicionar_apontamento_operador(
            item["id"],
            "finalizado",
            "IAGO",
            quantidade_boa=1,
            quantidade_refugo=0,
            setor_destino="Aguardando Dobra",
        )
        self.assertEqual((finished["status"], finished["setor_destino"]), ("Finalizado", "Aguardando Dobra"))
        destination = self.db.get_current_ops()[0]
        self.assertEqual(
            (destination["setor"], destination["quantidade"]),
            ("Aguardando Dobra", 1),
        )

    def test_concorrencia_permita_somente_um_inicio_e_um_historico(self):
        item = self._appointment("OP-CONCURRENT")
        barrier = threading.Barrier(2)

        def start():
            barrier.wait()
            return self.db.transicionar_apontamento_operador(
                item["id"], "producao", "IAGO"
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _value: start(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        timeline = self.db.get_op_timeline("OP-CONCURRENT")
        self.assertEqual(sum(row["tipo"] == "Apontamento Operador" for row in timeline), 1)
        self.assertEqual(sum(row["tipo"] == "Movimentação" for row in timeline), 1)

    def test_concorrencia_permita_somente_uma_finalizacao(self):
        item = self._appointment("OP-FINISH")
        self.db.transicionar_apontamento_operador(item["id"], "producao", "IAGO")
        barrier = threading.Barrier(2)

        def finish(destination):
            barrier.wait()
            return self.db.transicionar_apontamento_operador(
                item["id"],
                "finalizado",
                "IAGO",
                quantidade_boa=2,
                quantidade_refugo=0,
                setor_destino=destination,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(finish, ("Almoxarifado", "Aguardando Usinagem")))
        self.assertEqual(sum(result is not None for result in results), 1)
        timeline = self.db.get_op_timeline("OP-FINISH")
        self.assertEqual(sum(row["tipo"] == "Apontamento Operador" for row in timeline), 2)
        self.assertEqual(sum(row["tipo"] == "Movimentação" for row in timeline), 2)

    def test_transicao_de_tarefa_e_historico_sao_atomicos_e_condicionais(self):
        task_id = self.db.inserir_tarefa("T-TRANSICAO")
        self.assertTrue(self.db.registrar_transicao_tarefa(
            task_id, None, "Destacando", "IAGO", "Destaque", "Início do destaque"
        ))
        self.assertFalse(self.db.registrar_transicao_tarefa(
            task_id, None, "Destacando", "IAGO", "Destaque", "Início do destaque"
        ))
        self.assertEqual(len(self.db.get_op_timeline("T-TRANSICAO")), 1)

        self.db._after_task_transition = lambda *_args: (
            _ for _ in ()
        ).throw(RuntimeError("falha forçada"))
        with self.assertRaises(RuntimeError):
            self.db.registrar_transicao_tarefa(
                task_id, "Destacando", "Finalizado", "IAGO",
                "Organização de Pallets", "Peças organizadas nos pallets",
            )
        self.assertEqual(self.db.buscar_tarefa_por_id(task_id)["status"], "Destacando")
        self.assertEqual(len(self.db.get_op_timeline("T-TRANSICAO")), 1)

    def _liberar_destaque_da_tarefa(self, codigo_tarefa):
        """Conclui no Corte a única chapa Laser da tarefa.

        O Destaque só é liberado por plano de Laser concluído (Wave 3). Sem
        essa semente a tarefa não entra na fila e qualquer ação do posto é
        recusada com ``destaque_nao_liberado``.
        """

        now = datetime.now().replace(microsecond=0)
        plano_hash = f"HASH-{codigo_tarefa}"
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_tarefas
                    (codigo_tarefa, material, espessura, ativo, sincronizado_em)
                VALUES (%s, 'A36', 6.35, TRUE, %s)
                """,
                (codigo_tarefa, now),
            )
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa,
                    sequencia_nesting, quantidade_processo, maquina_sigmanest,
                    sigmanest_repeat_id, data_programa, ativo, sincronizado_em
                ) VALUES (
                    %s, %s, 'P-DESTAQUE', 'CHAPA 3000 x 1500', 1, 1,
                    'AMADA_ENSIS', 1, %s, TRUE, %s
                )
                """,
                (plano_hash, codigo_tarefa, now.date(), now),
            )
        started = self.db.iniciar_apontamento_corte(
            plano_hash, "Laser Ensis 3015", "CORTADOR", "2026-01-01",
            data_inicio=now - timedelta(hours=2),
        )
        self.assertIsNotNone(started)
        self.assertIsNotNone(
            self.db.finalizar_apontamento_corte(
                started["id"], "CORTADOR", data_fim=now - timedelta(hours=1)
            )
        )
        return plano_hash

    def test_destaque_persiste_inicio_parada_retomada_e_fim_na_mesma_tarefa(self):
        task_id = self.db.inserir_tarefa("T-DESTAQUE-FLUXO")
        self._liberar_destaque_da_tarefa("T-DESTAQUE-FLUXO")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_status_recursos (
                    codigo, nome, grupo_codigo, grupo_nome, habilitado,
                    oculto, setup, retrabalho, sincronizado_em
                ) VALUES (
                    'T029', 'Aguardando ponte', '0004', 'PARADAS DA FABRICA',
                    TRUE, FALSE, FALSE, FALSE, CURRENT_TIMESTAMP
                )
                """
            )
        service = ProductionService(self.db, "OPERADOR DESTAQUE")

        self.assertTrue(service.registrar_destacando(task_id, "T-DESTAQUE-FLUXO").ok)
        self.assertTrue(service.registrar_parada_destaque(
            task_id,
            "T-DESTAQUE-FLUXO",
            motivo_codigo="T029",
        ).ok)
        paused_finish = service.registrar_finalizado(task_id, "T-DESTAQUE-FLUXO")
        self.assertFalse(paused_finish.ok)
        self.assertEqual(paused_finish.code, "destaque_parado")
        self.assertTrue(service.registrar_destacando(task_id, "T-DESTAQUE-FLUXO").ok)
        self.assertTrue(service.registrar_finalizado(task_id, "T-DESTAQUE-FLUXO").ok)

        task = self.db.buscar_tarefa_por_id(task_id)
        events = self.db.listar_eventos_destaque(task_id)
        self.assertEqual(task["status"], "Finalizado")
        # O escopo da tarefa é uma máquina de estados só.
        self.assertEqual(
            [event["estado"] for event in events if event["plano_hash"] is None],
            ["inicio", "parada", "retomada", "fim"],
        )
        # A conclusão da tarefa fecha, por evidência explícita, a chapa que não
        # foi destacada individualmente — sem criar um segundo fluxo.
        self.assertEqual(
            [
                (event["estado"], event["plano_hash"])
                for event in events
                if event["plano_hash"] is not None
            ],
            [("fim", "HASH-T-DESTAQUE-FLUXO")],
        )
        self.assertEqual(len(self.db.get_op_timeline("T-DESTAQUE-FLUXO")), 4)

    def test_falha_antes_do_historico_reverte_transicao(self):
        item = self._appointment("OP-ROLLBACK")
        self.db._after_appointment_transition = lambda *_args: (_ for _ in ()).throw(RuntimeError("falha forçada"))
        with self.assertRaises(RuntimeError):
            self.db.transicionar_apontamento_operador(item["id"], "producao", "IAGO")
        self.assertEqual(self.db.buscar_apontamento_operacional(item["id"])["status"], "Aguardando")
        self.assertEqual(self.db.get_op_timeline("OP-ROLLBACK"), [])

    def test_despacho_preserva_maquina_e_eh_unidade_transacional(self):
        task_id = self.db.inserir_tarefa("T-DESPACHO")
        op_id = self.db.inserir_op_na_tarefa(task_id, "OP-DESPACHO", "Peça", "Dobra", 1)
        self.db.atualizar_op(op_id, "Romi 300", 1)
        self.db.atualizar_tarefa_status(task_id, "Finalizado")
        self.assertTrue(self.db.despachar_tarefa(task_id, "IAGO"))
        self.assertEqual(self.db.buscar_tarefa_por_id(task_id)["status"], "Despachado")
        self.assertEqual(self.db.get_current_ops()[0]["setor"], "Romi 300")


def datetime_from(text):
    from datetime import datetime
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    unittest.main()
