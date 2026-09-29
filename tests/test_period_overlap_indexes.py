"""BK-06/BK-16: consultas de período e FK quente usam índice sem mudar o resultado."""

from contextlib import nullcontext
from datetime import datetime
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database

INICIO = datetime(2026, 1, 10, 10, 0)
FIM = datetime(2026, 1, 10, 12, 0)


def _h(hora, minuto=0):
    return datetime(2026, 1, 10, hora, minuto)


class _CapturedConnection:
    """Conexão falsa que só guarda o SQL gerado pelo método real."""

    def __init__(self):
        self.calls = []

    def cursor(self):
        return nullcontext(self)

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchall(self):
        return []


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class PeriodOverlapIndexTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(self.dsn)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _execute(self, statement, params=None):
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute(statement, params)

    def _captured_sql(self, method, *args, **kwargs):
        captured = _CapturedConnection()
        with patch.object(self.db, "connection", lambda: nullcontext(captured)):
            getattr(self.db, method)(*args, **kwargs)
        return captured.calls[0]

    def test_bordas_do_periodo_preservam_o_resultado(self):
        estados = [  # (rótulo, início, fim) — janela [10:00, 12:00], bordas abertas
            ("termina_no_inicio", _h(8), _h(10)),
            ("comeca_no_fim", _h(12), _h(13)),
            ("duracao_zero", _h(11), _h(11)),
            ("atravessa", _h(9), _h(13)),
            ("aberto", _h(9), None),
        ]
        for rotulo, inicio, fim in estados:
            self._execute(
                "INSERT INTO eventos_estado_recurso (recurso, tipo_setor, categoria, op, data_inicio, data_fim)"
                " VALUES ('LASER1', 'Corte', 'producao', %s, %s, %s)",
                (rotulo, inicio, fim),
            )
            self._execute(
                "INSERT INTO sessoes_recurso (recurso, tipo_setor, data_inicio, data_fim, segundos_fisicos,"
                " referencia_origem) VALUES ('LASER1', 'Corte', %s, %s, 0, %s)",
                (inicio, fim, rotulo),
            )
        apontamentos = [  # (op, entrada, início, fim) — bordas fechadas
            ("FIM_NO_INICIO", _h(7), _h(8), _h(10)),
            ("INICIO_NO_FIM", _h(11), _h(12), _h(13)),
            ("ANTES", _h(7), _h(8), _h(9, 59)),
            ("SO_ENTRADA_ABERTO", _h(11), None, None),
            ("INVERTIDO_DENTRO", _h(10), _h(11), _h(10, 30)),
            ("INVERTIDO_FORA", _h(10), _h(13), _h(11)),
            ("ENTRADA_DEPOIS", _h(12, 1), None, None),
        ]
        for op, entrada, inicio, fim in apontamentos:
            self._execute(
                "INSERT INTO apontamentos_operacionais (op, tipo_setor, maquina, status, quantidade,"
                " operador_fila, data_entrada, data_inicio, data_fim, quantidade_boa, quantidade_refugo)"
                " VALUES (%s, 'Corte', 'LASER1', %s, 10, 'teste', %s, %s, %s, 0, 0)",
                (op, "Finalizado" if fim else "Em processo", entrada, inicio, fim),
            )

        estados_no_periodo = {row["op"] for row in self.db.listar_estados_recurso_periodo(INICIO, FIM)}
        sessoes_no_periodo = {row["referencia_origem"] for row in self.db.listar_rateios_tempo_periodo(INICIO, FIM)}
        fatos_no_periodo = {row["op"] for row in self.db.listar_fatos_operacionais_periodo(INICIO, FIM)}

        self.assertEqual(estados_no_periodo, {"duracao_zero", "atravessa", "aberto"})
        self.assertEqual(sessoes_no_periodo, {"duracao_zero", "atravessa", "aberto"})
        self.assertEqual(
            fatos_no_periodo,
            {"FIM_NO_INICIO", "INICIO_NO_FIM", "SO_ENTRADA_ABERTO", "INVERTIDO_DENTRO"},
        )

    def test_consultas_de_periodo_usam_indice_gist_de_intervalo(self):
        self._execute(
            """
            INSERT INTO eventos_estado_recurso (recurso, tipo_setor, categoria, op, data_inicio, data_fim)
            SELECT 'LASER1', 'Corte', 'producao', 'OP' || k,
                   TIMESTAMP '2025-01-01' + k * INTERVAL '70 minutes',
                   TIMESTAMP '2025-01-01' + (k + 1) * INTERVAL '70 minutes'
            FROM generate_series(0, 7999) k;
            INSERT INTO sessoes_recurso (recurso, tipo_setor, data_inicio, data_fim, segundos_fisicos)
            SELECT 'LASER1', 'Corte',
                   TIMESTAMP '2025-01-01' + k * INTERVAL '70 minutes',
                   TIMESTAMP '2025-01-01' + (k + 1) * INTERVAL '70 minutes', 4200
            FROM generate_series(0, 7999) k;
            INSERT INTO apontamentos_operacionais (op, tipo_setor, maquina, status, quantidade, operador_fila,
                                                   data_entrada, data_inicio, data_fim, quantidade_boa,
                                                   quantidade_refugo)
            SELECT 'OP' || k, 'Corte', 'LASER1', 'Finalizado', 10, 'teste',
                   TIMESTAMP '2025-01-01' + k * INTERVAL '70 minutes',
                   TIMESTAMP '2025-01-01' + k * INTERVAL '70 minutes',
                   TIMESTAMP '2025-01-01' + k * INTERVAL '70 minutes' + INTERVAL '1 hour', 10, 0
            FROM generate_series(0, 7999) k;
            ANALYZE eventos_estado_recurso;
            ANALYZE sessoes_recurso;
            ANALYZE apontamentos_operacionais;
            """
        )
        casos = {
            "listar_estados_recurso_periodo": "idx_estado_recurso_intervalo",
            "listar_rateios_tempo_periodo": "idx_sessao_recurso_intervalo",
            "listar_fatos_operacionais_periodo": "idx_apontamentos_intervalo",
        }
        with psycopg.connect(self.dsn) as connection:
            # Só tira o Seq Scan do páreo: um índice que o predicado não atende
            # continua inutilizável, então o plano prova o casamento da expressão.
            connection.execute("SET enable_seqscan = off")
            for method, index in casos.items():
                with self.subTest(method=method):
                    query, params = self._captured_sql(method, INICIO, FIM)
                    plan = "\n".join(row[0] for row in connection.execute("EXPLAIN " + query, params))
                    self.assertIn(index, plan)

    def test_fk_de_estado_por_evento_tem_indice_para_o_set_null(self):
        # BK-16: é esta busca que o ON DELETE SET NULL faz ao apagar um evento.
        with psycopg.connect(self.dsn) as connection:
            connection.execute("SET enable_seqscan = off")
            plan = "\n".join(
                row[0] for row in connection.execute(
                    "EXPLAIN UPDATE eventos_estado_recurso SET evento_apontamento_id = NULL"
                    " WHERE evento_apontamento_id = %s",
                    (1,),
                )
            )
        self.assertIn("idx_estado_recurso_evento_apontamento", plan)


if __name__ == "__main__":
    unittest.main()
