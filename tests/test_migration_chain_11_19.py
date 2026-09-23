"""Cadeia de migrations 11 → 19: o caminho que o banco REAL percorrerá.

O banco REAL do Gestor está em schema 11 e o piloto exige 19. Estes testes
constroem um schema 11 de verdade, semeiam as formas de dado que foram medidas
no REAL por auditoria READ-ONLY e então executam a MESMA ``apply_migrations``
que o piloto executará — sem enfraquecer nenhuma migration para passar.

O foco é o que pode dar errado sobre dados existentes:

* migration 12 reescreve a ``CHECK`` de ``eventos_estado_recurso.categoria``;
* migration 16 faz ``DROP CONSTRAINT`` sem ``IF EXISTS`` e cria ``UNIQUE``
  parcial sobre um trio que já tem dados;
* migration 18 adiciona ``CHECK`` que toda linha antiga precisa satisfazer.

O volume completo do REAL é exercitado por
``scripts/ensaiar_migracao_11_19.py``; aqui fica a regressão barata e rápida.
"""

from datetime import datetime, timedelta
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.database import migrations as migrations_module
from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.errors import DatabaseMigrationError
from app.database.migrations import apply_migrations, validate_migration_catalog
from app.database.schema import SCHEMA_VERSION
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig
from mes.integrations.totvs.outbox import OutboxStatus


PARTIDA = 11

# Categorias efetivamente presentes no banco REAL em 01/09/2026. A migration 12
# precisa aceitá-las sem tocar em nenhuma linha.
CATEGORIAS_REAIS = ("producao", "fora_turno")

TABELAS_PRESERVADAS = (
    "usuarios",
    "tarefas",
    "historico",
    "catalogo_pcp_ops",
    "catalogo_operacoes_op",
    "apontamentos_operacionais",
    "eventos_apontamento_operador",
    "eventos_estado_recurso",
    "catalogo_sigmanest_planos_corte",
    "apontamentos_corte",
)


class MigrationCatalogTests(unittest.TestCase):
    def test_schema_version_sem_migration_falha_com_diagnostico(self):
        original = migrations_module.SCHEMA_VERSION
        migrations_module.SCHEMA_VERSION = original + 1
        try:
            with self.assertRaisesRegex(DatabaseMigrationError, "migration.*ausente"):
                validate_migration_catalog()
        finally:
            migrations_module.SCHEMA_VERSION = original


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class MigrationChain11To19Tests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "cadeia11a19_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.agora = datetime.now().replace(microsecond=0) - timedelta(days=1)
        self.connection = psycopg.connect(self.dsn, row_factory=dict_row)
        self._construir_schema_11()
        self._semear()

    def tearDown(self):
        if not self.connection.closed:
            self.connection.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    # -- construção do ponto de partida --------------------------------
    def _construir_schema_11(self):
        original = migrations_module.SCHEMA_VERSION
        migrations_module.SCHEMA_VERSION = PARTIDA
        try:
            self.versao_inicial = apply_migrations(self.connection)
        finally:
            migrations_module.SCHEMA_VERSION = original
        self.connection.commit()

    def _executar(self, query, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, params)

    def _rows(self, query, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _scalar(self, query, params=()):
        encontrado = self._rows(query, params)
        return next(iter(encontrado[0].values())) if encontrado else None

    def _semear(self):
        agora = self.agora
        self._executar(
            """
            INSERT INTO usuarios (nome, senha_hash, nivel)
            VALUES ('ensaio', 'pbkdf2_sha256$1$x$y', 'operador_destaque')
            """
        )
        self._executar(
            """
            INSERT INTO catalogo_pcp_ops (
                codigo_op, produto_codigo, produto_descricao, quantidade,
                data_emissao, local_estoque, sincronizado_em
            ) VALUES ('OPCADEIA001', 'PROD1', 'Produto', 10, %s, '01', %s)
            """,
            (agora.date(), agora),
        )
        # Duas operações no mesmo trio-chave da UNIQUE parcial da migration 16,
        # distintas apenas pelo recurso — exatamente a forma do roteiro real.
        self._executar(
            """
            INSERT INTO catalogo_operacoes_op (
                codigo_op, produto_codigo, produto_descricao, numero_operacao,
                codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                sincronizado_em
            ) VALUES
                ('OPCADEIA001', 'PROD1', 'Produto', '10', 'LASER1', 'Corte', 'Corte', 1, TRUE, %s),
                ('OPCADEIA001', 'PROD1', 'Produto', '20', 'DOBRA1', 'Dobra', 'Dobra', 2, TRUE, %s)
            """,
            (agora, agora),
        )
        self._executar(
            """
            INSERT INTO apontamentos_operacionais (
                op, peca, tipo_setor, maquina, status, quantidade,
                operador_fila, data_entrada, numero_operacao, codigo_recurso
            ) VALUES ('OPCADEIA001', 'PECA', 'Corte', 'LASER1', 'Finalizado', 5,
                      'ENSAIO', %s, '10', 'LASER1')
            """,
            (agora,),
        )
        self._executar(
            """
            INSERT INTO eventos_apontamento_operador (apontamento_id, estado, operador, data_hora)
            SELECT id, 'producao', 'ENSAIO', %s FROM apontamentos_operacionais
            """,
            (agora,),
        )
        for indice, categoria in enumerate(CATEGORIAS_REAIS):
            self._executar(
                """
                INSERT INTO eventos_estado_recurso (
                    recurso, categoria, data_inicio, data_fim, origem
                ) VALUES ('LASER1', %s, %s, %s, 'ensaio')
                """,
                (
                    categoria,
                    agora + timedelta(minutes=10 * indice),
                    agora + timedelta(minutes=10 * indice + 5),
                ),
            )
        # Semente do schema 11: a coluna só vira `maquina_sigmanest` na
        # migration 23. Usar o nome novo aqui quebraria a reconstrução
        # do ponto de partida real.
        self._executar(
            """
            INSERT INTO catalogo_sigmanest_planos_corte (
                plano_hash, codigo_tarefa, programa, sequencia_nesting,
                quantidade_processo, maquina_qlik, sincronizado_em
            ) VALUES ('HASH0001', 'TAR-1', 'PRG1', 1, 1, 'LASER', %s)
            """,
            (agora,),
        )
        self._executar(
            """
            INSERT INTO apontamentos_corte (
                plano_hash, codigo_tarefa, programa, sequencia_nesting, maquina,
                quantidade_processo, status, operador_inicio, data_inicio,
                operador_fim, data_fim
            ) VALUES ('HASH0001', 'TAR-1', 'PRG1', 1, 'LASER1', 1, 'Finalizado',
                      'ENSAIO', %s, 'ENSAIO', %s)
            """,
            (agora, agora + timedelta(minutes=30)),
        )
        self.connection.commit()

    def _contagens(self):
        return {
            tabela: self._scalar(f"SELECT COUNT(*) AS total FROM {tabela}")
            for tabela in TABELAS_PRESERVADAS
        }

    # -- testes ---------------------------------------------------------
    def test_ponto_de_partida_e_o_schema_11_do_banco_real(self):
        self.assertEqual(self.versao_inicial, PARTIDA)
        self.assertEqual(
            self._scalar("SELECT MAX(version) AS v FROM schema_migrations"), PARTIDA
        )
        # Nada que as migrations 12–19 criam pode existir antes delas.
        for tabela in ("ai_conversations", "totvs_integration_messages", "totvs_outbox"):
            self.assertIsNone(
                self._scalar("SELECT to_regclass(%s) AS r", (tabela,)), tabela
            )

    def test_cadeia_12_a_19_chega_ao_alvo_preservando_todos_os_dados(self):
        antes = self._contagens()
        versao = apply_migrations(self.connection)
        self.connection.commit()
        self.assertEqual(versao, SCHEMA_VERSION)
        self.assertEqual(
            self._scalar("SELECT MAX(version) AS v FROM schema_migrations"),
            SCHEMA_VERSION,
        )
        self.assertEqual(self._contagens(), antes)
        registradas = {
            row["version"]
            for row in self._rows("SELECT version FROM schema_migrations")
        }
        self.assertTrue(set(range(1, SCHEMA_VERSION + 1)) <= registradas)

    def test_migration_12_aceita_as_categorias_que_existem_no_real(self):
        apply_migrations(self.connection)
        self.connection.commit()
        presentes = {
            row["categoria"]
            for row in self._rows("SELECT DISTINCT categoria FROM eventos_estado_recurso")
        }
        self.assertEqual(presentes, set(CATEGORIAS_REAIS))
        # A CHECK nova continua recusando um valor inventado.
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._executar(
                """
                INSERT INTO eventos_estado_recurso (recurso, categoria, data_inicio, origem)
                VALUES ('LASER9', 'categoria_inexistente', %s, 'ensaio')
                """,
                (self.agora,),
            )
        self.connection.rollback()

    def test_migration_16_troca_a_unique_do_roteiro_sem_perder_exclusividade(self):
        # A constraint que a migration remove precisa existir no ponto de partida.
        self.assertEqual(
            self._scalar(
                """
                SELECT COUNT(*) AS total FROM pg_constraint
                WHERE conname = 'uq_catalogo_operacao_op_recurso'
                """
            ),
            1,
        )
        apply_migrations(self.connection)
        self.connection.commit()
        self.assertEqual(
            self._scalar(
                """
                SELECT COUNT(*) AS total FROM pg_constraint
                WHERE conname = 'uq_catalogo_operacao_op_recurso'
                """
            ),
            0,
        )
        # A exclusividade migrou para o índice parcial e continua valendo para
        # as linhas legadas, que têm totvs_activity_id nulo.
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self._executar(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                    sincronizado_em
                ) VALUES ('OPCADEIA001', 'PROD1', 'Produto', '10', 'LASER1',
                          'Corte', 'Corte', 1, TRUE, %s)
                """,
                (self.agora,),
            )
        self.connection.rollback()

    def test_migration_18_valida_a_check_do_marco_terminal_sobre_linhas_antigas(self):
        # Toda linha pré-existente nasce marco_terminal = FALSE e precisa ter
        # tipo_setor e ativo preenchidos, senão a CHECK falharia na validação.
        self.assertEqual(
            self._scalar(
                """
                SELECT COUNT(*) AS total FROM catalogo_operacoes_op
                WHERE tipo_setor IS NULL OR ativo IS NULL
                """
            ),
            0,
        )
        apply_migrations(self.connection)
        self.connection.commit()
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE marco_terminal IS TRUE"
            ),
            0,
        )
        # A regra industrial do marco terminal chega intacta: ele nunca pode
        # ser apontável.
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._executar(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                    marco_terminal, sincronizado_em
                ) VALUES ('OPCADEIA001', 'PROD1', 'Produto', '99', 'ALMOX4',
                          'Terminal', NULL, 9, TRUE, TRUE, %s)
                """,
                (self.agora,),
            )
        self.connection.rollback()

    def test_migration_18_falharia_se_o_alvo_tivesse_linha_incompativel(self):
        """Prova que a CHECK é real: com dado incompatível, a cadeia para.

        Este é o cenário que a auditoria READ-ONLY do REAL existe para
        descartar antes do piloto — e que hoje ela descarta (zero linhas).
        """

        self._executar(
            "ALTER TABLE catalogo_operacoes_op ALTER COLUMN tipo_setor DROP NOT NULL"
        )
        self._executar(
            """
            INSERT INTO catalogo_operacoes_op (
                codigo_op, produto_codigo, produto_descricao, numero_operacao,
                codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                sincronizado_em
            ) VALUES ('OPCADEIA001', 'PROD1', 'Produto', '30', 'INSPEC',
                      'Inspecao', NULL, 3, TRUE, %s)
            """,
            (self.agora,),
        )
        self.connection.commit()
        with self.assertRaises(DatabaseMigrationError):
            apply_migrations(self.connection)
        self.connection.rollback()
        # A cadeia parou sem deixar o schema meio migrado.
        self.assertLess(
            self._scalar("SELECT MAX(version) AS v FROM schema_migrations"),
            SCHEMA_VERSION,
        )

    def test_constraints_e_indices_ficam_validos_apos_a_promocao(self):
        apply_migrations(self.connection)
        self.connection.commit()
        # A migration 25 adiciona ``NOT VALID`` de propósito: o histórico foi
        # produzido pela regra anterior (saldo por peças boas) e não pode ser
        # reescrito, mas toda escrita nova passa a ser recusada. É a única
        # exceção autorizada; qualquer outra constraint não validada indica
        # migration interrompida no meio.
        self.assertEqual(
            self._rows(
                """
                SELECT conname FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = %s AND NOT c.convalidated
                """,
                (self.schema,),
            ),
            [{"conname": "ck_apontamentos_quantidade_atendida_planejada"}],
        )
        self.assertEqual(
            self._rows(
                """
                SELECT c.relname FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND (NOT i.indisvalid OR NOT i.indisready)
                """,
                (self.schema,),
            ),
            [],
        )

    def test_aplicacao_sobe_e_a_outbox_funciona_no_schema_promovido(self):
        apply_migrations(self.connection)
        self.connection.commit()
        self.connection.close()

        db = Database(
            self.dsn,
            auto_migrate=True,
            totvs_outbox_config=OutboundEnqueueConfig(enabled=True),
        )
        try:
            self.assertEqual(db.obter_schema_version(), SCHEMA_VERSION)
            # Dados anteriores continuam acessíveis pelas consultas canônicas.
            self.assertEqual(len(db.listar_apontamentos_por_op("OPCADEIA001")), 1)
            self.assertEqual(db.metricas_outbound_totvs()["contagem"]["PENDING"], 0)
            with db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO totvs_outbox (
                        event_type, aggregate_type, aggregate_id, production_order,
                        idempotency_key, transaction, payload_xml, status,
                        next_attempt_at, created_at, updated_at
                    ) VALUES ('production_appointment', 'execution_event', '1',
                              'OPCADEIA001', %s, 'productionappointment',
                              '<TOTVSMessage/>', 'PENDING', %s, %s, %s)
                    RETURNING id
                    """,
                    (f"cadeia-{uuid4()}", db._now(), db._now(), db._now()),
                )
                item_id = cursor.fetchone()["id"]
            reservados = db.reservar_lote_outbound_totvs(worker="cadeia")
            self.assertEqual([item["id"] for item in reservados], [item_id])
            self.assertEqual(reservados[0]["status"], OutboxStatus.SENDING.value)
        finally:
            db.close()
        # Reabre a conexão do tearDown.
        self.connection = psycopg.connect(self.dsn, row_factory=dict_row)


if __name__ == "__main__":
    unittest.main()
