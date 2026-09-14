"""Wave 6C — a fila de Corte expõe TAREFA -> PLANO/NESTING -> OP -> PRODUTO.

O que estes testes fixam:

* a tarefa é o pai obrigatório e carrega seus planos já consolidados;
* o plano é a unidade de corte (programa), com suas chapas reais;
* a OP pertence ao plano em que a peça foi aninhada, e traz o produto local;
* "AGUARDANDO CORTE" nunca é confundido com "DISPONÍVEL PARA DESTAQUE";
* a quantidade de chapas e a repetição vêm sempre do SigmaNEST;
* a regra de liberação do Destaque continua sendo a já homologada.

Nenhum comando novo é criado: iniciar/parar/finalizar/destacar continuam os
mesmos. Esta wave é sobre representação, não sobre fluxo.
"""

from __future__ import annotations

from datetime import date, datetime
import unittest

from mes.services.cut import (
    PLAN_STATE_CUTTING,
    PLAN_STATE_DONE,
    PLAN_STATE_HIGHLIGHT_READY,
    PLAN_STATE_WAITING_CUT,
    CutService,
)
from mes.services.production import ProductionService
from tests.fakes import FakeDatabase


LASER = "Laser Ensis 3015"
PLASMA = "Plasma TerraBlade 4"


def _plano(plano_hash, programa, sequencia, repeticao, *, maquina="AMADA_ENSIS", tarefa="ZZT4503"):
    return {
        "plano_hash": plano_hash,
        "codigo_tarefa": tarefa,
        "programa": programa,
        "nome_chapa": f"CHAPA {programa}-{repeticao}",
        "sequencia_nesting": sequencia,
        # Repetição da chapa dentro do programa: é ela que diferencia duas
        # chapas físicas do mesmo nesting.
        "sigmanest_repeat_id": repeticao,
        "material": "A36",
        "espessura": 6.35,
        "maquina_sigmanest": maquina,
        "quantidade_processo": 3,
        "tempo_previsto_segundos": 300,
        "data_programa": date(2026, 9, 1),
        "ativo": True,
    }


def _linha_op(programa, codigo_op, peca, quantidade=4, tarefa="ZZT4503"):
    return {
        "linha_hash": f"{tarefa}|{programa}|{codigo_op}|{peca}",
        "codigo_tarefa": tarefa,
        "programa": programa,
        "codigo_op": codigo_op,
        "id_peca": peca,
        "setor_destino": "Almoxarifado",
        "quantidade": quantidade,
        "ativo": True,
    }


def _op_pcp(codigo_op, produto, descricao, quantidade=4):
    return {
        "codigo_op": codigo_op,
        "produto_codigo": produto,
        "produto_descricao": descricao,
        "quantidade": quantidade,
        "unidade": "UN",
        "ativo": True,
    }


class HierarquiaCorteTests(unittest.TestCase):
    """Tarefa com dois planos; o primeiro com duas chapas do mesmo programa."""

    def setUp(self):
        self.db = FakeDatabase()
        self.tarefa_id = self.db.inserir_tarefa("ZZT4503", material="A36", espessura=6.35)
        self.db.cut_plans.extend([
            _plano("h-001-1", "001", 1, 1),
            _plano("h-001-2", "001", 2, 2),
            _plano("h-002-1", "002", 3, 1),
        ])
        self.db.sigmanest_ops.extend([
            _linha_op("001", "1079689C001", "PECA-A"),
            _linha_op("001", "1079689C002", "PECA-B"),
            _linha_op("002", "1079689C003", "PECA-C"),
        ])
        self.db.pcp_ops.extend([
            _op_pcp("1079689C001", "PNT001", "PRODUTO A"),
            _op_pcp("1079689C002", "PNT002", "PRODUTO B"),
            _op_pcp("1079689C003", "PNT003", "PRODUTO C"),
        ])
        self.corte = CutService(self.db, "Cortador", cutoff_date="2026-01-01")

    # ------------------------------------------------------------------
    def _tarefa(self, servico=None):
        fila = (servico or CutService(
            self.db, "Cortador", cutoff_date="2026-01-01"
        )).listar_fila(LASER)
        self.assertEqual(len(fila), 1, "a tarefa é o pai obrigatório e aparece uma vez")
        return fila[0]

    def _plano_de(self, tarefa, programa):
        plano = next(
            (item for item in tarefa["planos"] if item["programa"] == programa), None
        )
        self.assertIsNotNone(plano, f"plano {programa} ausente na tarefa")
        return plano

    def _cortar(self, plano_hash, *, finalizar=True, maquina=LASER):
        iniciado = self.db.iniciar_apontamento_corte(
            plano_hash, maquina, "Cortador", "2026-01-01",
            data_inicio=datetime(2026, 9, 3, 8, 0),
        )
        self.assertIsNotNone(iniciado, f"{plano_hash} não iniciou")
        if not finalizar:
            return iniciado
        finalizado = self.db.finalizar_apontamento_corte(
            iniciado["id"], "Cortador", data_fim=datetime(2026, 9, 3, 9, 0)
        )
        self.assertIsNotNone(finalizado, f"{plano_hash} não finalizou")
        return finalizado

    # --- 1 a 5: a hierarquia -------------------------------------------
    def test_01_tarefa_com_um_unico_plano(self):
        self.db.cut_plans = [_plano("h-001-1", "001", 1, 1)]
        tarefa = self._tarefa()

        self.assertEqual(tarefa["codigo_tarefa"], "ZZT4503")
        self.assertEqual(tarefa["planos_count"], 1)
        self.assertEqual([item["programa"] for item in tarefa["planos"]], ["001"])

    def test_02_tarefa_com_varios_planos(self):
        tarefa = self._tarefa()

        self.assertEqual(tarefa["planos_count"], 2)
        # Ordenação operacional já existente: o programa ordena numericamente.
        self.assertEqual([item["programa"] for item in tarefa["planos"]], ["001", "002"])
        self.assertEqual([item["ordem"] for item in tarefa["planos"]], [1, 2])

    def test_03_plano_com_uma_unica_op(self):
        plano = self._plano_de(self._tarefa(), "002")

        self.assertEqual([op["codigo_op"] for op in plano["ops"]], ["1079689C003"])

    def test_04_plano_com_varias_ops(self):
        plano = self._plano_de(self._tarefa(), "001")

        self.assertEqual(
            [op["codigo_op"] for op in plano["ops"]],
            ["1079689C001", "1079689C002"],
        )

    def test_05_op_e_produto_associados_no_plano_correto(self):
        tarefa = self._tarefa()

        self.assertEqual(
            [
                (op["codigo_op"], op["produto_codigo"], op["produto_descricao"])
                for op in self._plano_de(tarefa, "001")["ops"]
            ],
            [
                ("1079689C001", "PNT001", "PRODUTO A"),
                ("1079689C002", "PNT002", "PRODUTO B"),
            ],
        )
        self.assertEqual(
            [op["quantidade_op"] for op in self._plano_de(tarefa, "002")["ops"]], [4]
        )
        # A OP do plano 002 não vaza para o plano 001.
        self.assertNotIn(
            "1079689C003",
            [op["codigo_op"] for op in self._plano_de(tarefa, "001")["ops"]],
        )
        self.assertEqual(tarefa["ops_sem_plano"], [])

    # --- 6 a 10: estados do plano --------------------------------------
    def test_06_plano_aguardando_corte(self):
        tarefa = self._tarefa()

        self.assertEqual(self._plano_de(tarefa, "001")["estado"], PLAN_STATE_WAITING_CUT)
        self.assertEqual(self._plano_de(tarefa, "002")["estado"], PLAN_STATE_WAITING_CUT)

    def test_07_plano_em_corte(self):
        self._cortar("h-001-1", finalizar=False)
        tarefa = self._tarefa()

        self.assertEqual(self._plano_de(tarefa, "001")["estado"], PLAN_STATE_CUTTING)
        # O outro plano continua aguardando: o estado é do plano, não da tarefa.
        self.assertEqual(self._plano_de(tarefa, "002")["estado"], PLAN_STATE_WAITING_CUT)

    def test_08_plano_disponivel_para_destaque(self):
        self._cortar("h-001-1")
        self._cortar("h-001-2")
        tarefa = self._tarefa()
        plano = self._plano_de(tarefa, "001")

        self.assertEqual(plano["estado"], PLAN_STATE_HIGHLIGHT_READY)
        self.assertEqual(plano["chapas_disponiveis_destaque"], 2)
        self.assertTrue(plano["libera_destaque"])

    def test_09_plano_finalizado_apos_destacado(self):
        self._cortar("h-001-1")
        self._cortar("h-001-2")
        destaque = ProductionService(self.db, "Destacador")
        for plano_hash in ("h-001-1", "h-001-2"):
            self.assertTrue(
                destaque.registrar_destacando(
                    self.tarefa_id, "ZZT4503", plano_hash=plano_hash
                ).ok
            )
            self.assertTrue(
                destaque.registrar_finalizado(
                    self.tarefa_id, "ZZT4503",
                    operador_identificacao="Destacador",
                    plano_hash=plano_hash,
                ).ok
            )

        plano = self._plano_de(self._tarefa(), "001")
        self.assertEqual(plano["estado"], PLAN_STATE_DONE)
        self.assertEqual(plano["chapas_disponiveis_destaque"], 0)

    def test_10_plano_nao_cortado_nunca_aparece_como_aguardando_destaque(self):
        self._cortar("h-001-1")
        tarefa = self._tarefa()
        plano_parcial = self._plano_de(tarefa, "001")
        plano_intocado = self._plano_de(tarefa, "002")

        # Chapa cortada dentro de um plano ainda pendente não transforma o
        # plano em trabalho do Destaque: ele continua sendo trabalho do Corte.
        self.assertEqual(plano_parcial["estado"], PLAN_STATE_CUTTING)
        self.assertEqual(plano_intocado["estado"], PLAN_STATE_WAITING_CUT)
        self.assertNotEqual(plano_intocado["estado"], PLAN_STATE_HIGHLIGHT_READY)
        # A chapa já cortada permanece visível para o Destaque, pela regra
        # canônica da Wave 3 — sem mudar o estado do plano.
        self.assertEqual(plano_parcial["chapas_disponiveis_destaque"], 1)

    # --- 11 a 14: dados reais do SigmaNEST -----------------------------
    def test_11_quantidade_de_chapas_vem_do_sigmanest(self):
        tarefa = self._tarefa()

        self.assertEqual(self._plano_de(tarefa, "001")["chapas_total"], 2)
        self.assertEqual(self._plano_de(tarefa, "002")["chapas_total"], 1)
        self.assertEqual(tarefa["quantidade_chapas"], 3)

    def test_12_repeticao_preservada(self):
        tarefa = self._tarefa()

        self.assertEqual(self._plano_de(tarefa, "001")["repeticoes"], [1, 2])
        self.assertEqual(
            [chapa["repeticao"] for chapa in self._plano_de(tarefa, "001")["chapas"]],
            [1, 2],
        )

    def test_13_nesting_nao_assume_uma_chapa(self):
        # Quatro chapas do MESMO programa: contar programas daria 1.
        self.db.cut_plans = [
            _plano(f"h-003-{indice}", "003", indice, indice) for indice in range(1, 5)
        ]
        self.db.sigmanest_ops = [_linha_op("003", "1079689C009", "PECA-Z")]
        tarefa = self._tarefa()
        plano = self._plano_de(tarefa, "003")

        self.assertEqual(tarefa["planos_count"], 1)
        self.assertEqual(plano["chapas_total"], 4)
        self.assertEqual(plano["repeticoes"], [1, 2, 3, 4])
        self.assertEqual(len(plano["chapas"]), 4)

    def test_14_tarefa_expansivel_no_read_model(self):
        tarefa = self._tarefa()

        # O contrato entrega a hierarquia inteira: expandir/recolher é decisão
        # local do cliente, sem uma segunda chamada por tarefa.
        self.assertTrue(tarefa["expansivel"])
        self.assertEqual(len(tarefa["planos"]), tarefa["planos_count"])
        for plano in tarefa["planos"]:
            self.assertIn("ops", plano)
            self.assertIn("chapas", plano)
            self.assertIn("estado", plano)

    # --- 15 a 20: o Destaque continua como estava ----------------------
    def test_15_destaque_respeita_a_regra_existente(self):
        destaque = ProductionService(self.db, "Destacador")

        bloqueado = destaque.registrar_destacando(
            self.tarefa_id, "ZZT4503", plano_hash="h-001-1"
        )
        self.assertFalse(bloqueado.ok)
        self.assertEqual(bloqueado.code, "destaque_nao_liberado")

        self._cortar("h-001-1")
        liberado = destaque.registrar_destacando(
            self.tarefa_id, "ZZT4503", plano_hash="h-001-1"
        )
        self.assertTrue(liberado.ok, liberado.message)

    def test_16_tarefa_incompleta_continua_bloqueada(self):
        self._cortar("h-001-1")
        destaque = ProductionService(self.db, "Destacador")

        resultado = destaque.registrar_destacando(self.tarefa_id, "ZZT4503")

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.code, "tarefa_corte_incompleto")

    def test_17_plasma_continua_sem_liberar_destaque(self):
        self.db.cut_plans = [
            _plano("h-p-1", "7041", 1, 1, maquina="MESSER_XPR_300"),
            _plano("h-p-2", "7042", 2, 1, maquina="MESSER_XPR_300"),
        ]
        self.db.sigmanest_ops = [_linha_op("7041", "1079689C004", "PECA-D")]
        self._cortar("h-p-1", maquina=PLASMA)

        fila = CutService(self.db, "Cortador", cutoff_date="2026-01-01").listar_fila(PLASMA)
        plano = next(item for item in fila[0]["planos"] if item["programa"] == "7041")

        self.assertFalse(plano["libera_destaque"])
        self.assertEqual(plano["estado"], PLAN_STATE_DONE)
        self.assertEqual(plano["chapas_disponiveis_destaque"], 0)
        self.assertEqual(self.db.listar_fila_destaque(), [])

    def test_18_laser_ensis_continua_podendo_liberar(self):
        self._cortar("h-001-1")

        fila_destaque = self.db.listar_fila_destaque()

        self.assertEqual(len(fila_destaque), 1)
        self.assertEqual(fila_destaque[0]["codigo_tarefa"], "ZZT4503")
        self.assertEqual(fila_destaque[0]["chapas_disponiveis"], 1)
        self.assertEqual(
            self._plano_de(self._tarefa(), "001")["libera_destaque"], True
        )

    def test_19_idempotencia_preservada(self):
        self._cortar("h-001-1")
        destaque = ProductionService(self.db, "Destacador")
        self.assertTrue(
            destaque.registrar_destacando(
                self.tarefa_id, "ZZT4503", plano_hash="h-001-1"
            ).ok
        )
        self.assertTrue(
            destaque.registrar_finalizado(
                self.tarefa_id, "ZZT4503",
                operador_identificacao="Destacador", plano_hash="h-001-1",
            ).ok
        )

        repetido = destaque.registrar_destacando(
            self.tarefa_id, "ZZT4503", plano_hash="h-001-1"
        )

        self.assertFalse(repetido.ok)
        self.assertEqual(repetido.code, "plano_destaque_duplicado")

    def test_20_historico_preservado(self):
        self._cortar("h-001-1", finalizar=False)
        servico = CutService(self.db, "Cortador", cutoff_date="2026-01-01")
        ativo = next(
            item for item in servico.listar_fila(LASER) if item["status"] == "Em processo"
        )
        servico.finalizar(ativo["apontamento_ids_em_processo"][0])

        tipos = [evento["tipo"] for evento in self.db.events]

        # Os eventos canônicos continuam os mesmos; os rótulos novos vivem só
        # no read model e não reescrevem histórico.
        self.assertIn("corte_nesting_concluido", tipos)
        historico = servico.listar_consulta(maquina=LASER, status="Todos")
        self.assertTrue(historico)
        self.assertTrue(all("planos" in linha for linha in historico))


class SelecaoDePlanoTests(unittest.TestCase):
    """A seleção de plano já existente continua sendo um único comando."""

    def setUp(self):
        self.db = FakeDatabase()
        self.db.inserir_tarefa("ZZT4503", material="A36", espessura=6.35)
        self.db.cut_plans.extend([
            _plano("h-001-1", "001", 1, 1),
            _plano("h-002-1", "002", 2, 1),
        ])
        self.corte = CutService(self.db, "Cortador", cutoff_date="2026-01-01")

    def test_iniciar_respeita_o_plano_escolhido_pelo_operador(self):
        resultado = self.corte.iniciar("h-002-1", LASER)

        self.assertTrue(resultado.ok, resultado.message)
        self.assertEqual(
            [linha["plano_hash"] for linha in self.db.cut_appointments], ["h-002-1"]
        )

    def test_iniciar_sem_escolha_segue_a_ordem_operacional(self):
        fila = self.corte.listar_fila(LASER)

        resultado = self.corte.iniciar(fila[0]["plano_hash"], LASER)

        self.assertTrue(resultado.ok, resultado.message)
        self.assertEqual(
            [linha["plano_hash"] for linha in self.db.cut_appointments], ["h-001-1"]
        )


class OpsLegadasSemProgramaTests(unittest.TestCase):
    """Linhas projetadas antes da Wave 6C não têm programa; nada é adivinhado."""

    def setUp(self):
        self.db = FakeDatabase()
        self.db.inserir_tarefa("ZZT4503", material="A36", espessura=6.35)
        self.db.pcp_ops.append(_op_pcp("1079689C001", "PNT001", "PRODUTO A"))
        self.corte = CutService(self.db, "Cortador", cutoff_date="2026-01-01")

    def test_tarefa_de_plano_unico_atribui_a_op_ao_unico_plano(self):
        self.db.cut_plans.append(_plano("h-001-1", "001", 1, 1))
        linha = _linha_op("001", "1079689C001", "PECA-A")
        linha["programa"] = None
        self.db.sigmanest_ops.append(linha)

        tarefa = self.corte.listar_fila(LASER)[0]

        self.assertEqual(
            [op["codigo_op"] for op in tarefa["planos"][0]["ops"]], ["1079689C001"]
        )
        self.assertEqual(tarefa["ops_sem_plano"], [])

    def test_tarefa_com_varios_planos_nao_adivinha_a_atribuicao(self):
        self.db.cut_plans.extend([
            _plano("h-001-1", "001", 1, 1),
            _plano("h-002-1", "002", 2, 1),
        ])
        linha = _linha_op("001", "1079689C001", "PECA-A")
        linha["programa"] = None
        self.db.sigmanest_ops.append(linha)

        tarefa = self.corte.listar_fila(LASER)[0]

        self.assertEqual([plano["ops"] for plano in tarefa["planos"]], [[], []])
        self.assertEqual(
            [op["codigo_op"] for op in tarefa["ops_sem_plano"]], ["1079689C001"]
        )
        # O contrato plano de OPs da tarefa continua completo.
        self.assertEqual(tarefa["ops_relacionadas"], ["1079689C001"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
