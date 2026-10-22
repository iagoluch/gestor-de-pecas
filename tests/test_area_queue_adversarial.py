"""QA adversarial da fila manual por recurso.

Cenários que ``tests/test_area_queue.py`` não cobre: troca de recurso, PUT
hostil, corridas, fronteiras de área/recurso, Solda, Corte/Destaque e a regra
"ordem do líder dispensa o crachá só no recurso fixado".

Mesma regra do arquivo base: PostgreSQL só em schema descartável dentro de
``TEST_DATABASE_URL``; nada escreve no banco REAL.

``expectedFailure`` marca defeito PROVADO e ainda aberto: o teste descreve o
comportamento correto e hoje falha. Quando o código for corrigido o teste vira
"unexpected success" e o marcador deve ser removido.
"""

from __future__ import annotations

from datetime import datetime
from threading import Barrier, Thread
import unittest

from fastapi.testclient import TestClient

from app.core.areas import recursos_da_area
from backend.api.config import WebSettings
from backend.api.main import create_app
from mes.services.manual_queue import ManualQueueError, ManualQueueService
from mes.services.operator_flow import OperatorFlowService
from tests import test_area_queue as base
from tests.helpers import liberar_primeira_peca

SETOR = base.SETOR
ROMI, EUROSTEC = base.ROMI, base.EUROSTEC
OP_A, OP_B, OP_C, OP_F, OP_G, OP_I = base.OP_A, base.OP_B, base.OP_C, base.OP_F, base.OP_G, base.OP_I
OP_D = base.OP_D

# Extras deste arquivo.
E1, E2, E3 = "Q0000000021", "Q0000000022", "Q0000000023"  # só CNC-02
S1, S2 = "Q0000000031", "Q0000000032"  # Solda Aço
SO_CORTE = "Q0000000041"  # único passo: Corte
SOLDA = "Solda Aço"
SENHA = base.SENHA


class _Base(base._PostgresCase):
    def setUp(self):
        super().setUp()
        for codigo in (E1, E2, E3):
            self._seed_op(codigo, [("10", "CNC-02", SETOR)])
        for codigo in (S1, S2):
            self._seed_op(codigo, [("10", "MT NT", SOLDA)])
        self._seed_op(SO_CORTE, [("10", "PLASMA", "Corte")])
        self.est1, self.est2 = (
            next(r for r in recursos_da_area("solda") if r["station"] == nome)
            for nome in ("Estação 1", "Estação 2")
        )
        self.alu1 = next(r for r in recursos_da_area("solda") if r["station"] == "Alumínio 1")

    def _erro(self, recurso, op):
        with self.assertRaises(ManualQueueError) as erro:
            self.fila.adicionar(recurso, op)
        return erro.exception

    def _fila_do_operador(self, setor, posto):
        return [c["op"] for c in OperatorFlowService(self.db, "OPERADOR TESTE").listar_cartoes(setor, posto)["queue"]]

    def _contexto_em(self, codigo_op, setor, posto, numero="10"):
        return dict(
            op=codigo_op, setor=setor, recurso=posto,
            operacao=self._operacao(codigo_op, numero),
        )

    def _iniciar_em(self, codigo_op, setor, posto, numero="10", **extra):
        contexto = self._contexto_em(codigo_op, setor, posto, numero)
        liberar_primeira_peca(self.db, "OPERADOR TESTE", **contexto)
        return OperatorFlowService(self.db, "OPERADOR TESTE").executar("Início", **contexto, **extra)

    def _sql(self, comando, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(comando, params)
            return cursor.fetchall() if cursor.description else None


# ----------------------------------------------------------------------------
# Troca de recurso, renumeração e remoção
# ----------------------------------------------------------------------------
class TrocaDeRecursoTests(_Base):
    def test_puxada_para_b_e_removida_volta_ao_a_sem_bagunçar_as_fixadas_de_a(self):
        for codigo in (E1, E2, E3):
            self.fila.adicionar(self.eurostec_r, codigo)
        self.assertEqual(self._ops(self.eurostec_r)[:3], [E1, E2, E3])

        puxada = self.fila.adicionar(self.romi, E1)["items"][0]
        self.assertEqual(puxada["op"], E1)
        self.assertEqual(puxada["origem_recurso"], EUROSTEC)
        # A sumiu da fila de A; as outras fixadas de A mantêm a ordem relativa.
        self.assertEqual(self._ops(self.eurostec_r)[:2], [E2, E3])
        self.assertNotIn(E1, self._ops(self.eurostec_r))
        # O operador de A enxerga o mesmo.
        self.assertNotIn(E1, self._fila_do_operador(SETOR, EUROSTEC))

        self.fila.remover(self.romi, puxada["entry_id"])
        voltou = self._ops(self.eurostec_r)
        self.assertIn(E1, voltou)
        self.assertEqual(voltou[:2], [E2, E3])  # fixadas de A seguem na frente
        self.assertNotIn(E1, self._ops(self.romi))
        self.assertEqual([(v["codigo_op"], v["recurso"]) for v in self._vivas()],
                         [(E2, "CNC-02"), (E3, "CNC-02")])

    def test_posicoes_de_a_nao_ficam_com_buraco_depois_que_uma_sai_para_b(self):
        for codigo in (E1, E2, E3):
            self.fila.adicionar(self.eurostec_r, codigo)
        self.fila.adicionar(self.romi, E1)
        fixadas = [i for i in self.fila.listar(self.eurostec_r)["items"] if i["fixada"]]
        self.assertEqual([i["op"] for i in fixadas], [E2, E3])
        # Na ESCRITA seguinte a posição é recompactada; a leitura não deve
        # expor 2,3 como se a posição 1 existisse.
        self.fila.adicionar(self.eurostec_r, E1)
        self.assertEqual([v["posicao"] for v in self._vivas() if v["recurso"] == "CNC-02"], [1, 2, 3])

    def test_leitura_apos_finalizar_mostra_posicoes_contiguas(self):
        """Defeito corrigido: a renumeração só acontecia na próxima ESCRITA.

        Entre a finalização da OP da frente e o próximo POST/PUT/DELETE, o GET
        da fila devolve ``posicao`` 2,3 (sem a 1). A ordem está certa; o número
        exposto na API está errado.
        """

        for codigo in (OP_A, OP_B, OP_G):
            self.fila.adicionar(self.romi, codigo)
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        fim = self.flow.executar(
            "Finalizado", **self._contexto(OP_A, ROMI), pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertTrue(fim.ok, fim.message)
        itens = [i for i in self.fila.listar(self.romi)["items"] if i["fixada"]]
        self.assertEqual([i["op"] for i in itens], [OP_B, OP_G])
        self.assertEqual([i["posicao"] for i in itens], [1, 2])

    def test_finalizada_some_da_fila_do_operador_e_as_posicoes_renumeram_na_escrita(self):
        for codigo in (OP_A, OP_B, OP_G):
            self.fila.adicionar(self.romi, codigo)
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        self.flow.executar(
            "Finalizado", **self._contexto(OP_A, ROMI), pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertEqual(self._ops(self.romi)[:2], [OP_B, OP_G])
        self.assertEqual(self._fila_do_operador(SETOR, ROMI)[:2], [OP_B, OP_G])
        self.fila.reordenar(self.romi, [self._id(OP_G), self._id(OP_B)])
        self.assertEqual(
            [(v["codigo_op"], v["posicao"]) for v in self._vivas()], [(OP_G, 1), (OP_B, 2)]
        )
        # A entrada da finalizada foi baixada (não só escondida).
        vivas_de_a = self._sql(
            "SELECT 1 FROM fila_manual_recurso WHERE codigo_op = %s AND removida_em IS NULL",
            (OP_A,),
        )
        self.assertEqual(vivas_de_a, [])

    def test_finalizar_op1_nao_derruba_fixacao_da_etapa_20_da_mesma_op(self):
        # I: etapa 10 (CNC-01) e 20 (CNC-02). Fixa a 10 em Eurostec, termina a 10.
        self.fila.adicionar(self.eurostec_r, OP_I)
        # A 10 foi fixada no Eurostec (não é o recurso natural). Inicia no Eurostec.
        res = self._iniciar_em(OP_I, SETOR, EUROSTEC, numero="10")
        self.assertTrue(res.ok, res.message)
        fim = self.flow.executar(
            "Finalizado", **self._contexto_em(OP_I, SETOR, EUROSTEC, "10"),
            pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertTrue(fim.ok, fim.message)
        # A etapa 20 (Eurostec natural) aparece na fila automática do Eurostec, sem fixação.
        itens = self.fila.listar(self.eurostec_r)["items"]
        da_i = [i for i in itens if i["op"] == OP_I]
        self.assertEqual(len(da_i), 1)
        self.assertFalse(da_i[0]["fixada"])
        self.assertNotIn(OP_I, self._ops(self.romi))

    @property
    def eurostec_r(self):
        return self.eurostec


# ----------------------------------------------------------------------------
# PUT hostil
# ----------------------------------------------------------------------------
class ReordenarHostilTests(_Base):
    def test_id_fixado_em_outro_recurso_e_ignorado_e_nao_e_roubado(self):
        self.fila.adicionar(self.eurostec, OP_C)
        self.fila.adicionar(self.romi, OP_A)
        resposta = self.fila.reordenar(self.romi, [self._id(OP_C), self._id(OP_A)])
        self.assertEqual([v["recurso"] for v in self._vivas() if v["codigo_op"] == OP_C], ["CNC-02"])
        self.assertNotIn(OP_C, [i["op"] for i in resposta["items"]])
        self.assertEqual(self._ops(self.eurostec)[0], OP_C)

    def test_put_vazio_nao_apaga_nem_reordena(self):
        for codigo in (OP_B, OP_G, OP_A):
            self.fila.adicionar(self.romi, codigo)
        antes = self._vivas()
        resposta = self.fila.reordenar(self.romi, [])
        self.assertEqual(self._vivas(), antes)
        self.assertEqual([i["op"] for i in resposta["items"]][:3], [OP_B, OP_G, OP_A])

    def test_put_parcial_mantem_o_resto_na_ordem_anterior_depois_das_dadas(self):
        for codigo in (OP_A, OP_B, OP_G, OP_F):
            self.fila.adicionar(self.romi, codigo)
        self.fila.reordenar(self.romi, [self._id(OP_G)])
        self.assertEqual(
            [(v["codigo_op"], v["posicao"]) for v in self._vivas()],
            [(OP_G, 1), (OP_A, 2), (OP_B, 3), (OP_F, 4)],
        )

    def test_put_duplicados_e_ids_absurdos_nao_estouram(self):
        for codigo in (OP_A, OP_B):
            self.fila.adicionar(self.romi, codigo)
        a, b = self._id(OP_A), self._id(OP_B)
        resposta = self.fila.reordenar(self.romi, [b, b, a, b, 0, -1, 2**62, a])
        self.assertEqual([i["op"] for i in resposta["items"]][:2], [OP_B, OP_A])
        self.assertEqual([v["posicao"] for v in self._vivas()], [1, 2])

    def test_put_com_id_de_op_finalizada_ou_inativa_e_ignorado(self):
        self.fila.adicionar(self.romi, OP_A)
        self.fila.adicionar(self.romi, OP_B)
        self._sql("UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = %s", (OP_A,))
        resposta = self.fila.reordenar(self.romi, [self._id(OP_A), self._id(OP_B)])
        self.assertNotIn(OP_A, [i["op"] for i in resposta["items"]])
        self.assertEqual([v["codigo_op"] for v in self._vivas()], [OP_B])

    def test_put_promove_op_visivel_nao_fixada(self):
        # A está visível (automática) no Romi: pô-la no PUT a fixa.
        resposta = self.fila.reordenar(self.romi, [self._id(OP_G)])
        self.assertEqual(resposta["items"][0]["op"], OP_G)
        self.assertTrue(resposta["items"][0]["fixada"])

    def test_put_nao_move_op_em_execucao_em_outro_recurso_para_este(self):
        # OP_C começou no Eurostec; o id dela no PUT do Romi não pode fixá-la lá.
        self.assertTrue(self._iniciar_em(OP_C, SETOR, EUROSTEC).ok)
        self.fila.reordenar(self.romi, [self._id(OP_C), self._id(OP_A)])
        self.assertEqual([v["codigo_op"] for v in self._vivas()], [OP_A])


# ----------------------------------------------------------------------------
# Corridas
# ----------------------------------------------------------------------------
class CorridasTests(_Base):
    def _correr(self, tarefas, rodadas=1):
        largada, erros = Barrier(len(tarefas)), []

        def trabalhar(tarefa):
            try:
                largada.wait(timeout=10)
                for _ in range(rodadas):
                    tarefa()
            except Exception as erro:  # noqa: BLE001 - o teste afirma que não houve nenhuma
                erros.append(erro)

        threads = [Thread(target=trabalhar, args=(t,)) for t in tarefas]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        return erros

    def test_post_duplo_da_mesma_op_gera_uma_entrada_so(self):
        erros = self._correr(
            [lambda: ManualQueueService(self.db, "L1").adicionar(self.romi, OP_A) for _ in range(4)]
        )
        self.assertEqual(erros, [])
        self.assertEqual([(v["codigo_op"], v["posicao"]) for v in self._vivas()], [(OP_A, 1)])

    def test_post_simultaneo_de_ops_diferentes_nao_repete_nem_pula_posicao(self):
        ops = [OP_A, OP_B, OP_F, OP_G]
        erros = self._correr(
            [lambda c=c: ManualQueueService(self.db, "L1").adicionar(self.romi, c) for c in ops]
        )
        self.assertEqual(erros, [])
        self.assertEqual([v["posicao"] for v in self._vivas()], [1, 2, 3, 4])
        self.assertEqual({v["codigo_op"] for v in self._vivas()}, set(ops))

    def test_mesma_op_puxada_ao_mesmo_tempo_por_dois_recursos_fica_em_um_so(self):
        # Travas por recurso são diferentes: a unicidade tem de vir do índice.
        erros = self._correr(
            [
                lambda: ManualQueueService(self.db, "L1").adicionar(self.romi, OP_C),
                lambda: ManualQueueService(self.db, "L2").adicionar(self.eurostec, OP_C),
            ]
        )
        self.assertEqual(erros, [])
        vivas = [v for v in self._vivas() if v["codigo_op"] == OP_C]
        self.assertEqual(len(vivas), 1)
        # E a fila do operador mostra a OP em exatamente um dos dois postos.
        onde = [p for p in (ROMI, EUROSTEC) if OP_C in self._fila_do_operador(SETOR, p)]
        self.assertEqual(len(onde), 1)

    def test_put_e_delete_simultaneos_nao_deixam_buraco_nem_erro(self):
        for codigo in (OP_A, OP_B, OP_G):
            self.fila.adicionar(self.romi, codigo)
        entrada = self.fila.listar(self.romi)["items"][0]
        ids = [self._id(c) for c in (OP_A, OP_B, OP_G)]
        erros = self._correr(
            [
                lambda: ManualQueueService(self.db, "L1").reordenar(self.romi, list(reversed(ids))),
                lambda: self._remover_ignorando_404(entrada["entry_id"]),
            ]
        )
        self.assertEqual(erros, [])
        posicoes = [v["posicao"] for v in self._vivas()]
        self.assertEqual(posicoes, sorted(set(posicoes)))

    def _remover_ignorando_404(self, entry_id):
        try:
            ManualQueueService(self.db, "L2").remover(self.romi, entry_id)
        except ManualQueueError as erro:
            self.assertEqual(erro.status_code, 404)

    def test_trocas_cruzadas_simultaneas_entre_dois_recursos_nao_dao_deadlock(self):
        """Romi puxa a OP do Eurostec e o Eurostec puxa a do Romi, ao mesmo tempo.

        Cada lado recompacta as posições das próprias entradas (UPDATE com lock
        de linha) antes de fixar a OP do outro (UPSERT na linha do outro): a
        ordem dos locks é cruzada. Só dispara quando cada recurso tem um buraco
        de posição para recompactar.
        """

        id_y, id_x = self._id(OP_A), self._id(OP_C)  # A é do Romi, C é do Eurostec
        erros_total = []
        for _ in range(25):
            self._sql("DELETE FROM fila_manual_recurso")
            for operacao, codigo, recurso in ((id_y, OP_A, "CNC-01"), (id_x, OP_C, "CNC-02")):
                self._sql(
                    "INSERT INTO fila_manual_recurso (catalogo_operacao_id, codigo_op, setor, "
                    "recurso, posicao, criado_por, criado_em) VALUES (%s, %s, %s, %s, 2, 'teste', now())",
                    (operacao, codigo, SETOR, recurso),
                )
            erros_total += self._correr(
                [
                    lambda: ManualQueueService(self.db, "L1").adicionar(self.romi, OP_C),
                    lambda: ManualQueueService(self.db, "L2").adicionar(self.eurostec, OP_A),
                ]
            )
        self.assertEqual([repr(e) for e in erros_total], [])

    def test_inicio_simultaneo_da_mesma_operacao_em_dois_recursos_so_um_vence(self):
        """OP_C puxada para o Romi; operador do Romi e do Eurostec iniciam juntos."""

        self.fila.adicionar(self.romi, OP_C)
        contextos = {
            ROMI: self._contexto_em(OP_C, SETOR, ROMI),
            EUROSTEC: self._contexto_em(OP_C, SETOR, EUROSTEC),
        }
        for contexto in contextos.values():
            liberar_primeira_peca(self.db, "OPERADOR TESTE", **contexto)
        resultados = {}

        def iniciar(posto):
            resultados[posto] = OperatorFlowService(self.db, "OPERADOR TESTE").executar(
                "Início", **contextos[posto]
            )

        erros = self._correr([lambda: iniciar(ROMI), lambda: iniciar(EUROSTEC)])
        self.assertEqual(erros, [])
        em_processo = [
            r for r in self.db.listar_apontamentos_por_op(OP_C) if r["status"] == "Em processo"
        ]
        self.assertEqual(
            len(em_processo), 1,
            f"mesma operação em andamento em {len(em_processo)} recursos: "
            f"{[(p, r.ok, r.code) for p, r in resultados.items()]}",
        )


# ----------------------------------------------------------------------------
# Regras ao puxar
# ----------------------------------------------------------------------------
class RegrasAoPuxarTests(_Base):
    def test_codigo_da_op_e_normalizado(self):
        resposta = self.fila.adicionar(self.romi, f"  {OP_G.lower()} ")
        self.assertEqual(resposta["items"][0]["op"], OP_G)

    def test_op_em_vazio_ou_so_espacos(self):
        self.assertEqual(self._erro(self.romi, "   ").code, "fila_manual_op_invalida")

    def test_corte_nao_e_puxavel(self):
        erro = self._erro(self.romi, SO_CORTE)
        self.assertEqual(erro.status_code, 409)
        self.assertEqual(self._vivas(), [])
        self.assertNotIn(SO_CORTE, self._ops(self.romi))

    def test_op_cuja_proxima_etapa_e_corte_nao_vai_para_usinagem(self):
        self.assertEqual(self._erro(self.romi, OP_D).code, "fila_manual_etapa_anterior_pendente")

    def test_op_ja_finalizada(self):
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        self.flow.executar(
            "Finalizado", **self._contexto(OP_A, ROMI), pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertEqual(self._erro(self.eurostec, OP_A).code, "fila_manual_op_concluida")

    def test_op_parada_ou_em_setup_ou_retrabalho_conta_como_em_execucao(self):
        for estado in ("Parada", "Setup", "Retrabalho"):
            with self.subTest(estado=estado):
                self.assertTrue(self._iniciar(OP_B, ROMI).ok) if estado == "Parada" else None
                self._sql(
                    "UPDATE apontamentos_operacionais SET status = %s WHERE op = %s "
                    "AND status IN ('Em processo','Parada','Setup','Retrabalho')",
                    (estado, OP_B),
                )
                self.assertEqual(self._erro(self.eurostec, OP_B).code, "fila_manual_op_em_execucao")

    def test_aguardando_de_finalizacao_parcial_em_outro_recurso_bloqueia_e_no_mesmo_mantem(self):
        self.assertTrue(self._iniciar(OP_A, ROMI).ok)
        self._sql("UPDATE apontamentos_operacionais SET status = 'Aguardando' WHERE op = %s", (OP_A,))
        self.assertEqual(
            self._erro(self.eurostec, OP_A).code, "fila_manual_op_aguardando_em_outro_recurso"
        )
        self.fila.adicionar(self.romi, OP_G)
        resposta = self.fila.adicionar(self.romi, OP_A)
        self.assertEqual([i["op"] for i in resposta["items"]][:2], [OP_G, OP_A])

    def test_op_fixada_e_depois_desativada_some_e_e_baixada(self):
        self.fila.adicionar(self.romi, OP_A)
        self.fila.adicionar(self.romi, OP_B)
        self._sql("UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = %s", (OP_A,))
        self.assertNotIn(OP_A, self._ops(self.romi))
        self.assertNotIn(OP_A, self._fila_do_operador(SETOR, ROMI))
        self.fila.adicionar(self.romi, OP_G)
        self.assertEqual([(v["codigo_op"], v["posicao"]) for v in self._vivas()], [(OP_B, 1), (OP_G, 2)])

    def test_operacao_inativada_depois_de_fixada_some(self):
        self.fila.adicionar(self.romi, OP_A)
        self._sql("UPDATE catalogo_operacoes_op SET ativo = FALSE WHERE codigo_op = %s", (OP_A,))
        self.assertNotIn(OP_A, self._ops(self.romi))

    def test_op_reativada_nao_ressuscita_entrada_ja_baixada(self):
        self.fila.adicionar(self.romi, OP_A)
        self._sql("UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = %s", (OP_A,))
        self.fila.adicionar(self.romi, OP_B)  # baixa a morta
        self._sql("UPDATE catalogo_pcp_ops SET ativo = TRUE WHERE codigo_op = %s", (OP_A,))
        self.assertEqual(self._ops(self.romi)[0], OP_B)
        self.assertFalse(
            next(i for i in self.fila.listar(self.romi)["items"] if i["op"] == OP_A)["fixada"]
        )


# ----------------------------------------------------------------------------
# Execução do operador
# ----------------------------------------------------------------------------
class ExecucaoAdversarialTests(_Base):
    def test_fixada_em_outro_recurso_continua_exigindo_cracha_no_terceiro(self):
        # OP_C (rota CNC-02) puxada para o Romi. No Romi: sem crachá. Na Fresadora
        # (nem rota, nem fixação): fluxo normal, com confirmação.
        self.fila.adicionar(self.romi, OP_C)
        fresadora = "Fresadora FTV31"
        recusado = self._iniciar_em(OP_C, SETOR, fresadora)
        self.assertFalse(recusado.ok)
        self.assertEqual(recusado.code, "confirmacao_recurso_obrigatoria")
        # E no Romi (o fixado) sem crachá.
        self.assertTrue(self._iniciar_em(OP_C, SETOR, ROMI).ok)

    def test_fixada_aceita_apelido_e_codigo_do_posto(self):
        self.fila.adicionar(self.romi, OP_C)
        res = self._iniciar_em(OP_C, SETOR, "CNC-01")
        self.assertTrue(res.ok, res.message)

    def test_nao_fixada_no_posto_divergente_continua_exigindo_confirmacao(self):
        self.fila.adicionar(self.romi, OP_C)
        self.fila.remover(self.romi, self.fila.listar(self.romi)["items"][0]["entry_id"])
        recusado = self._iniciar_em(OP_C, SETOR, ROMI)
        self.assertFalse(recusado.ok)
        self.assertEqual(recusado.code, "confirmacao_recurso_obrigatoria")

    def test_fixacao_vale_so_para_a_operacao_fixada(self):
        # I: fixa a etapa 10 no Eurostec. A etapa 20 já é do Eurostec, mas segue
        # bloqueada pela etapa anterior pendente.
        self.fila.adicionar(self.eurostec, OP_I)
        res = self._iniciar_em(OP_I, SETOR, EUROSTEC, numero="20")
        self.assertFalse(res.ok)
        self.assertEqual(res.code, "confirmacao_etapa_anterior_obrigatoria")

    def test_inicio_paralelo_com_fixacao_no_recurso_de_origem(self):
        # OP_A (rota Romi) fixada no Eurostec; começa no Eurostec e tenta de novo no Romi.
        self.fila.adicionar(self.eurostec, OP_A)
        self.assertTrue(self._iniciar_em(OP_A, SETOR, EUROSTEC).ok)
        paralelo = OperatorFlowService(self.db, "OPERADOR TESTE").executar(
            "Início", **self._contexto_em(OP_A, SETOR, ROMI)
        )
        self.assertFalse(paralelo.ok)
        ativos = [r for r in self.db.listar_apontamentos_por_op(OP_A) if r["status"] == "Em processo"]
        self.assertEqual([r["maquina"] for r in ativos], [EUROSTEC])

    def test_ao_iniciar_em_outro_posto_a_fixacao_antiga_nao_ressurge_no_posto_original(self):
        self.fila.adicionar(self.romi, OP_C)
        res = self._iniciar_em(OP_C, SETOR, EUROSTEC)  # rota natural, ignora a fixação
        self.assertTrue(res.ok, res.message)
        self.assertNotIn(OP_C, self._fila_do_operador(SETOR, ROMI))
        self.assertNotIn(OP_C, self._ops(self.romi))


# ----------------------------------------------------------------------------
# Equivalência com a ordem antiga
# ----------------------------------------------------------------------------
class SemEntradasOrdemAntigaTests(_Base):
    def test_sem_entradas_a_ordem_e_op_depois_operacao(self):
        for recurso, setor, posto in (
            (self.romi, SETOR, ROMI),
            (self.eurostec, SETOR, EUROSTEC),
            (self.est1, SOLDA, "Estação 1"),
        ):
            cartoes = OperatorFlowService(self.db, "OP").listar_cartoes(setor, posto)["queue"]
            chaves = [
                (str(c.get("op") or ""), str(c.get("numero_operacao") or c.get("operation") or ""))
                for c in cartoes
            ]
            self.assertEqual(chaves, sorted(chaves), posto)
            self.assertTrue(all(not c.get("fixada") for c in cartoes))
            self.assertTrue(all("posicao_manual" not in c for c in cartoes))
            self.assertEqual(
                [i["op"] for i in self.fila.listar(recurso)["items"]],
                [c["op"] for c in cartoes if c.get("catalogo_operacao_id") is not None],
            )

    def test_fixadas_na_frente_e_o_resto_na_ordem_antiga(self):
        self.fila.adicionar(self.romi, OP_G)
        cartoes = OperatorFlowService(self.db, "OP").listar_cartoes(SETOR, ROMI)["queue"]
        resto = [(c["op"], str(c.get("numero_operacao") or "")) for c in cartoes if not c.get("fixada")]
        self.assertEqual(resto, sorted(resto))
        self.assertEqual(cartoes[0]["op"], OP_G)

    def test_remover_a_ultima_fixacao_restaura_exatamente_a_ordem_antiga(self):
        antes = self._ops(self.romi)
        self.fila.adicionar(self.romi, OP_G)
        self.fila.adicionar(self.romi, OP_I)
        for item in [i for i in self.fila.listar(self.romi)["items"] if i["fixada"]]:
            self.fila.remover(self.romi, item["entry_id"])
        self.assertEqual(self._ops(self.romi), antes)


# ----------------------------------------------------------------------------
# Solda
# ----------------------------------------------------------------------------
class SoldaTests(_Base):
    def test_op_apontada_numa_estacao_nao_reaparece_em_outra_por_causa_da_fixacao(self):
        self.fila.adicionar(self.est1, S1)
        self.assertEqual(self._fila_do_operador(SOLDA, "Estação 1")[0], S1)
        res = self._iniciar_em(S1, SOLDA, "Estação 1")
        self.assertTrue(res.ok, res.message)
        for posto in ("Estação 2", "Estação 3", "Estação 9"):
            self.assertNotIn(S1, self._fila_do_operador(SOLDA, posto), posto)
        self.assertNotIn(S1, self._ops(self.est2))
        self.assertNotIn(S1, self._ops(self.est1))  # já em execução, não está mais "na fila"

    def test_op_apontada_sem_fixacao_nao_reaparece_em_outra_estacao_nem_pode_ser_puxada(self):
        res = self._iniciar_em(S2, SOLDA, "Estação 3")
        self.assertTrue(res.ok, res.message)
        self.assertNotIn(S2, self._fila_do_operador(SOLDA, "Estação 4"))
        erro = self._erro(self.est2, S2)
        self.assertEqual(erro.code, "fila_manual_op_em_execucao")

    def test_fixada_numa_estacao_some_das_outras_e_volta_ao_remover(self):
        item = self.fila.adicionar(self.est1, S1)["items"][0]
        self.assertNotIn(S1, self._fila_do_operador(SOLDA, "Estação 2"))
        self.assertNotIn(S1, self._ops(self.est2))
        self.fila.remover(self.est1, item["entry_id"])
        self.assertIn(S1, self._fila_do_operador(SOLDA, "Estação 2"))
        self.assertIn(S1, self._fila_do_operador(SOLDA, "Estação 1"))

    def test_fixada_em_aluminio_some_do_aco_e_aparece_no_aluminio(self):
        self.fila.adicionar(self.alu1, S1)
        self.assertEqual(self._fila_do_operador("Solda Alumínio", "Alumínio 1")[0], S1)
        self.assertNotIn(S1, self._fila_do_operador(SOLDA, "Estação 1"))

    def test_iniciar_na_estacao_fixada_apos_apontada_em_outra_estacao_e_recusado(self):
        self.fila.adicionar(self.est1, S1)
        # Alguém começa a mesma operação na Estação 2 (Solda aceita qualquer posto do setor).
        res2 = self._iniciar_em(S1, SOLDA, "Estação 2")
        if not res2.ok:
            return  # recusa também é aceitável: o importante é não duplicar
        res1 = OperatorFlowService(self.db, "OPERADOR TESTE").executar(
            "Início", **self._contexto_em(S1, SOLDA, "Estação 1")
        )
        self.assertFalse(res1.ok)
        ativos = [r for r in self.db.listar_apontamentos_por_op(S1) if r["status"] == "Em processo"]
        self.assertEqual(len(ativos), 1)

    def test_fixacao_morta_pela_execucao_em_outra_estacao_nao_ressurge_ao_liberar(self):
        """Estação 1 fixada, Estação 2 executa e finaliza: nada volta para a 1."""

        self.fila.adicionar(self.est1, S1)
        res2 = self._iniciar_em(S1, SOLDA, "Estação 2")
        if not res2.ok:
            self.skipTest(f"Solda recusou o início fora da fixação: {res2.code}")
        fim = OperatorFlowService(self.db, "OPERADOR TESTE").executar(
            "Finalizado", **self._contexto_em(S1, SOLDA, "Estação 2"),
            pecas_boas=10, operadores_cracha=["9001"],
        )
        self.assertTrue(fim.ok, fim.message)
        self.assertNotIn(S1, self._fila_do_operador(SOLDA, "Estação 1"))
        self.assertNotIn(S1, self._ops(self.est1))


# ----------------------------------------------------------------------------
# API: áreas, Corte/Destaque, CSRF
# ----------------------------------------------------------------------------
class ApiAdversarialTests(_Base):
    def setUp(self):
        super().setUp()
        for nivel, usuario in (("lider_serra", "lider.serra"), ("lider_dobra_corte", "lider.dc")):
            self.db.criar_nivel_personalizado(nivel, nivel, "lider")
            self.db.criar_usuario(usuario, SENHA, nivel)
        self.settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        self.app = create_app(settings=self.settings, database_factory=lambda: self.db)
        self._clientes = []

    def tearDown(self):
        for cliente in self._clientes:
            cliente.close()
        super().tearDown()

    def _login(self, usuario):
        cliente = TestClient(self.app)
        cliente.__enter__()
        self._clientes.append(cliente)
        resposta = cliente.post("/api/v1/auth/login", json={"username": usuario, "password": SENHA})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        return cliente, {"X-CSRF-Token": cliente.cookies.get("gestor_csrf")}

    def test_resource_de_outra_area_em_todas_as_rotas_e_variacoes_de_caixa_e_espaco(self):
        cliente, csrf = self._login("lider.serra")
        base_url = "/api/v1/areas/serra/queue"
        for recurso in ("CNC-01", "cnc-01", "  CNC-01  ", "Romi D 1000", "romi d 1000", "Estação 1"):
            with self.subTest(recurso=recurso):
                self.assertEqual(cliente.get(base_url, params={"resource": recurso}).status_code, 403)
                self.assertEqual(
                    cliente.post(base_url, json={"resource": recurso, "op": OP_A}, headers=csrf).status_code, 403
                )
                self.assertEqual(
                    cliente.put(base_url, json={"resource": recurso, "operation_ids": []}, headers=csrf).status_code,
                    403,
                )
                self.assertEqual(
                    cliente.delete(f"{base_url}/1", params={"resource": recurso}, headers=csrf).status_code, 403
                )
        self.assertEqual(self._vivas(), [])

    def test_area_certa_com_resource_de_outra_area_e_area_errada_com_resource_certo(self):
        cliente, csrf = self._login("lider.serra")
        # SERRA1 pertence à serra, mas o líder pede pela área usinagem.
        for area in ("usinagem", "dobra-corte", "solda"):
            resposta = cliente.get(f"/api/v1/areas/{area}/queue", params={"resource": "SERRA1"})
            self.assertEqual(resposta.status_code, 403, area)
            self.assertEqual(resposta.json()["code"], "area_access_denied")

    def test_delete_de_entrada_de_outro_recurso_pelo_proprio_recurso_nao_apaga(self):
        item = self.fila.adicionar(self.romi, OP_A)["items"][0]
        cliente, csrf = self._login("lider.serra")
        resposta = cliente.delete(
            f"/api/v1/areas/serra/queue/{item['entry_id']}", params={"resource": "SERRA1"}, headers=csrf
        )
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual([v["codigo_op"] for v in self._vivas()], [OP_A])

    def test_lider_da_serra_pode_puxar_op_de_usinagem_para_a_serra_mas_nao_o_contrario(self):
        cliente, csrf = self._login("lider.serra")
        ok = cliente.post(
            "/api/v1/areas/serra/queue", json={"resource": "SERRA1", "op": OP_A}, headers=csrf
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(ok.json()["items"][0]["origem_recurso"], ROMI)
        negado = cliente.post(
            "/api/v1/areas/serra/queue", json={"resource": "CNC-01", "op": OP_B}, headers=csrf
        )
        self.assertEqual(negado.status_code, 403)

    def test_corte_e_destaque_recusados_na_api(self):
        cliente, csrf = self._login("lider.dc")
        base_url = "/api/v1/areas/dobra-corte/queue"
        listados = cliente.get(f"{base_url}/resources").json()["items"]
        self.assertTrue(listados)
        self.assertFalse(
            [i for i in listados if i["setor"] in ("Corte", "Destaque") or i["resource"] in ("PLASMA", "LASER1")]
        )
        for recurso in ("PLASMA", "plasma", "Plasma TerraBlade 4", "LASER1", "Laser Ensis 3015", "Destaque"):
            with self.subTest(recurso=recurso):
                resposta = cliente.post(base_url, json={"resource": recurso, "op": OP_A}, headers=csrf)
                self.assertEqual(resposta.status_code, 403, resposta.text)
                self.assertEqual(resposta.json()["code"], "area_resource_denied")
                self.assertEqual(cliente.get(base_url, params={"resource": recurso}).status_code, 403)
        self.assertEqual(self._vivas(), [])

    def test_corpo_invalido_vira_422_sem_tocar_o_banco(self):
        cliente, csrf = self._login("lider.serra")
        url = "/api/v1/areas/serra/queue"
        casos = [
            ("post", {"resource": "SERRA1"}),
            ("post", {"resource": "SERRA1", "op": ""}),
            ("post", {"resource": "SERRA1", "op": "X" * 81}),
            ("post", {"resource": "SERRA1", "op": OP_E_SERRA, "extra": 1}),
            ("put", {"resource": "SERRA1", "operation_ids": ["abc"]}),
            ("put", {"resource": "SERRA1", "operation_ids": list(range(501))}),
            ("put", {"resource": "SERRA1"}),
        ]
        for metodo, corpo in casos:
            with self.subTest(metodo=metodo, corpo=str(corpo)[:60]):
                resposta = getattr(cliente, metodo)(url, json=corpo, headers=csrf)
                self.assertEqual(resposta.status_code, 422, resposta.text)
        self.assertEqual(
            cliente.delete(f"{url}/abc", params={"resource": "SERRA1"}, headers=csrf).status_code, 422
        )
        self.assertEqual(self._vivas(), [])

    def test_op_com_byte_nul_vira_erro_de_validacao_e_nao_500(self):
        """DEFEITO (baixo): ``op`` com U+0000 chega ao PostgreSQL e vira HTTP 500.

        ``AddQueueRequest.op`` só limita o tamanho; ``buscar_op_pcp_ativa`` faz
        ``psycopg.DataError`` ("text fields cannot contain NUL"). Esperado: 409/422.
        """

        cliente = TestClient(self.app, raise_server_exceptions=False)
        cliente.__enter__()
        self._clientes.append(cliente)
        cliente.post("/api/v1/auth/login", json={"username": "lider.serra", "password": SENHA})
        csrf = {"X-CSRF-Token": cliente.cookies.get("gestor_csrf")}
        resposta = cliente.post(
            "/api/v1/areas/serra/queue",
            json={"resource": "SERRA1", "op": "Q000" + chr(0) + "0001"},
            headers=csrf,
        )
        self.assertLess(resposta.status_code, 500, resposta.text[:200])

    def test_inteiro_fora_do_bigint_e_id_negativo_nao_viram_500(self):

        cliente = TestClient(self.app, raise_server_exceptions=False)
        cliente.__enter__()
        self._clientes.append(cliente)
        cliente.post("/api/v1/auth/login", json={"username": "lider.serra", "password": SENHA})
        csrf = {"X-CSRF-Token": cliente.cookies.get("gestor_csrf")}
        url = "/api/v1/areas/serra/queue"
        respostas = {
            "delete id gigante": cliente.delete(
                f"{url}/{2**70}", params={"resource": "SERRA1"}, headers=csrf
            ),
            "delete id negativo": cliente.delete(f"{url}/-1", params={"resource": "SERRA1"}, headers=csrf),
            "put id gigante": cliente.put(
                url, json={"resource": "SERRA1", "operation_ids": [2**70]}, headers=csrf
            ),
        }
        for nome, resposta in respostas.items():
            with self.subTest(nome):
                self.assertLess(
                    resposta.status_code, 500, f"{nome}: {resposta.status_code} {resposta.text[:200]}"
                )

    def test_nivel_de_lider_sem_mapa_de_areas_e_barrado_em_todas(self):
        self.db.criar_nivel_personalizado("lider_sem_area", "Lider sem area", "lider")
        self.db.criar_usuario("lider.sem", SENHA, "lider_sem_area")
        cliente, csrf = self._login("lider.sem")
        for area in ("serra", "usinagem", "solda", "dobra-corte", "pintura", "prototipo"):
            self.assertEqual(
                cliente.post(
                    f"/api/v1/areas/{area}/queue", json={"resource": "SERRA1", "op": OP_A}, headers=csrf
                ).status_code,
                403,
                area,
            )
        self.assertEqual(self._vivas(), [])

    def test_put_vazio_pela_api_e_200_e_id_gigante_nao_estoura(self):
        cliente, csrf = self._login("lider.serra")
        url = "/api/v1/areas/serra/queue"
        self.assertEqual(
            cliente.put(url, json={"resource": "SERRA1", "operation_ids": []}, headers=csrf).status_code, 200
        )
        gigante = cliente.put(
            url, json={"resource": "SERRA1", "operation_ids": [2**70, -5, 0]}, headers=csrf
        )
        self.assertEqual(gigante.status_code, 200, gigante.text)

    def test_escritas_exigem_csrf_e_sessao(self):
        cliente, csrf = self._login("lider.serra")
        url = "/api/v1/areas/serra/queue"
        self.assertEqual(cliente.put(url, json={"resource": "SERRA1", "operation_ids": []}).status_code, 403)
        self.assertEqual(cliente.delete(f"{url}/1", params={"resource": "SERRA1"}).status_code, 403)
        anonimo = TestClient(self.app)
        self._clientes.append(anonimo)
        for resposta in (
            anonimo.get(url, params={"resource": "SERRA1"}),
            anonimo.post(url, json={"resource": "SERRA1", "op": OP_A}),
            anonimo.put(url, json={"resource": "SERRA1", "operation_ids": []}),
            anonimo.delete(f"{url}/1", params={"resource": "SERRA1"}),
        ):
            self.assertIn(resposta.status_code, (401, 403))

    def test_resource_vazio_ou_gigante_e_422(self):
        cliente, _ = self._login("lider.serra")
        url = "/api/v1/areas/serra/queue"
        self.assertEqual(cliente.get(url, params={"resource": ""}).status_code, 422)
        self.assertEqual(cliente.get(url).status_code, 422)
        self.assertEqual(cliente.get(url, params={"resource": "A" * 121}).status_code, 422)

    def test_solda_pela_api_recurso_com_acento(self):
        self.db.criar_nivel_personalizado("lider_solda", "Líder Solda", "lider")
        self.db.criar_usuario("lider.solda", SENHA, "lider_solda")
        cliente, csrf = self._login("lider.solda")
        resposta = cliente.post(
            "/api/v1/areas/solda/queue", json={"resource": "estação 1", "op": S1}, headers=csrf
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["items"][0]["op"], S1)
        self.assertEqual([v["recurso"] for v in self._vivas()], ["Estação 1"])


OP_E_SERRA = base.OP_E


if __name__ == "__main__":
    unittest.main()
