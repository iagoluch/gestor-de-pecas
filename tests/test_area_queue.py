"""Fila manual por recurso: o líder ordena e puxa OPs; o operador vê e executa.

Todo acesso a PostgreSQL usa um schema descartável criado dentro de
``TEST_DATABASE_URL``. Nenhum teste escreve no banco REAL.
"""

from __future__ import annotations

from datetime import datetime
import os
from threading import Barrier, Thread
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from app.core.areas import recursos_da_area
from backend.api.config import WebSettings
from backend.api.main import create_app
from mes.services.manual_queue import ManualQueueError, ManualQueueService
from mes.services.operator_flow import OperatorFlowService
from tests.helpers import liberar_primeira_peca
from tests.test_totvs_operator_queue import RECURSOS_CANONICOS, _isolated_database

OP_A, OP_B, OP_C, OP_D, OP_E, OP_F, OP_G, OP_I = (f"Q000000000{n}" for n in range(1, 9))
SETOR = "Usinagem"
SENHA = "Fila-Manual#2026-xK9"
ROMI = "Romi D 1000"  # CNC-01
EUROSTEC = "Eurostec"  # CNC-02

RECURSOS = RECURSOS_CANONICOS + (
    {"codigo": "SERRA1", "nome": "S4220", "tipo_setor": "Serra"},
)


def _recurso(area_id, canonico):
    return next(
        item for item in recursos_da_area(area_id) if item["resource"] == canonico
    )


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class _PostgresCase(unittest.TestCase):
    def setUp(self):
        self.db, self.admin_dsn, self.schema = _isolated_database()
        self.db.publicar_recursos_pcfactory(RECURSOS)
        self._seed_execucao()
        self.romi = _recurso("usinagem", "CNC-01")
        self.eurostec = _recurso("usinagem", "CNC-02")
        # OP A, B, F, G: só CNC-01. C: só CNC-02. D: Corte e depois CNC-02.
        # E: Serra. I: CNC-01 e depois CNC-02.
        for codigo in (OP_A, OP_B, OP_F, OP_G):
            self._seed_op(codigo, [("10", "CNC-01", SETOR)])
        self._seed_op(OP_C, [("10", "CNC-02", SETOR)])
        self._seed_op(OP_D, [("10", "PLASMA", "Corte"), ("20", "CNC-02", SETOR)])
        self._seed_op(OP_I, [("10", "CNC-01", SETOR), ("20", "CNC-02", SETOR)])
        self._seed_op(OP_E, [("10", "SERRA1", "Serra")])
        self.fila = ManualQueueService(self.db, "LIDER TESTE")
        self.flow = OperatorFlowService(self.db, "OPERADOR TESTE")

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )

    def _seed_execucao(self):
        agora = datetime.now().replace(microsecond=0)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO catalogo_status_recursos (
                    codigo, nome, grupo_codigo, grupo_nome, habilitado,
                    setup, retrabalho, oculto, requer_comentario, sincronizado_em
                ) VALUES (%s, %s, %s, %s, TRUE, %s, %s, FALSE, FALSE, %s)
                """,
                [
                    ("0201", "FALTA DE MATERIAL", "0002", "PARADAS", False, False, agora),
                    ("0301", "SETUP", "0003", "SETUP", True, False, agora),
                    ("0401", "RETRABALHO", "0004", "RETRABALHO", False, True, agora),
                ],
            )
            cursor.execute(
                """
                INSERT INTO operadores_apontamento
                    (cracha, nome, ativo, fonte, autorizador_retrabalho)
                VALUES ('9001', 'OPERADOR TESTE', TRUE, 'teste', TRUE)
                """
            )

    def _seed_op(self, codigo_op, operacoes, quantidade=10):
        agora = datetime.now().replace(microsecond=0)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_pcp_ops (
                    codigo_op, produto_codigo, produto_descricao, quantidade,
                    unidade, status_pcp, ativo, sincronizado_em
                ) VALUES (%s, 'PROD-1', 'PRODUTO DE TESTE', %s, 'UN', '1', TRUE, %s)
                """,
                (codigo_op, quantidade, agora),
            )
            for ordem, (numero, recurso, setor) in enumerate(operacoes, start=1):
                cursor.execute(
                    """
                    INSERT INTO catalogo_operacoes_op (
                        codigo_op, produto_codigo, produto_descricao,
                        numero_operacao, codigo_recurso, descricao_operacao,
                        tipo_setor, ordem, fonte, ativo, sincronizado_em
                    ) VALUES (
                        %s, 'PROD-1', 'PRODUTO DE TESTE',
                        %s, %s, 'OPERACAO DE TESTE', %s, %s, 'teste_fila', TRUE, %s
                    )
                    """,
                    (codigo_op, numero, recurso, setor, ordem, agora),
                )

    def _operacao(self, codigo_op, numero="10"):
        return next(
            op for op in self.db.listar_operacoes_para_op(codigo_op)
            if op["numero_operacao"] == numero
        )

    def _id(self, codigo_op, numero="10"):
        return self._operacao(codigo_op, numero)["id"]

    def _ops(self, recurso):
        return [item["op"] for item in self.fila.listar(recurso)["items"]]

    def _vivas(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT codigo_op, recurso, posicao FROM fila_manual_recurso "
                "WHERE removida_em IS NULL ORDER BY recurso, posicao"
            )
            return [dict(row) for row in cursor.fetchall()]

    def _contexto(self, codigo_op, posto, numero="10"):
        return dict(
            op=codigo_op, setor=SETOR, recurso=posto,
            operacao=self._operacao(codigo_op, numero),
        )

    def _iniciar(self, codigo_op, posto, numero="10", **extra):
        contexto = self._contexto(codigo_op, posto, numero)
        liberar_primeira_peca(self.db, "OPERADOR TESTE", **contexto)
        return self.flow.executar("Início", **contexto, **extra)


class OrdemDaFilaTests(_PostgresCase):
    def test_ordem_do_lider_vale_para_o_operador(self):
        # Sem fixação a ordem é a automática (por OP).
        self.assertEqual(self._ops(self.romi), [OP_A, OP_B, OP_F, OP_G, OP_I])
        self.fila.adicionar(self.romi, OP_G)
        self.fila.adicionar(self.romi, OP_B)
        itens = self.fila.listar(self.romi)["items"]
        self.assertEqual([i["op"] for i in itens][:2], [OP_G, OP_B])
        self.assertEqual([i["fixada"] for i in itens][:3], [True, True, False])
        self.assertEqual([i["posicao"] for i in itens][:2], [1, 2])
        # O operador vê exatamente essa ordem no posto.
        cartoes = self.flow.listar_cartoes(SETOR, ROMI)["queue"]
        self.assertEqual([c["op"] for c in cartoes][:2], [OP_G, OP_B])

        resposta = self.fila.reordenar(
            self.romi, [self._id(OP_B), self._id(OP_G), self._id(OP_A)]
        )
        self.assertEqual([i["op"] for i in resposta["items"]][:3], [OP_B, OP_G, OP_A])
        self.assertEqual([i["fixada"] for i in resposta["items"]][:3], [True] * 3)
        self.assertEqual([i["posicao"] for i in resposta["items"]][:3], [1, 2, 3])

    def test_recurso_sem_fixacao_fica_intacto(self):
        antes = self._ops(self.eurostec)
        self.fila.adicionar(self.romi, OP_B)
        self.fila.reordenar(self.romi, [self._id(OP_B), self._id(OP_A)])
        self.assertEqual(self._ops(self.eurostec), antes)
        self.assertTrue(all(not i["fixada"] for i in self.fila.listar(self.eurostec)["items"]))

    def test_remover_volta_para_a_ordem_automatica(self):
        self.fila.adicionar(self.romi, OP_G)
        entrada = self.fila.listar(self.romi)["items"][0]
        self.assertEqual(entrada["op"], OP_G)
        resposta = self.fila.remover(self.romi, entrada["entry_id"])
        self.assertEqual([i["op"] for i in resposta["items"]][0], OP_A)
        self.assertEqual(self._vivas(), [])
        with self.assertRaises(ManualQueueError) as erro:
            self.fila.remover(self.romi, entrada["entry_id"])
        self.assertEqual(erro.exception.status_code, 404)

    def test_put_ignora_ids_que_nao_estao_na_fila(self):
        resposta = self.fila.reordenar(
            self.romi, [999999, self._id(OP_B), self._id(OP_B), self._id(OP_C)]
        )
        self.assertEqual([i["op"] for i in resposta["items"]][0], OP_B)
        self.assertEqual([v["codigo_op"] for v in self._vivas()], [OP_B])


class PuxarDeOutroRecursoTests(_PostgresCase):
    def test_op_puxada_some_da_fila_original_e_volta_ao_remover(self):
        self.assertIn(OP_C, self._ops(self.eurostec))
        resposta = self.fila.adicionar(self.romi, OP_C)
        puxada = resposta["items"][0]
        self.assertEqual(puxada["op"], OP_C)
        self.assertTrue(puxada["fixada"])
        self.assertEqual(puxada["origem_recurso"], EUROSTEC)
        self.assertNotIn(OP_C, self._ops(self.eurostec))

        self.fila.remover(self.romi, puxada["entry_id"])
        self.assertIn(OP_C, self._ops(self.eurostec))
        self.assertNotIn(OP_C, self._ops(self.romi))

    def test_puxar_de_novo_em_outro_recurso_move_a_fixacao(self):
        self.fila.adicionar(self.romi, OP_C)
        self.fila.adicionar(self.eurostec, OP_C)
        self.assertEqual([(v["codigo_op"], v["recurso"]) for v in self._vivas()], [(OP_C, "CNC-02")])
        self.assertIn(OP_C, self._ops(self.eurostec))
        self.assertNotIn(OP_C, self._ops(self.romi))

    def test_op_de_outro_setor_aparece_no_recurso_do_lider(self):
        # Serra puxando uma OP de Usinagem: precisa vir sem filtro de setor.
        serra = _recurso("serra", "SERRA1")
        resposta = self.fila.adicionar(serra, OP_A)
        self.assertEqual(resposta["items"][0]["op"], OP_A)
        self.assertEqual(resposta["items"][0]["origem_recurso"], ROMI)
        self.assertNotIn(OP_A, self._ops(self.romi))


class ValidacaoAoAdicionarTests(_PostgresCase):
    def _erro(self, recurso, op):
        with self.assertRaises(ManualQueueError) as erro:
            self.fila.adicionar(recurso, op)
        return erro.exception

    def test_op_inexistente_ou_inativa(self):
        self.assertEqual(self._erro(self.romi, "Q9999999999").code, "fila_manual_op_inexistente")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = %s", (OP_A,))
        self.assertEqual(self._erro(self.romi, OP_A).code, "fila_manual_op_inativa")

    def test_etapa_anterior_pendente_bloqueia(self):
        erro = self._erro(self.eurostec, OP_D)  # Corte (etapa 10) ainda não concluído
        self.assertEqual(erro.code, "fila_manual_etapa_anterior_pendente")
        self.assertEqual(erro.status_code, 409)
        self.assertIn("aguarda a etapa 10", erro.message)
        self.assertEqual(self._vivas(), [])

    def test_so_a_proxima_operacao_e_puxada_para_qualquer_recurso(self):
        # I ainda está na etapa 10: puxar para o CNC-02 fixa a etapa 10, não a 20.
        self.fila.adicionar(self.eurostec, OP_I)
        self.assertEqual(self._vivas()[0]["codigo_op"], OP_I)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT catalogo_operacao_id FROM fila_manual_recurso WHERE removida_em IS NULL"
            )
            self.assertEqual(cursor.fetchone()["catalogo_operacao_id"], self._id(OP_I, "10"))

    def test_op_ja_em_execucao_em_outro_recurso(self):
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        erro = self._erro(self.eurostec, OP_A)
        self.assertEqual(erro.code, "fila_manual_op_em_execucao")
        self.assertIn(f"Já em execução em {ROMI} desde ", erro.message)

    def test_adicionar_de_novo_no_mesmo_recurso_mantem_a_posicao(self):
        self.fila.adicionar(self.romi, OP_B)
        self.fila.adicionar(self.romi, OP_G)
        self.fila.adicionar(self.romi, OP_B)
        self.assertEqual(
            [(v["codigo_op"], v["posicao"]) for v in self._vivas()],
            [(OP_B, 1), (OP_G, 2)],
        )

    def test_op_sem_roteiro(self):
        agora = datetime.now().replace(microsecond=0)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_pcp_ops (
                    codigo_op, produto_codigo, produto_descricao, quantidade,
                    unidade, status_pcp, ativo, sincronizado_em
                ) VALUES ('Q0000000099', 'P', 'P', 1, 'UN', '1', TRUE, %s)
                """,
                (agora,),
            )
        self.assertEqual(self._erro(self.romi, "Q0000000099").code, "fila_manual_op_sem_roteiro")


class ExecucaoDoOperadorTests(_PostgresCase):
    def test_op_sai_da_fila_ao_finalizar(self):
        self.fila.adicionar(self.romi, OP_A)
        self.fila.adicionar(self.romi, OP_B)
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        fim = self.flow.executar(
            "Finalizado", **self._contexto(OP_A, ROMI),
            pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertTrue(fim.ok, fim.message)
        self.assertNotIn(OP_A, self._ops(self.romi))
        # A entrada morta é baixada na próxima escrita e a ordem segue limpa.
        self.fila.adicionar(self.romi, OP_G)
        self.assertEqual(
            [(v["codigo_op"], v["posicao"]) for v in self._vivas()],
            [(OP_B, 1), (OP_G, 2)],
        )

    def test_op_puxada_inicia_sem_cracha_de_autorizacao(self):
        # Controle: sem a ordem do líder, o recurso divergente exige crachá.
        sem_ordem = self._iniciar(OP_F, EUROSTEC)
        self.assertFalse(sem_ordem.ok)
        self.assertEqual(sem_ordem.code, "confirmacao_recurso_obrigatoria")

        # OP_C é do CNC-02 (Eurostec); o líder a puxou para o CNC-01 (Romi).
        self.fila.adicionar(self.romi, OP_C)
        puxada = self._iniciar(OP_C, ROMI)
        self.assertTrue(puxada.ok, puxada.message)
        linha = [
            r for r in self.db.listar_apontamentos_por_op(OP_C) if r["status"] == "Em processo"
        ]
        self.assertEqual(len(linha), 1)
        self.assertEqual(linha[0]["maquina"], ROMI)

    def test_ordem_do_lider_nao_dispensa_etapa_anterior_pendente(self):
        self.fila.adicionar(self.romi, OP_I)  # etapa 10 do CNC-01
        resposta = self._iniciar(OP_I, EUROSTEC, numero="20")
        self.assertFalse(resposta.ok)
        self.assertEqual(resposta.code, "confirmacao_etapa_anterior_obrigatoria")

    def test_bloqueia_inicio_paralelo_em_outro_recurso(self):
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        paralelo = self.flow.executar("Início", **self._contexto(OP_A, EUROSTEC))
        self.assertFalse(paralelo.ok)
        # A trava de "operação ativa em outro recurso" já existente responde
        # primeiro; a nova (operacao_em_execucao_em_outro_recurso) é a rede de
        # segurança para o mesmo caso. Qualquer uma recusa e cita o recurso.
        self.assertIn(
            paralelo.code,
            {"operacao_ativa_diferente", "operacao_em_execucao_em_outro_recurso"},
        )
        self.assertIn(ROMI, paralelo.message)
        em_processo = [
            r for r in self.db.listar_apontamentos_por_op(OP_A) if r["status"] == "Em processo"
        ]
        self.assertEqual(len(em_processo), 1)


class FilaCompartilhadaTests(_PostgresCase):
    """Solda/Pintura: todas as estações veem a mesma fila; o PUT não esconde nada."""

    def _checar(self, area, setor_rota, codigo_recurso, codigos_op):
        for indice, codigo in enumerate(codigos_op):
            self._seed_op(codigo, [("10", codigo_recurso, setor_rota)])
        recursos = recursos_da_area(area)
        visiveis = {
            r["resource"]: set(self._ops(r))
            for r in recursos
        }
        lider = recursos[0]
        fila_do_lider = [i for i in self.fila.listar(lider)["items"] if i["op"] in codigos_op]
        self.assertTrue(fila_do_lider, "o recurso do líder precisa ver as OPs")
        ids = [i["operation_id"] for i in reversed(fila_do_lider)]
        self.fila.reordenar(lider, ids)
        for recurso in recursos:
            depois = set(self._ops(recurso))
            self.assertEqual(
                depois & set(codigos_op), visiveis[recurso["resource"]] & set(codigos_op),
                recurso["resource"],
            )
        outros = [r for r in recursos[1:] if visiveis[r["resource"]] & set(codigos_op)]
        self.assertTrue(outros, "ao menos outra estação enxerga a mesma fila")
        # A ordem gravada vale só para o recurso do líder.
        self.assertTrue(all(not i["fixada"] for i in self.fila.listar(outros[0])["items"]))
        self.assertEqual(
            [i["op"] for i in self.fila.listar(lider)["items"] if i["op"] in codigos_op],
            [i["op"] for i in reversed(fila_do_lider)],
        )

    def test_solda_put_em_uma_estacao_nao_some_das_outras(self):
        self._checar("solda", "Solda Aço", "MT NT", ("S000000001", "S000000002"))

    def test_pintura_put_em_um_recurso_nao_some_dos_outros(self):
        self._checar("pintura", "Pintura", "PINT.L", ("P000000001", "P000000002"))

    def test_put_nao_vira_puxada_e_nao_dispensa_cracha(self):
        # OP do CNC-02 ordenada (PUT) no CNC-02: continua só lá e sem bypass no CNC-01.
        self.fila.reordenar(self.eurostec, [self._id(OP_C)])
        self.assertNotIn(OP_C, self._ops(self.romi))
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT puxada FROM fila_manual_recurso WHERE removida_em IS NULL")
            self.assertEqual([r["puxada"] for r in cursor.fetchall()], [False])

    def test_post_vira_puxada_mesmo_se_ja_ordenada_no_recurso(self):
        self.fila.reordenar(self.romi, [self._id(OP_A)])
        self.fila.adicionar(self.romi, OP_A)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT puxada, posicao FROM fila_manual_recurso WHERE removida_em IS NULL")
            self.assertEqual([(r["puxada"], r["posicao"]) for r in cursor.fetchall()], [(True, 1)])


class ConcorrenciaTests(_PostgresCase):
    def test_puts_simultaneos_deixam_posicoes_consistentes(self):
        ops = [OP_A, OP_B, OP_F, OP_G]
        for codigo in ops:
            self.fila.adicionar(self.romi, codigo)
        ids = [self._id(codigo) for codigo in ops]
        ordens = (ids, list(reversed(ids)))
        largada, erros = Barrier(2), []

        def trabalhar(ordem):
            try:
                largada.wait(timeout=10)
                for _ in range(8):
                    self.fila.reordenar(self.romi, ordem)
            except Exception as erro:  # noqa: BLE001 - o teste afirma que não houve nenhuma
                erros.append(erro)

        threads = [Thread(target=trabalhar, args=(ordem,)) for ordem in ordens]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        self.assertEqual(erros, [])
        vivas = self._vivas()
        self.assertEqual([v["posicao"] for v in vivas], [1, 2, 3, 4])
        self.assertEqual({v["codigo_op"] for v in vivas}, set(ops))


class AreaQueueApiTests(_PostgresCase):
    def setUp(self):
        super().setUp()
        self.db.criar_nivel_personalizado("lider_serra", "Líder Serra", "lider")
        self.db.criar_usuario("lider.serra", SENHA, "lider_serra")
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        self.client = TestClient(create_app(settings=settings, database_factory=lambda: self.db))
        self.client.__enter__()
        resposta = self.client.post(
            "/api/v1/auth/login", json={"username": "lider.serra", "password": SENHA}
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.csrf = {"X-CSRF-Token": self.client.cookies.get("gestor_csrf")}
        self.base = "/api/v1/areas/serra/queue"

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def test_exige_sessao(self):
        with TestClient(self.client.app) as anonimo:
            self.assertEqual(anonimo.get(f"{self.base}/resources").status_code, 401)

    def test_lider_da_serra_so_mexe_na_serra(self):
        for area in ("usinagem", "solda", "dobra-corte"):
            resposta = self.client.get(f"/api/v1/areas/{area}/queue/resources")
            self.assertEqual(resposta.status_code, 403, area)
            self.assertEqual(resposta.json()["code"], "area_access_denied")
        self.assertEqual(self.client.get("/api/v1/areas/inexistente/queue/resources").status_code, 404)
        # Recurso de outra área pedido pela área permitida.
        negado = self.client.get(self.base, params={"resource": "CNC-01"})
        self.assertEqual(negado.status_code, 403)
        self.assertEqual(negado.json()["code"], "area_resource_denied")
        negado = self.client.post(self.base, json={"resource": "CNC-01", "op": OP_A}, headers=self.csrf)
        self.assertEqual(negado.status_code, 403)
        self.assertEqual(self._vivas(), [])

    def test_fluxo_completo_e_formato_de_erro(self):
        recursos = self.client.get(f"{self.base}/resources").json()["items"]
        self.assertIn(
            {"resource": "SERRA1", "nome": "S4220", "setor": "Serra"}, recursos
        )

        sem_csrf = self.client.post(self.base, json={"resource": "SERRA1", "op": OP_E})
        self.assertEqual(sem_csrf.status_code, 403)

        criada = self.client.post(
            self.base, json={"resource": "serra1", "op": OP_E}, headers=self.csrf
        )
        self.assertEqual(criada.status_code, 200, criada.text)
        corpo = criada.json()
        self.assertEqual(corpo["resource"], "SERRA1")
        item = corpo["items"][0]
        self.assertEqual(item["op"], OP_E)
        self.assertTrue(item["fixada"])
        self.assertIsInstance(item["entry_id"], int)
        self.assertEqual(item["posicao"], 1)
        self.assertEqual(
            set(item),
            {"entry_id", "operation_id", "op", "operation", "product", "description",
             "qty", "fixada", "origem_recurso", "posicao"},
        )

        lida = self.client.get(self.base, params={"resource": "SERRA1"})
        self.assertEqual(lida.json(), corpo)

        reordenada = self.client.put(
            self.base,
            json={"resource": "SERRA1", "operation_ids": [item["operation_id"]]},
            headers=self.csrf,
        )
        self.assertEqual(reordenada.status_code, 200, reordenada.text)

        erro = self.client.post(
            self.base, json={"resource": "SERRA1", "op": "Q9999999999"}, headers=self.csrf
        )
        self.assertEqual(erro.status_code, 409)
        self.assertEqual(erro.json()["code"], "fila_manual_op_inexistente")
        self.assertIn("não encontrada", erro.json()["message"])

        removida = self.client.delete(
            f"{self.base}/{item['entry_id']}", params={"resource": "SERRA1"}, headers=self.csrf
        )
        self.assertEqual(removida.status_code, 200, removida.text)
        self.assertEqual(self._vivas(), [])
        de_novo = self.client.delete(
            f"{self.base}/{item['entry_id']}", params={"resource": "SERRA1"}, headers=self.csrf
        )
        self.assertEqual(de_novo.status_code, 404)
        self.assertEqual(de_novo.json()["code"], "fila_manual_entrada_inexistente")


class AreaQueuePermissaoTests(_PostgresCase):
    """Só líder e supervisor ordenam a fila, cada um nas áreas do próprio nível."""

    def setUp(self):
        super().setUp()
        self.db.criar_nivel_personalizado("supervisor_caldeiraria", "Supervisor Caldeiraria", "supervisor")
        self.db.criar_nivel_personalizado("qualidade_teste", "Qualidade", "gestor")
        self.db.criar_usuario("sup.caldeiraria", SENHA, "supervisor_caldeiraria")
        self.db.criar_usuario("qualidade.sandro", SENHA, "qualidade_teste")
        self.db.criar_usuario("gestor.geral", SENHA, "gestor")
        self.db.criar_usuario("diretor", SENHA, "diretoria")
        self.db.criar_usuario("admin.teste", SENHA, "admin")
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        self.app = create_app(settings=settings, database_factory=lambda: self.db)

    def _entrar(self, usuario):
        cliente = TestClient(self.app)
        cliente.__enter__()
        self.addCleanup(cliente.close)
        resposta = cliente.post("/api/v1/auth/login", json={"username": usuario, "password": SENHA})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return cliente, resposta.json()

    def test_supervisor_ordena_so_as_areas_do_seu_nivel(self):
        cliente, sessao = self._entrar("sup.caldeiraria")
        self.assertEqual(sessao["queue_areas"], ["dobra-corte", "usinagem", "serra"])
        for area in ("dobra-corte", "usinagem", "serra"):
            self.assertEqual(cliente.get(f"/api/v1/areas/{area}/queue/resources").status_code, 200, area)
        for area in ("solda", "pintura", "prototipo"):
            negado = cliente.get(f"/api/v1/areas/{area}/queue/resources")
            self.assertEqual(negado.status_code, 403, area)
            self.assertEqual(negado.json()["code"], "area_access_denied")

    def test_admin_ordena_a_fila_de_todas_as_areas(self):
        cliente, sessao = self._entrar("admin.teste")
        self.assertEqual(len(sessao["queue_areas"]), 7)
        self.assertEqual(cliente.get("/api/v1/areas/solda/queue/resources").status_code, 200)

    def test_quem_nao_e_lider_nem_supervisor_so_enxerga_a_area(self):
        for usuario in ("qualidade.sandro", "gestor.geral", "diretor"):
            cliente, sessao = self._entrar(usuario)
            self.assertEqual(sessao["queue_areas"], [], usuario)
            for rota in (
                cliente.get("/api/v1/areas/serra/queue/resources"),
                cliente.get("/api/v1/areas/serra/queue", params={"resource": "SERRA1"}),
            ):
                self.assertEqual(rota.status_code, 403, usuario)
                self.assertEqual(rota.json()["code"], "area_access_denied")
            csrf = {"X-CSRF-Token": cliente.cookies.get("gestor_csrf")}
            negado = cliente.post(
                "/api/v1/areas/serra/queue", json={"resource": "SERRA1", "op": OP_E}, headers=csrf
            )
            self.assertEqual(negado.status_code, 403, usuario)
        self.assertEqual(self._vivas(), [])


if __name__ == "__main__":
    unittest.main()
