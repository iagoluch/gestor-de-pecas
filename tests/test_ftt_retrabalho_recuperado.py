"""FTT e peça recuperada do retrabalho (manufatura, 19/10/2026, migration 64).

Regra: peça que foi para retrabalho fica fora das boas de primeira, mesmo
recuperada depois; a recuperação continua contando como peça boa produzida
(``good``), mas não soma outra boa ao FTT nem reentra na base por nova tentativa
de retrabalho. Cada peça entra UMA vez na base da operação.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from uuid import uuid4

from mes.analytics.oee import calculate_oee
from mes.domain.industrial import EventCategory
from tests.test_value_explanation import (
    DIA,
    _BaseRepo,
    _EventRepo,
    _event,
    _filters,
    _service,
    _tree,
)


def _ftt(good, scrap, rework, **recovered):
    return calculate_oee(
        seconds_by_category={EventCategory.PRODUCTION: 3600.0},
        good_quantity=good,
        scrap_quantity=scrap,
        rework_quantity=rework,
        standard_run_seconds=3600.0,
        **recovered,
    ).ftt


def _qualidade_9_boas_1_retrabalho_recuperado(tentativas=1):
    """9 aprovadas + 1 retrabalho; a peça volta ``tentativas`` vez(es) e é aprovada."""

    eventos = [
        _event(1, "boa", 9, "Qualidade", "QLD1", hora=9),
        _event(2, "retrabalho", 1, "Qualidade", "QLD1", hora=9),
    ]
    for tentativa in range(1, tentativas):
        eventos.append(
            _event(
                10 + tentativa, "retrabalho", 1, "Qualidade", "QLD1",
                hora=10 + tentativa, quantidade_recuperada=1,
            )
        )
    eventos.append(
        _event(99, "boa", 1, "Qualidade", "QLD1", hora=20, quantidade_recuperada=1)
    )
    return eventos


class FttCalculoTests(unittest.TestCase):
    def test_sem_recuperada_a_formula_e_a_de_sempre(self):
        self.assertAlmostEqual(_ftt(9, 0, 1).value, 90.0)

    def test_nove_boas_e_um_retrabalho_recuperado_da_noventa_por_cento(self):
        # 10 boas físicas (9 + a recuperada), 1 retrabalho: 9 / 10, não 10 / 11.
        ftt = _ftt(10, 0, 1, recovered_good_quantity=1)
        self.assertAlmostEqual(ftt.value, 90.0)
        self.assertNotAlmostEqual(_ftt(10, 0, 1).value, 90.0)

    def test_nova_tentativa_nao_aumenta_a_base(self):
        # 2 tentativas de retrabalho da mesma peça: base continua 10.
        ftt = _ftt(10, 0, 2, recovered_good_quantity=1, recovered_rework_quantity=1)
        self.assertAlmostEqual(ftt.value, 90.0)

    def test_refugo_depois_do_retrabalho_nao_duplica_a_peca(self):
        # 9 boas, 1 peça foi p/ retrabalho e depois virou refugo: base = 10.
        ftt = _ftt(9, 1, 1, recovered_scrap_quantity=1)
        self.assertAlmostEqual(ftt.value, 90.0)

    def test_so_recuperacao_no_periodo_nao_inventa_ftt(self):
        ftt = _ftt(1, 0, 0, recovered_good_quantity=1)
        self.assertIsNone(ftt.value)
        self.assertIn("recuperações de retrabalho", ftt.reason)


class FttGerencialEExplicacaoTests(unittest.TestCase):
    def test_overview_mantem_producao_fisica_e_tira_a_recuperada_do_ftt(self):
        repo = _EventRepo(_qualidade_9_boas_1_retrabalho_recuperado())
        _, overview = _tree(repo, "qtd.ftt")
        production = overview["production"]
        self.assertEqual(production["good"], 10)  # produção física intacta
        self.assertEqual(production["rework"], 1)
        self.assertEqual(production["ftt_recovered"], {"good": 1, "scrap": 0, "rework": 0})
        self.assertAlmostEqual(overview["kpis"]["ftt"]["value"], 90.0)

    def test_duas_tentativas_da_mesma_peca_mantem_a_base_em_dez(self):
        repo = _EventRepo(_qualidade_9_boas_1_retrabalho_recuperado(tentativas=2))
        _, overview = _tree(repo, "qtd.ftt")
        production = overview["production"]
        self.assertEqual((production["good"], production["rework"]), (10, 2))
        self.assertAlmostEqual(overview["kpis"]["ftt"]["value"], 90.0)

    def test_oee_do_setor_usa_o_mesmo_ftt(self):
        repo = _EventRepo(_qualidade_9_boas_1_retrabalho_recuperado())
        _, management = _service(repo)
        overview = management.get_overview(_filters())
        setor = next(
            item for item in overview["sector_kpis"] if item["setor"] == "Qualidade"
        )
        self.assertAlmostEqual(setor["metrics"]["ftt"]["value"], 90.0)

    def test_conta_aberta_do_ftt_mostra_a_regra_e_fecha_com_o_overview(self):
        repo = _EventRepo(_qualidade_9_boas_1_retrabalho_recuperado())
        tree, overview = _tree(repo, "qtd.ftt")
        self.assertAlmostEqual(tree["value"], overview["kpis"]["ftt"]["value"])
        self.assertAlmostEqual(tree["value"], 90.0)
        self.assertTrue(tree["reconciliation"]["ok"])
        self.assertIn("uma única vez na base", tree["rule"])
        self.assertIn("1 peças recuperadas", tree["reason"])
        self.assertIn(
            "Peças recuperadas do retrabalho", [item["label"] for item in tree["excluded"]]
        )

    def test_peca_boa_continua_mostrando_a_producao_fisica(self):
        tree, _ = _tree(_EventRepo(_qualidade_9_boas_1_retrabalho_recuperado()), "qtd.boa")
        self.assertEqual(tree["value"], 10.0)

    def test_fallback_sem_eventos_usa_o_apontamento_de_retorno(self):
        fatos = [
            {
                "id": 1, "op": "OP-1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
                "status": "Finalizado", "quantidade_boa": 9, "quantidade_refugo": 0,
                "quantidade_retrabalho": 1, "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
            },
            {
                "id": 2, "op": "OP-1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
                "status": "Finalizado", "quantidade_boa": 1, "quantidade_refugo": 0,
                "quantidade_retrabalho": 0, "retorno_retrabalho_qualidade": True,
                "data_inicio": datetime(2026, 8, 19, 10, 0),
                "data_fim": datetime(2026, 8, 19, 11, 0),
            },
        ]
        _, management = _service(_BaseRepo(facts=fatos))
        overview = management.get_overview(_filters())
        self.assertEqual(overview["production"]["good"], 10)
        self.assertAlmostEqual(overview["kpis"]["ftt"]["value"], 90.0)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class FttRecuperadaPostgresTests(unittest.TestCase):
    """Grava de verdade: a marca nasce no evento canônico (migration 64)."""

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database

        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "ftt_rec_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop_schema(self):
        import psycopg
        from psycopg import sql

        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _scalar(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchone().values())[0]

    def _apontamento(
        self, *, setor, boas=0, retrabalho=0, retorno=False, quantidade=10,
        status="Em processo",
    ):
        return self._scalar(
            """
            INSERT INTO apontamentos_operacionais (
                op, tipo_setor, maquina, status, quantidade, operador_fila,
                data_entrada, data_inicio, quantidade_boa, quantidade_retrabalho,
                retorno_retrabalho_qualidade
            ) VALUES ('OP-FTT', %s, 'RECURSO1', %s, %s, 'Ana', %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (setor, status, quantidade, DIA, DIA, boas, retrabalho, retorno),
        )

    def _cracha(self, cracha="9001"):
        self._scalar(
            "INSERT INTO operadores_apontamento (cracha, nome) VALUES (%s, 'Ana')"
            " RETURNING id",
            (cracha,),
        )
        return cracha

    def _eventos(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT tipo, quantidade, quantidade_recuperada"
                " FROM eventos_quantidade_producao ORDER BY id"
            )
            return [dict(row) for row in cursor.fetchall()]

    def test_migration_64_coluna_default_zero_e_idempotente(self):
        from app.database.migrations import FTT_RECUPERADA_STATEMENTS
        from app.database.schema import SCHEMA_VERSION

        self.assertGreaterEqual(SCHEMA_VERSION, 64)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 64"), 1
        )
        evento = self.db.registrar_evento_quantidade("boa", 3, "OP-FTT", data_hora=DIA)
        self.assertEqual(evento["quantidade_recuperada"], 0)  # sem retroativo: default 0
        with self.db.connection() as connection, connection.cursor() as cursor:
            for statement in FTT_RECUPERADA_STATEMENTS:
                cursor.execute(statement)  # reaplicar não falha

    def test_registrar_evento_marca_a_recuperada_inteira(self):
        evento = self.db.registrar_evento_quantidade(
            "boa", 2, "OP-FTT", data_hora=DIA, recuperada=True
        )
        self.assertEqual(evento["quantidade_recuperada"], 2)
        self.assertEqual(self._eventos()[-1]["quantidade"], 2)  # física intacta

    def test_reinspecao_na_qualidade_marca_a_boa_como_recuperada(self):
        # Qualidade: 9 boas + 1 retrabalho já gravados; a reinspeção aprova 1.
        apontamento = self._apontamento(setor="Qualidade", boas=9, retrabalho=1)
        linha = self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", quantidade_boa=1, data_hora=DIA
        )
        self.assertEqual(linha["status"], "Finalizado")
        self.assertEqual(linha["quantidade_boa"], 10)  # produção física/ERP intacta
        self.assertEqual(
            self._eventos(), [{"tipo": "boa", "quantidade": 1, "quantidade_recuperada": 1}]
        )

    def test_primeira_passagem_da_qualidade_nao_e_marcada(self):
        apontamento = self._apontamento(setor="Qualidade")
        self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", quantidade_boa=9, quantidade_retrabalho=1,
            data_hora=DIA,
        )
        self.assertEqual(
            self._eventos(),
            [
                {"tipo": "boa", "quantidade": 9, "quantidade_recuperada": 0},
                {"tipo": "retrabalho", "quantidade": 1, "quantidade_recuperada": 0},
            ],
        )

    def test_nova_tentativa_na_reinspecao_nao_reentra_na_base(self):
        apontamento = self._apontamento(setor="Qualidade", boas=9, retrabalho=1)
        self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", quantidade_retrabalho=1, data_hora=DIA
        )
        self.assertEqual(
            self._eventos(),
            [{"tipo": "retrabalho", "quantidade": 1, "quantidade_recuperada": 1}],
        )

    def test_apontamento_de_retorno_do_retrabalho_marca_o_que_lanca(self):
        apontamento = self._apontamento(setor="Dobra", retorno=True, quantidade=1)
        self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", quantidade_boa=1, data_hora=DIA
        )
        self.assertEqual(
            self._eventos(), [{"tipo": "boa", "quantidade": 1, "quantidade_recuperada": 1}]
        )

    def test_operacao_comum_nao_e_marcada(self):
        apontamento = self._apontamento(setor="Dobra")
        self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", quantidade_boa=10, data_hora=DIA
        )
        self.assertEqual(
            self._eventos(), [{"tipo": "boa", "quantidade": 10, "quantidade_recuperada": 0}]
        )

    # --- "Finalizar Ret." (20/10/2026): encerra o retrabalho, OP volta a Em processo ---

    def _finalizar_retrabalho(self, *, boas=9, retrabalho=1, **quantidades):
        cracha = self._cracha()
        apontamento = self._apontamento(
            setor="Dobra", boas=boas, retrabalho=retrabalho, status="Retrabalho"
        )
        linha = self.db.transicionar_apontamento_operador(
            apontamento, "producao", "Ana", operadores_cracha=[cracha],
            data_hora=DIA, encerrar_retrabalho=True, **quantidades,
        )
        return apontamento, linha

    def test_encerrar_retrabalho_so_com_refugo_marca_a_recuperada(self):
        _, linha = self._finalizar_retrabalho(quantidade_boa=0, quantidade_refugo=1)
        self.assertEqual(linha["status"], "Em processo")  # não finaliza a OP
        self.assertIsNone(linha["data_fim"])
        self.assertEqual(linha["quantidade_refugo"], 1)
        self.assertEqual(
            self._eventos(), [{"tipo": "refugo", "quantidade": 1, "quantidade_recuperada": 1}]
        )

    def test_encerrar_retrabalho_so_com_boas_marca_a_recuperada(self):
        _, linha = self._finalizar_retrabalho(quantidade_boa=1, quantidade_refugo=0)
        self.assertEqual(linha["status"], "Em processo")
        self.assertEqual(linha["quantidade_boa"], 10)  # produção física intacta
        self.assertEqual(
            self._eventos(), [{"tipo": "boa", "quantidade": 1, "quantidade_recuperada": 1}]
        )

    def test_encerrar_retrabalho_campo_vazio_vale_zero(self):
        _, linha = self._finalizar_retrabalho(quantidade_boa=None, quantidade_refugo=1)
        self.assertEqual(linha["quantidade_refugo"], 1)
        self.assertEqual(
            self._eventos(), [{"tipo": "refugo", "quantidade": 1, "quantidade_recuperada": 1}]
        )

    def test_encerrar_retrabalho_zero_a_zero_so_volta_a_producao(self):
        _, linha = self._finalizar_retrabalho()
        self.assertEqual(linha["status"], "Em processo")
        self.assertEqual(self._eventos(), [])

    def test_encerrar_retrabalho_misto_marca_boa_e_refugo(self):
        # 8 boas + 2 em retrabalho: 1 volta boa e 1 vira refugo.
        _, linha = self._finalizar_retrabalho(
            boas=8, retrabalho=2, quantidade_boa=1, quantidade_refugo=1
        )
        self.assertEqual(linha["status"], "Em processo")
        self.assertEqual(
            self._eventos(),
            [
                {"tipo": "boa", "quantidade": 1, "quantidade_recuperada": 1},
                {"tipo": "refugo", "quantidade": 1, "quantidade_recuperada": 1},
            ],
        )

    def test_encerrar_retrabalho_registra_evento_de_producao(self):
        # O tempo de produção normal volta a correr: o último estado é 'producao'.
        apontamento, _ = self._finalizar_retrabalho(quantidade_boa=1)
        estados = self._scalar(
            "SELECT estado FROM eventos_apontamento_operador"
            " WHERE apontamento_id = %s ORDER BY id DESC LIMIT 1",
            (apontamento,),
        )
        self.assertEqual(estados, "producao")

    def test_encerrar_retrabalho_cracha_invalido_e_recusado_sem_gravar(self):
        apontamento = self._apontamento(
            setor="Dobra", boas=9, retrabalho=1, status="Retrabalho"
        )
        with self.assertRaisesRegex(ValueError, "Crachá não cadastrado"):
            self.db.transicionar_apontamento_operador(
                apontamento, "producao", "Ana", operadores_cracha=["0000"],
                quantidade_boa=1, data_hora=DIA, encerrar_retrabalho=True,
            )
        self.assertEqual(self._eventos(), [])
        self.assertEqual(
            self._scalar("SELECT status FROM apontamentos_operacionais WHERE id = %s", (apontamento,)),
            "Retrabalho",
        )

    def test_encerrar_retrabalho_nao_ultrapassa_o_saldo(self):
        cracha = self._cracha()
        apontamento = self._apontamento(
            setor="Dobra", boas=9, retrabalho=1, status="Retrabalho"
        )
        with self.assertRaisesRegex(ValueError, "excede"):
            self.db.transicionar_apontamento_operador(
                apontamento, "producao", "Ana", operadores_cracha=[cracha],
                quantidade_boa=1, quantidade_refugo=1, data_hora=DIA,
                encerrar_retrabalho=True,
            )
        self.assertEqual(self._eventos(), [])

    def test_retrabalho_para_producao_sem_a_marca_continua_recusado(self):
        apontamento = self._apontamento(
            setor="Dobra", boas=9, retrabalho=1, status="Retrabalho"
        )
        self.assertIsNone(
            self.db.transicionar_apontamento_operador(
                apontamento, "producao", "Ana", quantidade_boa=1, data_hora=DIA
            )
        )

    def test_encerrar_retrabalho_so_vale_a_partir_do_retrabalho(self):
        apontamento = self._apontamento(setor="Dobra", status="Em processo")
        self.assertIsNone(
            self.db.transicionar_apontamento_operador(
                apontamento, "producao", "Ana", data_hora=DIA, encerrar_retrabalho=True
            )
        )

    def test_ftt_9_boas_1_retrabalho_recuperado_da_90_por_cento(self):
        self._finalizar_retrabalho(quantidade_boa=1)
        eventos = self._eventos()
        recuperada = sum(e["quantidade_recuperada"] for e in eventos if e["tipo"] == "boa")
        self.assertEqual(recuperada, 1)
        # 9 boas de primeira + 1 recuperada (física: 10), 1 retrabalho na base.
        self.assertAlmostEqual(
            _ftt(10, 0, 1, recovered_good_quantity=recuperada).value, 90.0
        )

    def test_finalizar_comum_fora_do_retrabalho_nao_e_marcado(self):
        cracha = self._cracha()
        apontamento = self._apontamento(setor="Dobra", status="Em processo")
        self.db.transicionar_apontamento_operador(
            apontamento, "finalizado", "Ana", operadores_cracha=[cracha],
            quantidade_boa=10, data_hora=DIA,
        )
        self.assertEqual(
            self._eventos(), [{"tipo": "boa", "quantidade": 10, "quantidade_recuperada": 0}]
        )


if __name__ == "__main__":
    unittest.main()
