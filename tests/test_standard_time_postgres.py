"""Tempo padrão manual/estimado contra o Postgres real (migration 56).

Schema isolado em ``TEST_DATABASE_URL`` (nunca o REAL), criado e descartado por
teste. Cobre o SQL que os dublês de ``test_standard_time.py`` não executam: a
consulta de fatos com a prioridade da fonte, o repositório e a reimportação.
"""

from datetime import datetime, timedelta
import os
import threading
import time
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from app.database import migrations as migrations_module
from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.migrations import apply_migrations
from app.database.schema import SCHEMA_VERSION
from mes.domain.standard_time import normalize_key
from mes.services.standard_time import StandardTimeRuleError, StandardTimeService

AGORA = datetime(2026, 10, 6, 9, 0)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class StandardTimePostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "tempo_padrao_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        # Relógio do sistema controlável: a vigência do manual usa o instante de
        # "agora". Padrão: 3h antes de AGORA, ou seja, antes do início (AGORA-2h)
        # dos fatos de ``_apontar``; os testes de vigência movem o relógio.
        self.clock = AGORA - timedelta(hours=3)
        self.db = Database(
            make_conninfo(base.dsn, options=f"-c search_path={self.schema}"),
            now_func=lambda: self.clock,
        )
        self.service = StandardTimeService(self.db, now_func=lambda: AGORA)
        for op in ("OP1", "OP2", "OP3"):
            self._exec(
                "INSERT INTO catalogo_pcp_ops (codigo_op, produto_codigo, produto_descricao,"
                " quantidade, data_emissao, local_estoque, sincronizado_em)"
                " VALUES (%s, 'PROD1', 'Produto', 10, %s, '01', %s)",
                (op, AGORA.date(), AGORA),
            )
        # Dobra sem tempo (Protheus 0,01 -> NULL), Solda com Protheus real, Corte sem tempo.
        self._catalogo("OP1", "prod1", "20", "dobra1", "Dobra", None)
        self._catalogo("OP2", "PROD1", "20", "DOBRA1", "Dobra", None)  # mesma chave, outra OP
        self._catalogo("OP1", "PROD1", "30", "SOLDA1", "Solda", 42.0)
        self._catalogo("OP3", "PROD2", "10", "LASER1", "Corte", None)

    def _drop_schema(self):
        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _exec(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)

    def _catalogo(self, op, produto, operacao, recurso, setor, tempo):
        self._exec(
            """
            INSERT INTO catalogo_operacoes_op (
                codigo_op, produto_codigo, produto_descricao, numero_operacao,
                codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                tempo_medio_segundos, sincronizado_em
            ) VALUES (%s, %s, 'Produto', %s, %s, 'Operação', %s, %s, TRUE, %s, %s)
            """,
            (op, produto, operacao, recurso, setor, int(operacao) // 10, tempo, AGORA),
        )

    def _apontar(self, op, operacao, recurso, setor, inicio=None):
        inicio = inicio or AGORA - timedelta(hours=2)
        self._exec(
            """
            INSERT INTO apontamentos_operacionais (
                op, peca, tipo_setor, maquina, status, quantidade, operador_fila,
                data_entrada, data_inicio, numero_operacao, codigo_recurso, catalogo_operacao_id
            ) SELECT %s, 'PECA', %s, %s, 'Finalizado', 5, 'ENSAIO', %s, %s, %s, %s, c.id
              FROM catalogo_operacoes_op c
              WHERE c.codigo_op = %s AND c.numero_operacao = %s
            """,
            (op, setor, recurso, inicio, inicio, operacao, recurso, op, operacao),
        )

    def _fatos(self):
        fatos = self.db.listar_fatos_operacionais_periodo(AGORA - timedelta(days=1), AGORA)
        return {(f["op"], f["numero_operacao"]): f for f in fatos}

    # --- vigência: período fechado não muda -------------------------------
    def _apontar_em(self, op, dia, hora=8):
        """Fato de Dobra (chave PROD1/20/DOBRA1) iniciado às ``hora`` (padrão 08:00) de ``dia``."""

        self._apontar(op, "20", "DOBRA1", "Dobra", inicio=datetime(2026, 10, dia, hora, 0))

    def _padrao_por_dia(self, op="OP1"):
        """{dia do mês: (fonte, segundos)} dos fatos da OP, janela ampla."""

        fatos = self.db.listar_fatos_operacionais_periodo(
            datetime(2026, 9, 1), datetime(2026, 10, 31)
        )
        return {
            f["data_inicio"].day: (
                f["tempo_padrao_fonte"],
                None if f["tempo_padrao_segundos"] is None else float(f["tempo_padrao_segundos"]),
            )
            for f in fatos if f["op"] == op
        }

    def _dia(self, dia, hora=12):
        self.clock = datetime(2026, 10, dia, hora, 0)

    def test_manual_definido_depois_do_fato_nao_altera_o_fato(self):
        self._apontar_em("OP1", 5)
        self._apontar_em("OP1", 6)
        self._apontar_em("OP1", 7)
        self._dia(6)  # 12:00: o fato de 06 (08:00) começou antes do manual
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self.assertEqual(
            self._padrao_por_dia(), {5: (None, None), 6: (None, None), 7: ("manual", 40.0)}
        )

    def test_manual_do_mesmo_dia_vale_so_a_partir_do_instante(self):
        # Mesmo dia: fato da manhã (OP1, 08:00) não muda com manual definido às
        # 12:00; fato iniciado depois da definição (OP2, 13:00) usa o manual.
        self._apontar_em("OP1", 6, hora=8)
        self._apontar_em("OP2", 6, hora=13)
        self._dia(6, hora=12)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self.assertEqual(self._padrao_por_dia("OP1"), {6: (None, None)})
        self.assertEqual(self._padrao_por_dia("OP2"), {6: ("manual", 40.0)})

    def test_fato_iniciado_exatamente_no_instante_da_vigencia_ja_usa_o_manual(self):
        self._apontar_em("OP1", 6, hora=12)
        self._dia(6, hora=12)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self.assertEqual(self._padrao_por_dia(), {6: ("manual", 40.0)})

    def test_alterar_manual_nao_muda_periodo_anterior(self):
        for dia in (5, 6, 7, 8):
            self._apontar_em("OP1", dia)
        self._dia(6)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self._dia(7)
        self.service.set_manual("PROD1", "20", "DOBRA1", 50)
        self.assertEqual(
            self._padrao_por_dia(),
            {5: (None, None), 6: (None, None), 7: ("manual", 40.0), 8: ("manual", 50.0)},
        )
        # Mesmo dia, mais tarde: a última versão vence a partir do novo instante,
        # sem tocar nos fatos anteriores a ele.
        self._dia(7, hora=15)
        self.service.set_manual("PROD1", "20", "DOBRA1", 55)
        self.assertEqual(
            self._padrao_por_dia(),
            {5: (None, None), 6: (None, None), 7: ("manual", 40.0), 8: ("manual", 55.0)},
        )

    def test_remover_manual_nao_muda_periodo_anterior(self):
        for dia in (7, 8, 9):
            self._apontar_em("OP1", dia)
        self._dia(6)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self._dia(9)
        self.service.remove_manual("PROD1", "20", "DOBRA1")
        self.assertEqual(
            self._padrao_por_dia(),
            {7: ("manual", 40.0), 8: ("manual", 40.0), 9: ("manual", 40.0)},
        )
        # Fato posterior à remoção fica sem manual; redefinir vale só dali em diante.
        self._apontar_em("OP1", 10)
        self._dia(11)
        self._apontar_em("OP1", 12)
        self.service.set_manual("PROD1", "20", "DOBRA1", 60)
        self.assertEqual(
            self._padrao_por_dia(),
            {7: ("manual", 40.0), 8: ("manual", 40.0), 9: ("manual", 40.0),
             10: (None, None), 12: ("manual", 60.0)},
        )

    def test_estimado_nao_atinge_fato_anterior_a_vigente_desde(self):
        for dia in (5, 6, 8):
            self._apontar_em("OP1", dia)
        self._apontar_em("OP2", 7, hora=2)  # antes do cálculo (03:00): fora da vigência
        self._apontar_em("OP2", 9, hora=4)  # depois do cálculo
        registro = {"produto": "PROD1", "operacao": "20", "recurso": "DOBRA1",
                    "segundos_por_peca": 70.0, "amostras": 5,
                    "janela_inicio": datetime(2026, 9, 1), "janela_fim": datetime(2026, 10, 6)}
        self.db.substituir_tempos_padrao_estimados([registro], datetime(2026, 10, 7, 3, 0))
        esperado = {5: (None, None), 6: (None, None), 8: ("estimado", 70.0)}
        self.assertEqual(self._padrao_por_dia(), esperado)
        self.assertEqual(self._padrao_por_dia("OP2"), {7: (None, None), 9: ("estimado", 70.0)})
        # Recálculo do dia seguinte: o valor muda, a vigência (primeiro dia) não.
        self.db.substituir_tempos_padrao_estimados(
            [{**registro, "segundos_por_peca": 65.0}], datetime(2026, 10, 8, 3, 0)
        )
        self.assertEqual(
            self._padrao_por_dia(),
            {5: (None, None), 6: (None, None), 8: ("estimado", 65.0)},
        )
        item = next(
            i for i in self.db.listar_tempos_padrao(somente_sem_padrao=False)["items"]
            if i["numero_operacao"] == "20"
        )
        self.assertEqual(str(item["estimado_vigente_desde"]), "2026-10-07 03:00:00")

    def test_protheus_continua_vencendo_manual_e_estimado_em_qualquer_dia(self):
        for dia in (5, 6, 7):
            self._apontar_em("OP1", dia)
        self._dia(6)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self.db.substituir_tempos_padrao_estimados(
            [{"produto": "PROD1", "operacao": "20", "recurso": "DOBRA1",
              "segundos_por_peca": 70.0, "amostras": 5,
              "janela_inicio": datetime(2026, 9, 1), "janela_fim": datetime(2026, 10, 5)}],
            datetime(2026, 10, 5, 3, 0),
        )
        self._exec("UPDATE catalogo_operacoes_op SET tempo_medio_segundos = 33 WHERE numero_operacao = '20'")
        self.assertEqual(
            self._padrao_por_dia(),
            {5: ("protheus", 33.0), 6: ("protheus", 33.0), 7: ("protheus", 33.0)},
        )

    def test_listagem_e_historico_expoem_vigente_desde(self):
        self._dia(6)
        self.service.set_manual("PROD1", "20", "DOBRA1", 40)
        self._dia(7)
        self.service.set_manual("PROD1", "20", "DOBRA1", 50)
        item = next(
            i for i in self.db.listar_tempos_padrao(somente_sem_padrao=False)["items"]
            if i["numero_operacao"] == "20"
        )
        self.assertEqual(str(item["manual_vigente_desde"]), "2026-10-07 12:00:00")
        self.assertIsNone(item["estimado_vigente_desde"])
        historico = self.db.listar_historico_tempo_padrao_manual("PROD1", "20", "DOBRA1")
        self.assertEqual(
            [(h["acao"], str(h["vigente_desde"])) for h in historico],
            [("alterado", "2026-10-07 12:00:00"), ("definido", "2026-10-06 12:00:00")],
        )

    def test_schema_com_as_tres_tabelas(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 57)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = %s AND table_name LIKE 'tempo_padrao%%'",
                (self.schema,),
            )
            nomes = {row["table_name"] for row in cursor.fetchall()}
        self.assertEqual(
            nomes,
            {"tempo_padrao_manual", "tempo_padrao_manual_historico", "tempo_padrao_estimado"},
        )

    def test_prioridade_da_fonte_na_consulta_de_fatos(self):
        self._apontar("OP1", "20", "DOBRA1", "Dobra")
        self._apontar("OP1", "30", "SOLDA1", "Solda")
        self._apontar("OP3", "10", "LASER1", "Corte")
        fato = self._fatos()[("OP1", "20")]
        self.assertIsNone(fato["tempo_padrao_fonte"])
        self.assertIsNone(fato["tempo_padrao_segundos"])

        # Estimado vale quando não há Protheus nem manual...
        self.db.substituir_tempos_padrao_estimados(
            [{"produto": "PROD1", "operacao": "20", "recurso": "DOBRA1",
              "segundos_por_peca": 70.0, "amostras": 5,
              "janela_inicio": AGORA - timedelta(days=9), "janela_fim": AGORA - timedelta(days=1)}],
            AGORA - timedelta(hours=3),  # antes do início do fato (AGORA-2h)
        )
        fato = self._fatos()[("OP1", "20")]
        self.assertEqual((fato["tempo_padrao_fonte"], float(fato["tempo_padrao_segundos"])), ("estimado", 70.0))

        # ...manual vence o estimado...
        self.service.set_manual("prod1", "20", "dobra1", 55.5, usuario_nome="Eng")
        fato = self._fatos()[("OP1", "20")]
        self.assertEqual((fato["tempo_padrao_fonte"], float(fato["tempo_padrao_segundos"])), ("manual", 55.5))
        self.assertIsNone(fato["tempo_medio_segundos"])

        # ...e o Protheus real posterior vence o manual sem apagá-lo.
        self._exec("UPDATE catalogo_operacoes_op SET tempo_medio_segundos = 40 WHERE numero_operacao = '20'")
        fato = self._fatos()[("OP1", "20")]
        self.assertEqual((fato["tempo_padrao_fonte"], float(fato["tempo_padrao_segundos"])), ("protheus", 40.0))
        itens = self.db.listar_tempos_padrao(somente_sem_padrao=False)["items"]
        dobra = next(i for i in itens if i["numero_operacao"] == "20")
        self.assertEqual(float(dobra["tempo_manual_segundos"]), 55.5)
        self.assertEqual(dobra["fonte_efetiva"], "protheus")

        # Protheus volta a NULL (reimportação com 0,01): o manual reaparece.
        self._exec("UPDATE catalogo_operacoes_op SET tempo_medio_segundos = NULL WHERE numero_operacao = '20'")
        self.assertEqual(self._fatos()[("OP1", "20")]["tempo_padrao_fonte"], "manual")

        # Solda: Protheus real; Corte: nunca recebe estimado/manual.
        self.assertEqual(self._fatos()[("OP1", "30")]["tempo_padrao_fonte"], "protheus")
        self.assertIsNone(self._fatos()[("OP3", "10")]["tempo_padrao_fonte"])

    def test_corte_ignora_estimado_gravado_por_engano(self):
        self._apontar("OP3", "10", "LASER1", "Corte")
        self.db.substituir_tempos_padrao_estimados(
            [{"produto": "PROD2", "operacao": "10", "recurso": "LASER1",
              "segundos_por_peca": 5.0, "amostras": 9,
              "janela_inicio": AGORA - timedelta(days=9), "janela_fim": AGORA - timedelta(days=1)}],
            AGORA,
        )
        self.assertIsNone(self._fatos()[("OP3", "10")]["tempo_padrao_fonte"])

    def test_fatos_nao_duplicam_linhas_quando_ha_varias_ops_da_mesma_chave(self):
        self._apontar("OP1", "20", "DOBRA1", "Dobra")
        self._apontar("OP2", "20", "DOBRA1", "Dobra")
        self.service.set_manual("PROD1", "20", "DOBRA1", 50)
        fatos = self.db.listar_fatos_operacionais_periodo(AGORA - timedelta(days=1), AGORA)
        self.assertEqual(len(fatos), 2)

    def test_lista_agrupa_chave_filtra_e_pagina(self):
        lista = self.db.listar_tempos_padrao(somente_sem_padrao=True)
        # Dobra (2 OPs, 1 chave) sem padrão; Solda tem Protheus; Corte fora.
        self.assertEqual(
            [(i["produto_codigo"], i["numero_operacao"]) for i in lista["items"]], [("PROD1", "20")]
        )
        self.assertEqual(lista["total"], 1)
        self.assertEqual(self.db.listar_tempos_padrao(somente_sem_padrao=False)["total"], 2)
        self.assertEqual(self.db.listar_tempos_padrao(somente_sem_padrao=False, setor="solda")["total"], 1)
        self.assertEqual(self.db.listar_tempos_padrao(somente_sem_padrao=False, produto="prod2")["total"], 0)
        self.assertEqual(len(self.db.listar_tempos_padrao(somente_sem_padrao=False, limite=1)["items"]), 1)
        self.service.set_manual("PROD1", "20", "DOBRA1", 55)
        self.assertEqual(self.db.listar_tempos_padrao(somente_sem_padrao=True)["total"], 0)

    # --- "tem Protheus": tela e fatos seguem a mesma regra --------------------
    def _chave_mista(self):
        """PROD3/40/DOBRA3: OP1 com Protheus 30, OP2 sem (0,01 vira NULL), OP3 com 0."""

        self._catalogo("OP1", "PROD3", "40", "DOBRA3", "Dobra", 30.0)
        self._catalogo("OP2", "PROD3", "40", "DOBRA3", "Dobra", None)
        self._catalogo("OP3", "PROD3", "40", "DOBRA3", "Dobra", 0)
        for op in ("OP1", "OP2", "OP3"):
            self._apontar(op, "40", "DOBRA3", "Dobra")

    def _tela(self, produto):
        return next(
            i for i in self.db.listar_tempos_padrao(somente_sem_padrao=False, produto=produto)["items"]
        )

    def _fontes_dos_fatos(self, operacao):
        return {
            f["op"]: f["tempo_padrao_fonte"]
            for f in self.db.listar_fatos_operacionais_periodo(AGORA - timedelta(days=1), AGORA)
            if f["numero_operacao"] == operacao
        }

    def _tela_e_fatos_concordam(self, produto, operacao):
        """Tela só diz "tem Protheus" quando TODOS os fatos da chave usam o Protheus."""

        fontes = self._fontes_dos_fatos(operacao)
        item = self._tela(produto)
        todos_protheus = bool(fontes) and all(f == "protheus" for f in fontes.values())
        self.assertEqual(item["tempo_protheus_segundos"] is not None, todos_protheus, (item, fontes))
        self.assertEqual(
            item["linhas_com_protheus"], sum(1 for f in fontes.values() if f == "protheus"), (item, fontes)
        )
        self.assertEqual(item["linhas_total"], len(fontes))
        return item, fontes

    def test_chave_mista_tela_e_fatos_concordam_sobre_ter_protheus(self):
        self._chave_mista()
        item, fontes = self._tela_e_fatos_concordam("PROD3", "40")
        self.assertEqual(fontes, {"OP1": "protheus", "OP2": None, "OP3": None})
        # Sem Protheus em todas as linhas a chave continua precisando de manual.
        self.assertIsNone(item["tempo_protheus_segundos"])
        self.assertEqual((item["linhas_com_protheus"], item["linhas_total"]), (1, 3))
        self.assertIsNone(item["fonte_efetiva"])
        self.assertIn(
            ("PROD3", "40"),
            [(i["produto_codigo"], i["numero_operacao"])
             for i in self.db.listar_tempos_padrao(somente_sem_padrao=True)["items"]],
        )
        # O manual é aceito e cobre exatamente as linhas que ficaram sem padrão.
        self.service.set_manual("PROD3", "40", "DOBRA3", 77)
        self.assertEqual(
            self._fontes_dos_fatos("40"), {"OP1": "protheus", "OP2": "manual", "OP3": "manual"}
        )
        self.assertEqual(self._tela("PROD3")["fonte_efetiva"], "manual")
        self._tela_e_fatos_concordam("PROD3", "40")

    def test_chave_so_com_tempo_zero_ou_nulo_nao_tem_protheus_em_nenhum_lado(self):
        self._catalogo("OP1", "PROD4", "40", "DOBRA4", "Dobra", 0)
        self._catalogo("OP2", "PROD4", "40", "DOBRA4", "Dobra", None)
        self._apontar("OP1", "40", "DOBRA4", "Dobra")
        self._apontar("OP2", "40", "DOBRA4", "Dobra")
        self._tela_e_fatos_concordam("PROD4", "40")
        self.assertEqual(self._tela("PROD4")["linhas_com_protheus"], 0)

    def test_chave_toda_com_protheus_usa_o_valor_da_linha_mais_recente(self):
        self._catalogo("OP1", "PROD5", "40", "DOBRA5", "Dobra", 10.0)
        self._catalogo("OP2", "PROD5", "40", "DOBRA5", "Dobra", 12.0)
        self._exec(
            "UPDATE catalogo_operacoes_op SET sincronizado_em = %s"
            " WHERE codigo_op = 'OP2' AND numero_operacao = '40'",
            (AGORA + timedelta(hours=1),),
        )
        self._apontar("OP1", "40", "DOBRA5", "Dobra")
        self._apontar("OP2", "40", "DOBRA5", "Dobra")
        item, fontes = self._tela_e_fatos_concordam("PROD5", "40")
        self.assertEqual(set(fontes.values()), {"protheus"})
        self.assertEqual(float(item["tempo_protheus_segundos"]), 12.0)
        self.assertEqual(item["fonte_efetiva"], "protheus")
        contexto = self.db.obter_contexto_tempo_padrao("PROD5", "40", "DOBRA5")
        self.assertEqual(float(contexto["tempo_protheus_segundos"]), 12.0)

    def test_contexto_de_escrita_segue_a_mesma_regra_da_tela(self):
        self._chave_mista()
        contexto = self.db.obter_contexto_tempo_padrao("PROD3", "40", "DOBRA3")
        self.assertIsNone(contexto["tempo_protheus_segundos"])
        self.assertEqual((contexto["linhas_com_protheus"], contexto["linhas_total"]), (1, 3))

    # --- normalização da chave: Python == SQL ---------------------------------
    def test_normalize_key_python_equivale_ao_btrim_upper_do_sql(self):
        valores = ["  ab c ", "ab\t", "\tab", "ab ", "ab\n", " \tab\t ", "AB", "", "  "]
        with self.db.connection() as connection, connection.cursor() as cursor:
            for valor in valores:
                cursor.execute(
                    "SELECT UPPER(BTRIM(%s::text)) AS chave, BTRIM(%s::text) AS operacao", (valor, valor)
                )
                sql_row = cursor.fetchone()
                esperado = normalize_key(valor, valor, valor)
                self.assertEqual(sql_row["chave"], esperado[0], repr(valor))
                self.assertEqual(sql_row["operacao"], esperado[1], repr(valor))

    def test_chave_com_tab_no_catalogo_faz_o_ciclo_tela_manual_fato(self):
        self._catalogo("OP1", "ZZ9\t", "40", "DOBRA9", "Dobra", None)
        self._apontar("OP1", "40", "DOBRA9", "Dobra")
        item = self._tela("ZZ9")
        self.assertEqual(item["produto_codigo"], "ZZ9\t")
        self.service.set_manual(item["produto_codigo"], item["numero_operacao"], item["codigo_recurso"], 33)
        self.assertEqual(self._fontes_dos_fatos("40"), {"OP1": "manual"})

    # --- filtro de produto: LIKE literal --------------------------------------
    def test_filtro_de_produto_escapa_curingas_do_like(self):
        for idx, produto in enumerate(("AB_C", "ABXC", "50%OFF", "50XXOFF", "A\\B", "AXB")):
            self._catalogo("OP1", produto, "40", f"RECL{idx}", "Dobra", None)

        def produtos(termo):
            itens = self.db.listar_tempos_padrao(somente_sem_padrao=False, produto=termo)["items"]
            return sorted(i["produto_codigo"] for i in itens)

        self.assertEqual(produtos("ab_c"), ["AB_C"])
        self.assertEqual(produtos("0%o"), ["50%OFF"])
        self.assertEqual(produtos("a\\b"), ["A\\B"])
        self.assertEqual(produtos("%"), ["50%OFF"])
        self.assertEqual(produtos("_"), ["AB_C"])
        self.assertEqual(produtos("AB"), ["ABXC", "AB_C"])

    # --- histórico do manual: serialização por chave --------------------------
    def test_duas_primeiras_definicoes_simultaneas_gravam_definido_e_alterado(self):
        original = self.db._registrar_historico_tempo_padrao
        primeira = threading.Event()

        def historico_lento(*args, **kwargs):
            # Alarga a janela: a 1ª transação segura o commit enquanto a 2ª começa.
            if not primeira.is_set():
                primeira.set()
                time.sleep(0.4)
            return original(*args, **kwargs)

        self.db._registrar_historico_tempo_padrao = historico_lento
        partida = threading.Barrier(2)
        erros = []

        def definir(valor):
            try:
                partida.wait(timeout=5)
                self.db.definir_tempo_padrao_manual("PROD1", "20", "DOBRA1", valor, usuario_nome="Eng")
            except Exception as error:  # pragma: no cover - só se o teste falhar
                erros.append(error)

        threads = [threading.Thread(target=definir, args=(valor,)) for valor in (40, 50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(erros, [])
        historico = self.db.listar_historico_tempo_padrao_manual("PROD1", "20", "DOBRA1")
        self.assertEqual(sorted(h["acao"] for h in historico), ["alterado", "definido"])
        alterado = next(h for h in historico if h["acao"] == "alterado")
        definido = next(h for h in historico if h["acao"] == "definido")
        self.assertEqual(alterado["segundos_anterior"], definido["segundos_novo"])

    def test_manual_valida_regra_e_grava_historico(self):
        with self.assertRaises(StandardTimeRuleError) as protheus:
            self.service.set_manual("PROD1", "30", "SOLDA1", 10)
        self.assertEqual(protheus.exception.status_code, 409)
        with self.assertRaises(StandardTimeRuleError) as corte:
            self.service.set_manual("PROD2", "10", "LASER1", 10)
        self.assertEqual(corte.exception.status_code, 409)
        self.service.set_manual("PROD1", "20", "DOBRA1", 55, observacao="medido", usuario_nome="Eng")
        self.service.set_manual("PROD1", "20", "DOBRA1", 60, usuario_nome="Eng")
        self.service.remove_manual("PROD1", "20", "DOBRA1", usuario_nome="Eng")
        historico = self.db.listar_historico_tempo_padrao_manual("PROD1", "20", "DOBRA1")
        self.assertEqual(sorted(h["acao"] for h in historico), ["alterado", "definido", "removido"])
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._exec(
                "INSERT INTO tempo_padrao_manual (produto_codigo, numero_operacao, codigo_recurso,"
                " segundos_por_peca) VALUES ('X', '1', 'Y', 0)"
            )

    def test_substituir_estimados_e_idempotente_e_remove_obsoletos(self):
        registro = {"produto": "PROD1", "operacao": "20", "recurso": "DOBRA1",
                    "segundos_por_peca": 70.0, "amostras": 5,
                    "janela_inicio": AGORA - timedelta(days=9), "janela_fim": AGORA - timedelta(days=1)}
        outro = {**registro, "operacao": "30", "recurso": "SOLDA1"}
        self.db.substituir_tempos_padrao_estimados([registro, outro], AGORA)
        self.db.substituir_tempos_padrao_estimados([registro], AGORA + timedelta(days=1))
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT numero_operacao, segundos_por_peca FROM tempo_padrao_estimado")
            linhas = cursor.fetchall()
        self.assertEqual([(r["numero_operacao"], float(r["segundos_por_peca"])) for r in linhas], [("20", 70.0)])

    def test_recalculo_ponta_a_ponta(self):
        # 5 execuções da mesma chave (uma por dia), com eventos de produção.
        for dia in range(1, 6):
            inicio = datetime(2026, 10, 6) - timedelta(days=dia) + timedelta(hours=8)
            fim = inicio + timedelta(seconds=500 + 100 * dia)
            self._exec(
                """
                INSERT INTO apontamentos_operacionais (
                    op, peca, tipo_setor, maquina, status, quantidade, quantidade_boa, operador_fila,
                    data_entrada, data_inicio, data_fim, numero_operacao, codigo_recurso,
                    catalogo_operacao_id
                ) SELECT %s, 'PECA', 'Dobra', 'DOBRA1', 'Finalizado', 10, 10, 'ENSAIO', %s, %s, %s,
                         '20', 'DOBRA1', c.id
                  FROM catalogo_operacoes_op c WHERE c.codigo_op = 'OP1' AND c.numero_operacao = '20'
                """,
                (f"OPD{dia}", inicio, inicio, fim),
            )
            for estado, instante in (("producao", inicio), ("finalizado", fim)):
                self._exec(
                    """
                    INSERT INTO eventos_apontamento_operador (apontamento_id, estado, operador, data_hora)
                    SELECT id, %s, 'ENSAIO', %s FROM apontamentos_operacionais WHERE op = %s
                    """,
                    (estado, instante, f"OPD{dia}"),
                )
        resumo = self.service.recalculate_estimates()
        self.assertEqual(resumo["chaves_estimadas"], 1, resumo)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tempo_padrao_estimado")
            linhas = cursor.fetchall()
        self.assertEqual(len(linhas), 1)
        # 60, 70, 80, 90, 100 s/peça -> P25 = 70.
        self.assertEqual(float(linhas[0]["segundos_por_peca"]), 70.0)
        self.assertEqual(linhas[0]["amostras"], 5)
        self.assertEqual(self.service.last_estimate_run(), AGORA)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class StandardTimeVigenciaMigrationTests(unittest.TestCase):
    """Migration 57 sobre dados gravados na 56: backfill do dia de registro."""

    def test_backfill_de_vigente_desde_a_partir_do_registro_existente(self):
        base = load_postgres_config(testing=True)
        schema = "tempo_padrao_mig_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            dsn = make_conninfo(base.dsn, options=f"-c search_path={schema}")
            with psycopg.connect(dsn, row_factory=dict_row) as connection:
                original = migrations_module.SCHEMA_VERSION
                migrations_module.SCHEMA_VERSION = 56
                try:
                    self.assertEqual(apply_migrations(connection), 56)
                finally:
                    migrations_module.SCHEMA_VERSION = original
                connection.commit()
                connection.execute(
                    "INSERT INTO tempo_padrao_manual_historico (produto_codigo, numero_operacao,"
                    " codigo_recurso, acao, segundos_novo, registrado_em)"
                    " VALUES ('P', '10', 'R', 'definido', 40, '2026-10-02 15:30')"
                )
                connection.execute(
                    "INSERT INTO tempo_padrao_estimado (produto_codigo, numero_operacao,"
                    " codigo_recurso, segundos_por_peca, amostras, calculado_em, janela_inicio,"
                    " janela_fim) VALUES ('P', '10', 'R', 70, 5, '2026-10-04 03:00',"
                    " '2026-09-01', '2026-10-03')"
                )
                connection.commit()
                self.assertEqual(apply_migrations(connection), SCHEMA_VERSION)
                connection.commit()
                manual = connection.execute(
                    "SELECT vigente_desde FROM tempo_padrao_manual_historico"
                ).fetchone()
                estimado = connection.execute(
                    "SELECT vigente_desde FROM tempo_padrao_estimado"
                ).fetchone()
            self.assertEqual(str(manual["vigente_desde"]), "2026-10-02 15:30:00")
            self.assertEqual(str(estimado["vigente_desde"]), "2026-10-04 03:00:00")
        finally:
            with psycopg.connect(base.dsn, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


if __name__ == "__main__":
    unittest.main()
