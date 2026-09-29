"""Invariantes de concorrência no PostgreSQL real (BK-02, BK-03, BK-07).

Cada teste dispara duas threads contra o mesmo recurso, com conexões próprias,
liberadas juntas por uma barreira. O resultado esperado é sempre um vencedor e
um conflito controlado, nunca dois registros físicos para o mesmo recurso.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import os
import threading
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.leadership import LeaderLease
from mes.services.operator_flow import OperatorState

ALIAS = "Laser Ensis 3015"
CANONICO = "LASER1"


def _em_paralelo(*tarefas):
    barreira = threading.Barrier(len(tarefas))

    def rodar(tarefa):
        barreira.wait(timeout=10)
        return tarefa()

    with ThreadPoolExecutor(len(tarefas)) as executor:
        return [futuro.result(timeout=30) for futuro in [executor.submit(rodar, t) for t in tarefas]]


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class InvariantesDeConcorrenciaTests(unittest.TestCase):
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

    def _rateio(self, recurso, op, inicio):
        def registrar():
            try:
                return self.db.registrar_rateio_recurso(
                    recurso, inicio, inicio + timedelta(hours=1),
                    [{"op": op, "segundos_atribuidos": 3600, "estrategia": "manual"}], tipo_setor="Corte",
                )
            except ValueError as exc:
                return exc
        return registrar

    def test_rateio_por_alias_e_por_codigo_nao_se_sobrepoem(self):
        # BK-02: alias e código caíam em travas distintas e gravavam as duas
        # sessões físicas da mesma hora no mesmo recurso.
        inicio = datetime(2026, 9, 22, 9, 0)
        resultados = _em_paralelo(
            self._rateio(ALIAS, "OP-ALIAS", inicio),
            self._rateio(CANONICO, "OP-CODIGO", inicio + timedelta(minutes=30)),
        )

        erros = [r for r in resultados if isinstance(r, ValueError)]
        self.assertEqual(len(erros), 1, resultados)
        self.assertIn("sobreposta", str(erros[0]))
        sessoes = self.db.listar_rateios_tempo_periodo(
            inicio - timedelta(hours=1), inicio + timedelta(hours=3), recurso=ALIAS
        )
        self.assertEqual({s["recurso"] for s in sessoes}, {CANONICO})

    def _op(self, codigo):
        tarefa = self.db.inserir_tarefa("T-" + codigo)
        self.db.inserir_op_na_tarefa(tarefa, codigo, "Peça", "Aguardando Corte", 1)
        return tarefa

    def _inicio(self, codigo, tarefa, maquina):
        """O Início do operador visto pelo banco: fila, transição e desfazer."""

        def iniciar():
            fila = self.db.enfileirar_apontamento_operacional(
                codigo, "Peça", tarefa, "Corte", maquina, "OPERADOR", 1,
                recurso_exclusivo=True,
            )
            if fila.get("exclusive_resource_conflict"):
                return "conflito"
            linha = self.db.transicionar_apontamento_operador(
                fila["id"], OperatorState.PRODUCTION.value, "OPERADOR",
                recurso_exclusivo=True,
            )
            if linha.get("exclusive_resource_conflict"):
                self.db.descartar_inicio_nao_iniciado(fila["id"])
                return "conflito"
            return "iniciado"
        return iniciar

    def _ativos(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT op, status FROM apontamentos_operacionais"
                " WHERE status IN ('Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho')"
            )
            return cursor.fetchall()

    def test_dois_inicios_simultaneos_deixam_um_apontamento_e_um_conflito(self):
        # BK-03: a checagem de ocupação do fluxo roda antes e fora da
        # transação do INSERT; os dois Inícios passavam e a fila ficava com dois.
        for _ in range(5):
            self.tearDown()
            self.setUp()
            primeira, segunda = self._op("OP-A"), self._op("OP-B")
            resultados = _em_paralelo(
                self._inicio("OP-A", primeira, ALIAS),
                self._inicio("OP-B", segunda, CANONICO),
            )
            self.assertEqual(sorted(resultados), ["conflito", "iniciado"])
            ativos = self._ativos()
            self.assertEqual(len(ativos), 1, ativos)
            self.assertEqual(ativos[0]["status"], "Em processo")

    def test_revalidacao_no_insert_ve_o_recurso_ocupado_pelo_alias(self):
        primeira, segunda = self._op("OP-A"), self._op("OP-B")
        self.assertEqual(self._inicio("OP-A", primeira, ALIAS)(), "iniciado")

        conflito = self.db.enfileirar_apontamento_operacional(
            "OP-B", "Peça", segunda, "Corte", CANONICO, "OPERADOR", 1,
            recurso_exclusivo=True,
        )

        self.assertTrue(conflito["exclusive_resource_conflict"])
        self.assertEqual(len(self._ativos()), 1)

    def test_descarte_nao_apaga_fila_que_ja_produziu(self):
        tarefa = self._op("OP-A")
        fila = self.db.enfileirar_apontamento_operacional(
            "OP-A", "Peça", tarefa, "Corte", CANONICO, "OPERADOR", 1
        )
        self.db.transicionar_apontamento_operador(
            fila["id"], OperatorState.PRODUCTION.value, "OPERADOR"
        )

        self.assertFalse(self.db.descartar_inicio_nao_iniciado(fila["id"]))
        self.assertEqual(len(self._ativos()), 1)

    def test_um_so_lider_e_a_morte_dele_libera_a_vez(self):
        # BK-07: com dois processos, cada um subia o agendador e o bot do
        # Telegram e o mesmo relatório saía duas vezes.
        # Id aleatório: o advisory lock vale para o banco inteiro, não por schema.
        lock_id = int(uuid4().int % 2_000_000_000)
        primeiro, segundo = LeaderLease(lock_id), LeaderLease(lock_id)
        try:
            self.assertEqual(_em_paralelo(lambda: primeiro.hold(self.db), lambda: segundo.hold(self.db)).count(True), 1)
            lider, reserva = (primeiro, segundo) if primeiro._held else (segundo, primeiro)
            self.assertTrue(lider.hold(self.db))
            self.assertFalse(reserva.hold(self.db))

            # Processo líder morto: o PostgreSQL derruba a sessão e solta o lock.
            pid = lider._connection.info.backend_pid
            with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
                connection.execute("SELECT pg_terminate_backend(%s)", (pid,))

            self.assertTrue(reserva.hold(self.db))
            self.assertFalse(lider.hold(self.db))
        finally:
            primeiro.release()
            segundo.release()


if __name__ == "__main__":
    unittest.main()
