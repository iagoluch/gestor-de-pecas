"""Estado físico após o fim da OP e após o intervalo automático (PostgreSQL real).

Regras da Manufatura (Gabriel Fogaça, 24/09/2026):
- terminou a última OP/nesting e não há outra execução: o recurso entra em
  Recurso sem demanda, sem lacuna na timeline;
- fim do intervalo automático volta para o último estado, qualquer que seja
  (OP em produção, parada com motivo, sem demanda) — C09/C10;
- OP encerrada durante o intervalo não é reaberta no retorno (I03);
- apontamento feito durante o intervalo não encerra o intervalo antes da hora;
- execução encerrada após a jornada (fora da hora extra) leva a Fora de turno.
"""

from datetime import datetime, timedelta
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.resource_mapping import resolve_resource_identity
from app.database.config import load_postgres_config
from app.database.database import Database
from mes.domain import ManufacturingRules

RESOURCE = "1303"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ResourceStateNoDemandAndBreakTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))
        # Terça-feira 09:00, dentro do expediente global (08:00-17:30).
        self.t0 = datetime(2026, 9, 22, 9, 0)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _at(self, minutes):
        return self.t0 + timedelta(minutes=minutes)

    def _started_op(self, code="OP-ESTADO", minute=0):
        task_id = self.db.inserir_tarefa("T-" + code)
        self.db.inserir_op_na_tarefa(task_id, code, "Peça", "Aguardando Dobra", 2)
        item = self.db.enfileirar_apontamento_operacional(
            code, "Peça", task_id, "Dobra", RESOURCE, "IAGO", 2
        )
        self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO", data_hora=self._at(minute)
        )
        return item

    def _finish(self, item, minute):
        return self.db.transicionar_apontamento_operador(
            item["id"], "finalizado", "IAGO", quantidade_boa=2, data_hora=self._at(minute)
        )

    def _break(self, start, end, resource=RESOURCE):
        # Mesmos parâmetros de iniciar_intervalo_automatico.
        self.db.transicionar_estado_recurso(
            resource, "parada", data_hora=self._at(start), operador="SISTEMA",
            motivo="Intervalo automático — Almoço", planejado=True, automatico=True,
            tipo_interrupcao="intervalo_programado",
            origem="intervalo_programado_inicio",
            referencia_origem=self._at(start).isoformat(),
        )
        return self.db.finalizar_intervalo_automatico(self._at(end), "Almoço")

    def _timeline(self, resource=RESOURCE):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM eventos_estado_recurso
                WHERE UPPER(recurso) = UPPER(%s) ORDER BY data_inicio, id
                """,
                (resolve_resource_identity(resource),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def _assert_no_demand(self, state):
        self.assertTrue(ManufacturingRules.state_is_no_demand(
            category=state["categoria"],
            interruption_type=state.get("tipo_interrupcao"),
            operation=state.get("op"),
        ))
        self.assertEqual(state["tipo_interrupcao"], "recurso_sem_demanda")

    def _assert_continuous(self, timeline):
        for before, after in zip(timeline, timeline[1:]):
            self.assertEqual(before["data_fim"], after["data_inicio"])
        self.assertIsNone(timeline[-1]["data_fim"])

    def test_fim_da_ultima_op_entra_em_sem_demanda_sem_lacuna(self):
        item = self._started_op()
        self._finish(item, 60)

        timeline = self._timeline()
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "fila"])
        self._assert_no_demand(timeline[-1])
        self.assertEqual(timeline[-1]["data_inicio"], self._at(60))
        self._assert_continuous(timeline)

    def test_fim_de_uma_op_com_outra_ativa_continua_em_producao(self):
        first = self._started_op("OP-A", minute=0)
        self._started_op("OP-B", minute=10)
        self._finish(first, 60)

        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "producao")
        self.assertIsNone(current["data_fim"])

    def test_c09_intervalo_durante_producao_volta_para_a_mesma_op(self):
        item = self._started_op()
        resumed = self._break(60, 120)

        self.assertEqual(len(resumed), 1)
        timeline = self._timeline()
        self.assertEqual(
            [row["categoria"] for row in timeline], ["producao", "parada", "producao"]
        )
        self.assertEqual(timeline[-1]["op"], timeline[0]["op"])
        self.assertEqual(timeline[-1]["apontamento_id"], item["id"])
        self.assertEqual(timeline[-1]["data_inicio"], self._at(120))
        self._assert_continuous(timeline)

    def test_intervalo_durante_parada_volta_para_a_mesma_parada(self):
        item = self._started_op()
        self.db.transicionar_apontamento_operador(
            item["id"], "parada", "IAGO", motivo="Aguardando qualidade", data_hora=self._at(30)
        )
        self._break(60, 120)

        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "parada")
        self.assertEqual(current["motivo"], "Aguardando qualidade")
        self.assertFalse(current["automatico"])
        self.assertEqual(current["data_inicio"], self._at(120))

    def test_c10_intervalo_durante_sem_demanda_volta_para_sem_demanda(self):
        item = self._started_op()
        self._finish(item, 30)
        self._break(60, 120)

        timeline = self._timeline()
        self.assertEqual(
            [row["categoria"] for row in timeline], ["producao", "fila", "parada", "fila"]
        )
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

    def test_i03_op_encerrada_durante_o_intervalo_nao_e_reaberta(self):
        item = self._started_op()
        self.db.transicionar_estado_recurso(
            RESOURCE, "parada", data_hora=self._at(60), operador="SISTEMA",
            motivo="Intervalo automático — Almoço", planejado=True, automatico=True,
            tipo_interrupcao="intervalo_programado", origem="intervalo_programado_inicio",
        )
        self._finish(item, 90)

        during = self._timeline()[-1]
        self.assertEqual(during["tipo_interrupcao"], "intervalo_programado")
        self.assertIsNone(during["data_fim"], "o intervalo não pode ser encurtado")

        self.db.finalizar_intervalo_automatico(self._at(120), "Almoço")
        timeline = self._timeline()
        self.assertEqual(
            [row["categoria"] for row in timeline], ["producao", "parada", "fila"]
        )
        self._assert_no_demand(timeline[-1])
        self.assertIsNone(timeline[-1]["op"])
        self._assert_continuous(timeline)

    def test_apontamento_durante_o_intervalo_nao_encerra_o_intervalo(self):
        item = self._started_op()
        self.db.transicionar_estado_recurso(
            RESOURCE, "parada", data_hora=self._at(60), operador="SISTEMA",
            motivo="Intervalo automático — Almoço", planejado=True, automatico=True,
            tipo_interrupcao="intervalo_programado", origem="intervalo_programado_inicio",
        )
        self.db.transicionar_apontamento_operador(
            item["id"], "parada", "IAGO", motivo="Aguardando qualidade", data_hora=self._at(90)
        )

        during = self._timeline()[-1]
        self.assertEqual(during["tipo_interrupcao"], "intervalo_programado")
        self.assertIsNone(during["data_fim"], "o intervalo não pode ser encurtado")

        self.db.finalizar_intervalo_automatico(self._at(120), "Almoço")
        timeline = self._timeline()
        self.assertEqual(
            [row["categoria"] for row in timeline], ["producao", "parada", "parada"]
        )
        self.assertEqual(timeline[-1]["motivo"], "Aguardando qualidade")
        self.assertEqual(timeline[-1]["apontamento_id"], item["id"])
        self.assertEqual(timeline[-1]["data_inicio"], self._at(120))
        self._assert_continuous(timeline)

    def test_op_encerrada_apos_a_jornada_entra_em_fora_de_turno(self):
        # 22:00-23:00: depois do expediente e da hora extra H2 (até 21:30).
        item = self._started_op(minute=13 * 60)
        self._finish(item, 14 * 60)

        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "fora_turno")
        self.assertEqual(current["tipo_interrupcao"], "fim_turno")
        self.assertIsNone(current["data_fim"])

        # O retorno do turno seguinte converte em sem demanda.
        self.db.finalizar_fora_turno_automatico(datetime(2026, 9, 23, 8, 0))
        returned = self._timeline()[-1]
        self.assertEqual(returned["categoria"], "fila")
        self.assertEqual(returned["tipo_interrupcao"], "retorno_turno_sem_demanda")
        self.assertIsNone(returned["op"])

    def test_op_encerrada_na_hora_extra_planejada_entra_em_sem_demanda(self):
        # 18:00-19:00: dentro da hora extra H2 (17:30-21:30).
        item = self._started_op(minute=9 * 60)
        self._finish(item, 10 * 60)

        self._assert_no_demand(self._timeline()[-1])

    def test_fim_do_nesting_do_corte_entra_em_sem_demanda(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_tarefas
                    (codigo_tarefa, material, espessura, ativo, sincronizado_em)
                VALUES ('T-CORTE-SD', 'A36', 6.35, TRUE, %s)
                """,
                (self.t0,),
            )
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa,
                    sequencia_nesting, quantidade_processo, maquina_sigmanest,
                    sigmanest_repeat_id, data_programa, ativo, sincronizado_em
                ) VALUES (
                    'HASH-CORTE-SD', 'T-CORTE-SD', 'P-SD', 'CHAPA', 1, 1,
                    'AMADA_ENSIS', 1, %s, TRUE, %s
                )
                """,
                (self.t0.date(), self.t0),
            )
        started = self.db.iniciar_apontamento_corte(
            "HASH-CORTE-SD", "Laser Ensis 3015", "CORTADOR", "2026-01-01",
            data_inicio=self._at(0),
        )
        self.db.finalizar_apontamento_corte(started["id"], "CORTADOR", data_fim=self._at(30))

        timeline = self._timeline(started["maquina"])
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "fila"])
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)


if __name__ == "__main__":
    unittest.main()
