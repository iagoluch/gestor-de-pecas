"""Estado físico após o fim da OP e após o intervalo automático (PostgreSQL real).

Regras da Manufatura (Gabriel Fogaça, 24/09/2026):
- terminou a última OP/nesting e não há outra execução: o recurso entra em
  Recurso sem demanda, sem lacuna na timeline;
- fim do intervalo automático volta para o último estado, qualquer que seja
  (OP em produção, parada com motivo, sem demanda) — C09/C10;
- OP encerrada durante o intervalo não é reaberta no retorno (I03);
- OP apontada durante o intervalo sobe para produção; encerrada ainda na
  pausa, o recurso volta para a pausa; aberta até o fim, continua como está;
- parada apontada durante o intervalo não encerra o intervalo antes da hora;
- execução encerrada após a jornada (fora da hora extra) leva a Fora de turno;
- ciclo H1/expediente/H2: fora de turno nos limites da jornada, sem demanda
  entre a última OP e o próximo limite;
- registrar quantidade não é transição de estado e não tira o recurso da pausa;
- nesting do Corte em execução no início do almoço segue em produção (decisão
  do usuário, 25/09/2026);
- alterar H1/H2 não reescreve a linha do tempo já gravada.

Os cenários pedidos na validação de 25/09/2026 conferem também as bases do
OEE (``_oee_bases``), pelo mesmo caminho do ``ManagementService``: estados
persistidos → consolidação física → parada planejada fora → fórmula.
"""

from datetime import datetime, time, timedelta
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.resource_mapping import resolve_resource_identity
from app.database.config import load_postgres_config
from app.database.database import Database
from mes.analytics.oee import calculate_oee, oee_seconds_by_category
from mes.analytics.resource_state import summarize_physical_states
from mes.domain import EventCategory, ManufacturingRules, StopClassification

RESOURCE = "1303"
# Almoço semeado pela migration 23 (12:10-12:52), em minutos a partir de t0 = 09:00.
LUNCH_START = 190
LUNCH_END = 232


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
        # O enfileiramento usa o relógio real; alinha ao t0 fixo do teste para
        # não parecer um evento posterior aos limites de turno simulados.
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE eventos_apontamento_operador SET data_hora = %s"
                " WHERE apontamento_id = %s AND estado = 'fila'",
                (self._at(minute), item["id"]),
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

    def _lunch_start(self, resource=RESOURCE, sector="Dobra"):
        # Mesmos parâmetros de iniciar_intervalo_automatico, na janela configurada.
        self.db.transicionar_estado_recurso(
            resource, "parada", tipo_setor=sector, data_hora=self._at(LUNCH_START),
            operador="SISTEMA", motivo="Intervalo automático — Almoço",
            planejado=True, automatico=True, tipo_interrupcao="intervalo_programado",
            origem="intervalo_programado_inicio",
            referencia_origem=self._at(LUNCH_START).isoformat(),
        )

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

    def _oee_bases(self, start, end, resource=RESOURCE):
        """Totais físicos e bases da fórmula corporativa no período [start, end]."""

        physical = summarize_physical_states(
            self._timeline(resource), inicio=self._at(start), fim=self._at(end)
        )
        stops = physical["totals_by_stop_classification"].get(EventCategory.DOWNTIME, {})
        planned = stops.get(StopClassification.PLANNED, 0.0)
        calculation = calculate_oee(
            seconds_by_category=oee_seconds_by_category(
                physical["totals"], planned_downtime_seconds=planned
            ),
            good_quantity=0, scrap_quantity=0, rework_quantity=0, standard_run_seconds=0,
        )
        return physical["totals"], stops, calculation

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

    def _program_ops(self, *operations):
        """Publica no catálogo TOTVS operações (op, numero, recurso) ainda não apontadas."""

        self.db.publicar_catalogo_pcp([
            {"codigo_op": code, "produto_codigo": "PROD-" + code, "produto_descricao": "Peça",
             "quantidade": 2, "unidade": "UN", "data_emissao": "2026-09-01"}
            for code in dict.fromkeys(code for code, _, _ in operations)
        ])
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, ordem, fonte,
                    ativo, sincronizado_em
                ) VALUES (%s, 'PROD-' || %s, 'Peça', %s, %s, 'DOBRAR', 'Dobra', 1,
                          'teste', TRUE, %s)
                """,
                [(code, code, number, resource, self.t0) for code, number, resource in operations],
            )

    def test_fim_da_ultima_op_com_op_programada_no_recurso_fica_em_fila_com_a_op(self):
        # OP-ESTADO/10 é a que será apontada; OP-LASER é de outro recurso.
        self._program_ops(("OP-ESTADO", "10", RESOURCE), ("OP-PROG", "20", RESOURCE),
                          ("OP-LASER", "10", "LASER"))
        item = self._started_op()
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE apontamentos_operacionais SET numero_operacao = '10' WHERE id = %s",
                (item["id"],),
            )
        self._finish(item, 60)

        timeline = self._timeline()
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "fila"])
        current = timeline[-1]
        self.assertEqual((current["op"], current["numero_operacao"]), ("OP-PROG", "20"))
        self.assertEqual(current["tipo_interrupcao"], "op_programada")
        self.assertFalse(ManufacturingRules.state_is_no_demand(
            category=current["categoria"], operation=current["op"]
        ))
        self._assert_continuous(timeline)
        # Fila com OP é espera (QUEUE): fora das duas bases, como sem demanda.
        totals, _, calc = self._oee_bases(0, 120)
        self.assertEqual(totals[EventCategory.QUEUE], 3600)
        self.assertEqual(calc.time_bases["available_seconds"], 3600)

    def test_op_apontada_nao_e_programada_e_o_recurso_fica_sem_demanda(self):
        self._program_ops(("OP-ESTADO", "10", RESOURCE))
        item = self._started_op()
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE apontamentos_operacionais SET numero_operacao = '10' WHERE id = %s",
                (item["id"],),
            )
        self._finish(item, 60)

        self._assert_no_demand(self._timeline()[-1])

    def test_op_programada_durante_a_pausa_sai_da_pausa_em_fila_com_a_op(self):
        item = self._started_op()
        self._finish(item, 30)
        self._program_ops(("OP-PROG", "20", RESOURCE))
        self._break(60, 120)

        current = self._timeline()[-1]
        self.assertEqual((current["categoria"], current["op"]), ("fila", "OP-PROG"))
        self.assertEqual(current["tipo_interrupcao"], "op_programada")
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

    def test_parada_apontada_no_intervalo_nao_encerra_o_intervalo(self):
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

        # Só a pausa sai da base; a parada que persiste depois dela penaliza.
        self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO", data_hora=self._at(140)
        )
        totals, stops, calc = self._oee_bases(0, 150)
        self.assertEqual(totals[EventCategory.PRODUCTION], 4200)  # 0-60 + 140-150
        self.assertEqual(totals[EventCategory.DOWNTIME], 4800)    # 60-140
        self.assertEqual(stops[StopClassification.PLANNED], 3600)    # pausa 60-120
        self.assertEqual(stops[StopClassification.UNPLANNED], 1200)  # qualidade 120-140
        self.assertEqual(calc.time_bases["available_seconds"], 5400)
        self.assertEqual(calc.time_bases["worked_seconds"], 4200)
        self.assertAlmostEqual(calc.availability.value, 4200 / 5400 * 100)

    def test_op_apontada_no_intervalo_sobe_e_encerrada_nele_volta_ao_intervalo(self):
        before = self._started_op("OP-ANTES", minute=150)
        self._finish(before, 180)
        self._lunch_start()
        during = self._started_op("OP-PAUSA", minute=200)
        self.assertEqual(self._timeline()[-1]["categoria"], "producao")

        self._finish(during, 220)
        back = self._timeline()[-1]
        self.assertEqual(back["tipo_interrupcao"], "intervalo_programado")
        self.assertTrue(back["planejado"])
        self.assertEqual(back["data_inicio"], self._at(220))

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        timeline = self._timeline()
        self.assertEqual(
            [row["categoria"] for row in timeline],
            ["producao", "fila", "parada", "producao", "parada", "fila"],
        )
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

        # Almoço 190-232: só os trechos efetivamente pausados saem da base.
        totals, stops, calc = self._oee_bases(LUNCH_START, LUNCH_END)
        self.assertEqual(totals[EventCategory.PRODUCTION], 1200)  # 200-220
        self.assertEqual(stops[StopClassification.PLANNED], 1320)  # 190-200 + 220-232
        self.assertEqual(calc.time_bases["available_seconds"], 1200)
        self.assertEqual(calc.time_bases["worked_seconds"], 1200)
        self.assertEqual(calc.availability.value, 100.0)

    def test_quantidade_registrada_na_pausa_nao_inicia_execucao(self):
        item = self._started_op(minute=150)
        self._finish(item, 180)
        self._lunch_start()
        before = self._timeline()

        # Registro tardio da produção da manhã: evento de quantidade, não de estado.
        self.db.registrar_evento_quantidade(
            "boa", 3, "OP-ESTADO", recurso=RESOURCE, tipo_setor="Dobra",
            data_hora=self._at(200),
        )
        # Finalizado -> produção não é transição válida: apontar de novo não
        # reabre a execução nem encerra a pausa.
        self.assertIsNone(self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO", data_hora=self._at(205)
        ))

        after = self._timeline()
        self.assertEqual(after, before)
        self.assertEqual(after[-1]["tipo_interrupcao"], "intervalo_programado")
        self.assertEqual(after[-1]["data_inicio"], self._at(LUNCH_START))
        self.assertIsNone(after[-1]["data_fim"])

    def test_fim_da_ultima_op_com_outra_op_aberta_no_recurso_nao_e_sem_demanda(self):
        first = self._started_op("OP-A", minute=0)
        second = self._started_op("OP-B", minute=10)
        self.db.transicionar_apontamento_operador(
            second["id"], "parada", "IAGO", motivo="Aguardando material",
            data_hora=self._at(20),
        )
        self._finish(first, 60)

        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "parada")
        self.assertEqual(current["op"], "OP-B")
        self.assertIsNone(current["data_fim"])
        self.assertNotEqual(current["tipo_interrupcao"], "recurso_sem_demanda")

    def test_op_apontada_no_intervalo_e_aberta_ate_o_fim_continua_como_esta(self):
        self._lunch_start()
        item = self._started_op("OP-PAUSA", minute=200)

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "producao")
        self.assertEqual(current["apontamento_id"], item["id"])
        self.assertEqual(current["data_inicio"], self._at(200))
        self.assertIsNone(current["data_fim"])

    def test_op_da_pausa_encerrada_com_op_anterior_aberta_volta_ao_intervalo(self):
        before = self._started_op("OP-ANTES", minute=0)
        self._lunch_start()
        during = self._started_op("OP-PAUSA", minute=200)
        self._finish(during, 220)
        self.assertEqual(self._timeline()[-1]["tipo_interrupcao"], "intervalo_programado")

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        current = self._timeline()[-1]
        self.assertEqual(current["categoria"], "producao")
        self.assertEqual(current["apontamento_id"], before["id"])

    def test_ciclo_h1_expediente_h2(self):
        # Fim do expediente (17:30) com OP aberta -> fora de turno.
        item = self._started_op(minute=420)
        self.db.interromper_apontamento_fim_turno(item["id"], data_hora=self._at(510))
        self.assertEqual(self._timeline()[-1]["categoria"], "fora_turno")

        # H2: operador aponta a OP de novo; sem OP, sem demanda até o fim da H2.
        self.db.transicionar_apontamento_operador(
            item["id"], "producao", "IAGO", data_hora=self._at(540)
        )
        self.assertEqual(self._timeline()[-1]["categoria"], "producao")
        self._finish(item, 600)
        self._assert_no_demand(self._timeline()[-1])
        self.db.interromper_recursos_ociosos_fim_turno(self._at(750))
        self.assertEqual(self._timeline()[-1]["categoria"], "fora_turno")

        # H1 do dia seguinte (06:30-07:00): OP finalizada -> sem demanda, que
        # atravessa o início do expediente (08:00) sem virar outro estado.
        early = self._started_op("OP-H1", minute=1290)
        self._finish(early, 1320)
        self._assert_no_demand(self._timeline()[-1])
        self.db.finalizar_fora_turno_automatico(self._at(1380))
        self._assert_no_demand(self._timeline()[-1])
        self._assert_continuous(self._timeline())

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

    def _cut_plan(self):
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

    def test_fim_do_nesting_do_corte_entra_em_sem_demanda(self):
        self._cut_plan()
        started = self.db.iniciar_apontamento_corte(
            "HASH-CORTE-SD", "Laser Ensis 3015", "CORTADOR", "2026-01-01",
            data_inicio=self._at(0),
        )
        self.db.finalizar_apontamento_corte(started["id"], "CORTADOR", data_fim=self._at(30))

        timeline = self._timeline(started["maquina"])
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "fila"])
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

    def test_nesting_iniciado_e_encerrado_no_intervalo_volta_ao_intervalo(self):
        self._cut_plan()
        machine = "Laser Ensis 3015"
        self._lunch_start(machine, sector="Corte")
        during = self.db.iniciar_apontamento_corte(
            "HASH-CORTE-SD", "Laser Ensis 3015", "CORTADOR", "2026-01-01",
            data_inicio=self._at(200),
        )
        self.assertEqual(self._timeline(machine)[-1]["categoria"], "producao")

        self.db.finalizar_apontamento_corte(during["id"], "CORTADOR", data_fim=self._at(220))
        self.assertEqual(
            self._timeline(machine)[-1]["tipo_interrupcao"], "intervalo_programado"
        )

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        timeline = self._timeline(machine)
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

    def _publish_cut_resource(self, code):
        # Cadastro anterior ao dia simulado; publicar usa o relógio do Database.
        with patch.object(self.db, "_now", lambda: self.t0 - timedelta(days=1)):
            self.db.publicar_recursos_pcfactory([{
                "codigo": code, "nome": code, "tipo_setor": "Corte", "habilitado": True,
            }])

    def test_nesting_em_execucao_no_almoco_segue_em_producao(self):
        self._cut_plan()
        self._publish_cut_resource("PLASMA")
        machine = "Laser Ensis 3015"
        started = self.db.iniciar_apontamento_corte(
            "HASH-CORTE-SD", machine, "CORTADOR", "2026-01-01", data_inicio=self._at(150),
        )

        changed = self.db.iniciar_intervalo_automatico(
            self._at(LUNCH_START), "Almoço", tipo_setor="Corte"
        )
        paused = {row["recurso"] for row in changed}
        self.assertNotIn(resolve_resource_identity(machine), paused)
        self.assertIn("PLASMA", paused)

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        self.db.finalizar_apontamento_corte(started["id"], "CORTADOR", data_fim=self._at(250))
        timeline = self._timeline(machine)
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "fila"])
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

        totals, stops, calc = self._oee_bases(150, 250, machine)
        self.assertEqual(totals[EventCategory.PRODUCTION], 6000)  # 150-250, almoço incluso
        self.assertEqual(totals.get(EventCategory.DOWNTIME, 0), 0)
        self.assertEqual(calc.time_bases["available_seconds"], 6000)
        self.assertEqual(calc.availability.value, 100.0)

    def test_nesting_da_manha_encerrado_no_almoco_entra_na_pausa(self):
        self._cut_plan()
        machine = "Laser Ensis 3015"
        started = self.db.iniciar_apontamento_corte(
            "HASH-CORTE-SD", machine, "CORTADOR", "2026-01-01", data_inicio=self._at(150),
        )
        self.db.iniciar_intervalo_automatico(self._at(LUNCH_START), "Almoço", tipo_setor="Corte")
        self.db.finalizar_apontamento_corte(started["id"], "CORTADOR", data_fim=self._at(210))

        during = self._timeline(machine)[-1]
        self.assertEqual(during["tipo_interrupcao"], "intervalo_programado")
        self.assertEqual(during["data_inicio"], self._at(210))

        self.db.finalizar_intervalo_automatico(self._at(LUNCH_END), "Almoço")
        timeline = self._timeline(machine)
        self.assertEqual([row["categoria"] for row in timeline], ["producao", "parada", "fila"])
        self._assert_no_demand(timeline[-1])
        self._assert_continuous(timeline)

        totals, stops, calc = self._oee_bases(150, LUNCH_END, machine)
        self.assertEqual(totals[EventCategory.PRODUCTION], 3600)  # 150-210
        self.assertEqual(stops[StopClassification.PLANNED], 1320)  # 210-232
        self.assertEqual(calc.time_bases["available_seconds"], 3600)

    def test_alterar_h2_nao_reescreve_a_linha_do_tempo_gravada(self):
        # 18:00-19:00 na H2 original (17:30-21:30), fora de turno às 21:30.
        item = self._started_op(minute=9 * 60)
        self._finish(item, 10 * 60)
        self.db.interromper_recursos_ociosos_fim_turno(self._at(750))
        timeline = self._timeline()
        totals, stops, calc = self._oee_bases(0, 780)
        self.assertFalse(self.db._fora_do_turno(RESOURCE, self._at(12 * 60)))  # 21:00

        # H2 encurtada para 20:30 à meia-noite do dia seguinte (vigência).
        h2 = next(row for row in self.db.listar_parametros_turno() if row["nome"] == "H2")
        with patch.object(self.db, "_now", lambda: self._at(15 * 60)):
            self.db.salvar_parametro_turno(
                nome="H2", tipo=h2["tipo"], hora_inicio=time(17, 30), hora_fim=time(20, 30),
                ordem=h2["ordem"], parametro_id=h2["id"],
            )

        # O dia já vivido continua com a H2 que valia nele; o seguinte usa a nova.
        self.assertFalse(self.db._fora_do_turno(RESOURCE, self._at(12 * 60)))
        self.assertTrue(self.db._fora_do_turno(RESOURCE, self._at(36 * 60)))
        self.assertEqual(self._timeline(), timeline)
        after_totals, after_stops, after_calc = self._oee_bases(0, 780)
        self.assertEqual(after_totals, totals)
        self.assertEqual(after_stops, stops)
        self.assertEqual(after_calc.time_bases, calc.time_bases)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TimelineSoDePostosApontaveisTests(unittest.TestCase):
    """Recurso só sincronizado fica fora da timeline automática e das somas;
    estação de solda sem código de catálogo entra (pedido de 25/09/2026)."""

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))
        self.t0 = datetime(2026, 9, 22, 9, 0)
        with patch.object(self.db, "_now", lambda: self.t0 - timedelta(days=1)):
            self.db.publicar_recursos_pcfactory([
                {"codigo": "LASER1", "nome": "Laser", "tipo_setor": "Corte", "habilitado": True},
                {"codigo": "ALMOXS", "nome": "Almox", "tipo_setor": None, "habilitado": True},
            ])

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _auto(self, recurso):
        return self.db.transicionar_estado_recurso(
            recurso, "fila", data_hora=self.t0, automatico=True,
            origem="sincronizacao_recurso_sem_demanda",
        )

    def test_inventario_tem_estacoes_de_solda_e_nao_tem_catalogo_puro(self):
        codes = {row["codigo"]: row for row in self.db.listar_recursos_ativos_scheduler()}
        self.assertIn("LASER1", codes)
        self.assertNotIn("ALMOXS", codes)
        self.assertEqual(codes["Estação 1"]["tipo_setor"], "Solda Aço")
        self.assertEqual(codes["Alumínio 3"]["tipo_setor"], "Solda Alumínio")

    def test_escrita_automatica_so_em_posto_apontavel(self):
        self.assertIsNone(self._auto("ALMOXS"))
        self.assertEqual(self._auto("Estação 2")["categoria"], "fila")

    def test_soma_de_tempo_ignora_recurso_so_sincronizado(self):
        self.db.transicionar_estado_recurso("ALMOXS", "fila", data_hora=self.t0)
        self._auto("LASER1")
        fim = self.t0 + timedelta(hours=1)
        recursos = {row["recurso"] for row in self.db.listar_estados_recurso_periodo(self.t0, fim)}
        self.assertEqual(recursos, {"LASER1"})
        atuais = {row["recurso"] for row in self.db.listar_estados_recurso_atuais()}
        self.assertEqual(atuais, {"LASER1"})

    def test_estacao_nova_nao_ganha_pausa_retroativa(self):
        almoco = datetime(2026, 9, 22, 12, 10)
        pausadas = lambda: {  # noqa: E731
            row["recurso"] for row in self.db.iniciar_intervalo_automatico(
                almoco, "Almoço", tipo_setor="Solda Aço"
            )
        }
        self.assertEqual(pausadas(), set())
        self._auto("Estação 2")  # primeiro estado às 09:00, antes do almoço
        self.assertEqual(pausadas(), {"Estação 2"})

    def test_chave_de_dev_devolve_os_recursos_so_sincronizados(self):
        with patch("app.core.operator_sectors.INCLUIR_RECURSOS_SO_SINCRONIZADOS", True):
            self.assertIsNotNone(self._auto("ALMOXS"))
            codes = {row["codigo"] for row in self.db.listar_recursos_ativos_scheduler()}
        self.assertIn("ALMOXS", codes)
