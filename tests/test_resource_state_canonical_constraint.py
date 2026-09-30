"""Estado físico gravado só pelo código canônico do recurso (migration 51).

O Laser aparecia duas vezes nas telas porque o histórico tinha linhas com o
nome do posto ("Laser Ensis 3015") ao lado do código (LASER1). O banco agora
recusa nome de posto/alias como identidade do estado.
"""

import os
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

from app.core.resource_mapping import (
    OFFICIAL_RESOURCE_ALIASES,
    RESOURCE_DISPLAY_NAMES,
    resolve_resource_identity,
)
from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.migrations import (
    MIGRATIONS,
    RESOURCE_STATE_CANONICAL_CODE_STATEMENTS,
    RESOURCE_STATE_FORBIDDEN_IDENTITIES,
    RESOURCE_STATE_LEGACY_TO_CANONICAL,
)


class ForbiddenIdentitiesInSyncTests(unittest.TestCase):
    def test_lista_da_trava_acompanha_o_mapa_de_recursos(self):
        # Nome novo no mapa sem migration nova reabriria a duplicação.
        names = set(RESOURCE_DISPLAY_NAMES.values()) | set(OFFICIAL_RESOURCE_ALIASES)
        expected = {name.lower() for name in names if resolve_resource_identity(name) != name}
        self.assertEqual(set(RESOURCE_STATE_FORBIDDEN_IDENTITIES), expected)

    def test_migration_53_converte_cada_nome_travado_no_codigo_atual(self):
        self.assertEqual(set(RESOURCE_STATE_LEGACY_TO_CANONICAL), set(RESOURCE_STATE_FORBIDDEN_IDENTITIES))
        for legacy, code in RESOURCE_STATE_LEGACY_TO_CANONICAL.items():
            self.assertEqual(resolve_resource_identity(legacy), code, legacy)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ResourceStateCanonicalConstraintTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _insert_raw(self, resource):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO eventos_estado_recurso (recurso, categoria, origem, data_inicio)"
                " VALUES (%s, 'parada', 'teste', NOW())",
                (resource,),
            )

    def test_banco_recusa_nome_do_posto_como_recurso(self):
        for name in ("Laser Ensis 3015", "LASER", " laser ensis 3015 "):
            with self.subTest(name=name), self.assertRaises(errors.CheckViolation):
                self._insert_raw(name)

    def test_banco_aceita_codigo_canonico_e_posto_sem_codigo(self):
        self._insert_raw("LASER1")
        self._insert_raw("Robô 1")

    def test_estado_aberto_conta_so_ate_agora(self):
        # Filtro "hoje" termina 23:59:59; o estado aberto não pode somar o futuro.
        agora = datetime.now()
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO eventos_estado_recurso (recurso, categoria, origem, data_inicio)"
                " VALUES ('LASER1', 'fila', 'teste', %s)",
                (agora - timedelta(hours=1),),
            )
        rows = self.db.listar_estados_recurso_periodo(agora - timedelta(hours=2), agora + timedelta(hours=10))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["segundos_periodo"], 3600, delta=120)

    def test_gravador_converte_nome_do_posto_no_codigo(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            self.db._transicionar_estado_recurso_tx(cursor, "Laser Ensis 3015", "parada")
            cursor.execute("SELECT recurso FROM eventos_estado_recurso")
            self.assertEqual([row["recurso"] for row in cursor.fetchall()], ["LASER1"])

    def test_migration_53_converte_historico_legado_e_valida_a_trava(self):
        # Reproduz o REAL de 30/09: 1303 e Laser Ensis 3015 abertos desde agosto,
        # e o código canônico já com estado aberto (cópia na VM).
        agosto, hoje = datetime(2026, 8, 18, 17, 30), datetime(2026, 9, 30, 8, 0)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("ALTER TABLE eventos_estado_recurso DROP CONSTRAINT ck_eventos_estado_recurso_codigo_canonico")
            cursor.executemany(
                "INSERT INTO eventos_estado_recurso (recurso, categoria, origem, data_inicio, data_fim)"
                " VALUES (%s, %s, 'teste', %s, %s)",
                [
                    ("1303", "fora_turno", agosto, None),
                    ("Laser Ensis 3015", "producao", agosto, agosto + timedelta(seconds=5)),
                    ("Laser Ensis 3015", "producao", agosto + timedelta(days=2), None),
                    ("LASER1", "fila", hoje, None),
                ],
            )
            for statement in RESOURCE_STATE_CANONICAL_CODE_STATEMENTS + MIGRATIONS[53][1]:
                cursor.execute(statement)
            cursor.execute(
                "SELECT recurso, data_inicio, data_fim FROM eventos_estado_recurso ORDER BY recurso, data_inicio"
            )
            rows = [(r["recurso"], r["data_inicio"], r["data_fim"]) for r in cursor.fetchall()]
            cursor.execute(
                "SELECT convalidated FROM pg_constraint WHERE conname = 'ck_eventos_estado_recurso_codigo_canonico'"
                " AND conrelid = 'eventos_estado_recurso'::regclass"
            )
            validated = cursor.fetchone()["convalidated"]
        self.assertEqual(rows, [
            ("DOBRA3", agosto, agosto),
            ("LASER1", agosto, agosto + timedelta(seconds=5)),
            ("LASER1", agosto + timedelta(days=2), agosto + timedelta(days=2)),
            ("LASER1", hoje, None),
        ])
        self.assertTrue(validated)
