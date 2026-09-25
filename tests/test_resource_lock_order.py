"""Ordem de locks do estado físico do recurso (PostgreSQL real).

Ordem canônica: advisory lock do recurso -> linha aberta em
``eventos_estado_recurso``. As rotinas de lote do scheduler (fim do intervalo,
retorno do turno) liam as linhas com ``FOR UPDATE`` antes do advisory lock e
entravam em deadlock com o apontamento do operador no mesmo recurso — o
operador recebia "conexão perdida" exatamente no horário de retomada.
"""

from datetime import datetime
import os
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database


RESOURCE = "SOLDA-LOCK-ORDER-1"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ResourceLockOrderTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(self.dsn)
        # Os recursos daqui são fictícios: testam travas e restauração, não a
        # regra de postos apontáveis — liga a chave de dev que os inclui.
        dev_switch = patch("app.core.operator_sectors.INCLUIR_RECURSOS_SO_SINCRONIZADOS", True)
        dev_switch.start()
        self.addCleanup(dev_switch.stop)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _race_with_operator_path(self, scheduler_call):
        """Operador segura o advisory lock; o scheduler roda; o operador pede a linha."""

        result = {}
        with psycopg.connect(self.dsn) as operator:
            with operator.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(UPPER(%s)))", (RESOURCE,))

                def run_scheduler():
                    try:
                        result["scheduler"] = scheduler_call()
                    except Exception as exc:  # registrado para a asserção abaixo
                        result["scheduler_error"] = exc

                worker = threading.Thread(target=run_scheduler)
                worker.start()
                time.sleep(1.0)
                try:
                    cursor.execute(
                        """
                        SELECT id FROM eventos_estado_recurso
                        WHERE UPPER(recurso) = UPPER(%s) AND data_fim IS NULL
                        FOR UPDATE
                        """,
                        (RESOURCE,),
                    )
                    operator.commit()
                    result["operator"] = "ok"
                except psycopg.errors.DeadlockDetected as exc:
                    operator.rollback()
                    result["operator_error"] = exc
            worker.join(20)
            self.assertFalse(worker.is_alive(), "scheduler não terminou")
        return result

    def test_fim_do_intervalo_nao_entra_em_deadlock_com_o_operador(self):
        self.db.transicionar_estado_recurso(
            RESOURCE, "producao", data_hora=datetime(2026, 9, 23, 11, 0)
        )
        self.db.transicionar_estado_recurso(
            RESOURCE, "parada", data_hora=datetime(2026, 9, 23, 12, 0),
            planejado=True, automatico=True, tipo_interrupcao="intervalo_programado",
            origem="intervalo_programado_inicio",
        )

        result = self._race_with_operator_path(
            lambda: self.db.finalizar_intervalo_automatico(datetime(2026, 9, 23, 13, 0), "Almoço")
        )

        self.assertNotIn("operator_error", result)
        self.assertNotIn("scheduler_error", result)
        self.assertEqual(result["operator"], "ok")
        self.assertEqual(len(result["scheduler"]), 1)
        self.assertEqual(result["scheduler"][0]["categoria"], "producao")
        self.assertEqual(result["scheduler"][0]["data_inicio"], datetime(2026, 9, 23, 13, 0))

    def test_retorno_do_turno_nao_entra_em_deadlock_com_o_operador(self):
        self.db.transicionar_estado_recurso(
            RESOURCE, "fora_turno", data_hora=datetime(2026, 9, 22, 17, 48),
            planejado=True, automatico=True, tipo_interrupcao="fim_turno",
            origem="fim_turno_automatico_ocioso",
        )

        result = self._race_with_operator_path(
            lambda: self.db.finalizar_fora_turno_automatico(datetime(2026, 9, 23, 8, 0))
        )

        self.assertNotIn("operator_error", result)
        self.assertNotIn("scheduler_error", result)
        self.assertEqual(result["operator"], "ok")
        self.assertEqual([row["categoria"] for row in result["scheduler"]], ["fila"])

    def test_fim_da_pausa_restaura_snapshot_de_producao_parada_e_sem_demanda(self):
        casos = (
            {
                "recurso": "RESTAURA-PRODUCAO",
                "categoria": "producao",
                "op": "OP-PAUSA-1",
                "numero_operacao": "20",
                "motivo": None,
            },
            {
                "recurso": "RESTAURA-PARADA",
                "categoria": "parada",
                "op": "OP-PAUSA-2",
                "motivo": "Aguardando liberação da Qualidade",
            },
            {
                "recurso": "RESTAURA-SEM-DEMANDA",
                "categoria": "fila",
                "op": None,
                "motivo": "Recurso sem demanda",
                "automatico": True,
                "tipo_interrupcao": "retorno_turno_sem_demanda",
            },
        )
        for case in casos:
            kwargs = dict(case)
            resource = kwargs.pop("recurso")
            category = kwargs.pop("categoria")
            self.db.transicionar_estado_recurso(
                resource, category, tipo_setor="Dobra",
                data_hora=datetime(2026, 9, 23, 11, 0), **kwargs,
            )
            self.db.transicionar_estado_recurso(
                resource, "parada", tipo_setor="Dobra",
                data_hora=datetime(2026, 9, 23, 12, 10),
                motivo="Intervalo automático — Almoço", planejado=True,
                automatico=True, tipo_interrupcao="intervalo_programado",
                origem="intervalo_programado_inicio",
            )

        resumed = self.db.finalizar_intervalo_automatico(
            datetime(2026, 9, 23, 12, 52), "Almoço", tipo_setor="Dobra"
        )
        by_resource = {row["recurso"]: row for row in resumed}

        self.assertEqual(by_resource["RESTAURA-PRODUCAO"]["categoria"], "producao")
        self.assertEqual(by_resource["RESTAURA-PRODUCAO"]["op"], "OP-PAUSA-1")
        self.assertEqual(by_resource["RESTAURA-PARADA"]["categoria"], "parada")
        self.assertEqual(
            by_resource["RESTAURA-PARADA"]["motivo"],
            "Aguardando liberação da Qualidade",
        )
        self.assertEqual(by_resource["RESTAURA-SEM-DEMANDA"]["categoria"], "fila")
        self.assertIsNone(by_resource["RESTAURA-SEM-DEMANDA"]["op"])

    def test_pausa_automatica_inclui_recurso_habilitado_nunca_usado(self):
        # Cadastro anterior à pausa: a publicação carimba ``sincronizado_em`` com
        # o relógio do Database, e a pausa ignora recurso cadastrado depois dela.
        with patch.object(self.db, "_now", lambda: datetime(2026, 9, 24, 8, 0)):
            self.db.publicar_recursos_pcfactory([{
                "codigo": "NOVO-SEM-HISTORICO",
                "nome": "Novo sem histórico",
                "tipo_setor": "Dobra",
                "habilitado": True,
            }])

        changed = self.db.iniciar_intervalo_automatico(
            datetime(2026, 9, 24, 14, 0), "Almoço", tipo_setor="Dobra"
        )

        state = next(row for row in changed if row["recurso"] == "NOVO-SEM-HISTORICO")
        self.assertEqual(state["categoria"], "parada")
        self.assertTrue(state["automatico"])
        self.assertEqual(state["tipo_interrupcao"], "intervalo_programado")
