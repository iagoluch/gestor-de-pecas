"""Wave 6D — visão gerencial de acompanhamento da Solda.

O que estes testes fixam:

* a OP de conjunto soldado é localizada pelo roteiro de Solda, com a identidade
  canônica do catálogo (nenhum identificador novo, nenhuma OP duplicada);
* produto/conjunto e máquina/modelo vêm da OP e da operação, sem inferência;
* MODELO ausente não quebra a leitura e não produz estação falsa;
* ESTAÇÃO é dado observado no apontamento real — ausente fica ausente, presente
  é a estação onde a OP realmente passou;
* A VENCER, ATRASADA e FINALIZADA seguem as regras acordadas, e "finalizada" só
  existe com apontamento concluído;
* atraso é acompanhamento: a OP atrasada continua executável pelo posto;
* múltiplas OPs, múltiplas estações e atualização da leitura.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import unittest

from mes.domain.welding import (
    WELDING_STATUS_DONE,
    WELDING_STATUS_DUE,
    WELDING_STATUS_LATE,
    week_bounds,
)
from mes.services.first_piece import FirstPieceService
from mes.services.operator_flow import OperatorFlowService
from mes.services.welding import WeldingManagementService
from tests.fakes import FakeDatabase


# Quinta-feira. A semana desta referência vai de 07/09 a 13/09.
AGORA = datetime(2026, 9, 10, 14, 0, 0)


def _pcp(codigo_op, **valores):
    base = {
        "codigo_op": codigo_op,
        "produto_codigo": f"PROD-{codigo_op}",
        "produto_descricao": f"CONJUNTO SOLDADO {codigo_op}",
        "produto_modelo": None,
        "quantidade": 4,
        "unidade": "UN",
        "ativo": True,
        "data_emissao": None,
        "prazo_entrega": None,
        "inicio_planejado": None,
        "fim_planejado": None,
        "totvs_generated_on": None,
    }
    base.update(valores)
    return base


class SoldaGerencialBase(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self._proximo_id = 6400

    # ------------------------------------------------------------------
    def _op(self, codigo_op, *, recurso="S CEN", operacao="10", setor="Solda", **pcp):
        self.db.pcp_ops.append(_pcp(codigo_op, **pcp))
        self._proximo_id += 1
        linha = {
            "id": self._proximo_id,
            "codigo_op": codigo_op,
            "numero_operacao": operacao,
            "codigo_recurso": recurso,
            "descricao_operacao": "SOLDA CENTRAL 710",
            "recurso_nome": "SOLDA CENTRAL 710",
            "tipo_setor": setor,
            "produto_codigo": f"PROD-{codigo_op}",
            "produto_descricao": f"CONJUNTO SOLDADO {codigo_op}",
            "ordem": int(operacao),
            "ativo": True,
        }
        self.db.catalog_operations.append(linha)
        return linha

    def _apontar(self, operacao, estacao, *, status="Em processo", inicio=None, fim=None):
        """Insere a execução observada sem passar pelo fluxo do operador.

        O objetivo destes testes é a leitura gerencial; o fluxo canônico é
        exercitado à parte, no teste que prova que atraso não bloqueia.
        """

        registro = self.db.enfileirar_apontamento_operacional(
            operacao["codigo_op"], None, None, operacao["tipo_setor"], estacao,
            "OPERADOR 6D", quantidade=1, data_entrada=inicio or AGORA,
            operacao=operacao,
        )
        alvo = next(item for item in self.db.appointments if item["id"] == registro["id"])
        alvo["status"] = status
        alvo["data_inicio"] = inicio or AGORA
        alvo["data_fim"] = fim
        return alvo

    def _ler(self, agora=AGORA):
        servico = WeldingManagementService(self.db, now_func=lambda: agora)
        return servico.acompanhamento()

    def _linhas(self, agora=AGORA):
        return [
            linha
            for grupo in self._ler(agora)["estacoes"]
            for linha in grupo["ops"]
        ]


class LocalizacaoDaOpTests(SoldaGerencialBase):
    def test_localiza_op_de_conjunto_soldado_pelo_roteiro(self):
        self._op("A9716901001")
        linhas = self._linhas()
        self.assertEqual([linha["op"] for linha in linhas], ["A9716901001"])

    def test_op_de_outro_setor_nao_entra_na_visao_de_solda(self):
        self._op("A9716901001", setor="Dobra", recurso="DOBRA3")
        self.assertEqual(self._linhas(), [])

    def test_identidade_da_op_e_a_canonica_do_catalogo(self):
        """``codigo_op`` já é número + item + sequência; nada é recomposto."""

        self._op("A9716901001")
        linha = self._linhas()[0]
        self.assertEqual(linha["op"], "A9716901001")
        self.assertNotIn("id", linha)
        self.assertNotIn("linha_id", linha)

    def test_op_com_duas_soldas_no_roteiro_nao_duplica_a_op(self):
        self._op("A9716901001", operacao="10")
        self._op("A9716901001", operacao="30", recurso="S CAB")
        leitura = self._ler()
        linhas = [linha for grupo in leitura["estacoes"] for linha in grupo["ops"]]
        self.assertEqual(len(linhas), 2, "cada solda do roteiro é uma linha")
        self.assertEqual({linha["op"] for linha in linhas}, {"A9716901001"})
        self.assertEqual(leitura["resumo"]["ops"], 1, "a OP continua sendo uma só")

    def test_op_inativa_no_catalogo_sai_da_visao(self):
        self._op("A9716901001", ativo=False)
        self.assertEqual(self._linhas(), [])


class ProdutoEMaquinaTests(SoldaGerencialBase):
    def test_produto_e_maquina_vem_da_op_e_da_operacao(self):
        self._op("A9716901001", recurso="ROBO P")
        linha = self._linhas()[0]
        self.assertEqual(linha["produto"]["codigo"], "PROD-A9716901001")
        self.assertEqual(linha["produto"]["descricao"], "CONJUNTO SOLDADO A9716901001")
        self.assertEqual(linha["maquina"]["codigo"], "ROBO P")
        self.assertEqual(linha["maquina"]["nome"], "SOLDA CENTRAL 710")

    def test_maquina_sem_nome_publico_mantem_o_codigo_visivel(self):
        linha_roteiro = self._op("A9716901001", recurso="S ART")
        linha_roteiro["recurso_nome"] = None
        linha = self._linhas()[0]
        self.assertEqual(linha["maquina"]["nome"], "S ART")

    def test_duas_ops_de_maquinas_diferentes_nao_se_misturam(self):
        self._op("OP-1", recurso="ROBO S")
        self._op("OP-2", recurso="SMSX")
        por_op = {linha["op"]: linha["maquina"]["codigo"] for linha in self._linhas()}
        self.assertEqual(por_op, {"OP-1": "ROBO S", "OP-2": "SMSX"})


class ModeloTests(SoldaGerencialBase):
    def test_modelo_ausente_nao_gera_erro_nem_valor_inventado(self):
        self._op("A9716901001")
        linha = self._linhas()[0]
        self.assertIsNone(linha["modelo"]["value"])
        self.assertEqual(linha["modelo"]["availability"], "nao_configurado")

    def test_modelo_ausente_nao_produz_estacao_falsa(self):
        """A estação nunca é derivada do modelo nem da máquina."""

        self._op("A9716901001", recurso="ROBO P")
        linha = self._linhas()[0]
        self.assertIsNone(linha["modelo"]["value"])
        self.assertIsNone(linha["estacao"]["value"])

    def test_modelo_informado_aparece_como_valor_real(self):
        self._op("A9716901001", produto_modelo="TRC 710")
        linha = self._linhas()[0]
        self.assertEqual(linha["modelo"]["value"], "TRC 710")
        self.assertEqual(linha["modelo"]["availability"], "disponivel")


class EstacaoObservadaTests(SoldaGerencialBase):
    def test_estacao_ausente_fica_ausente_e_agrupada_sem_estacao(self):
        self._op("A9716901001")
        leitura = self._ler()
        self.assertEqual(len(leitura["estacoes"]), 1)
        grupo = leitura["estacoes"][0]
        self.assertIsNone(grupo["nome"])
        self.assertEqual(grupo["availability"], "sem_registros")
        self.assertIsNone(grupo["ops"][0]["estacao"]["value"])

    def test_estacao_presente_e_a_estacao_realmente_apontada(self):
        operacao = self._op("A9716901001")
        self._apontar(operacao, "Estação 3")
        linha = self._linhas()[0]
        self.assertEqual(linha["estacao"]["value"], "Estação 3")
        self.assertEqual(linha["estacao"]["availability"], "disponivel")

    def test_multiplas_estacoes_aparecem_em_ordem_numerica(self):
        for numero, codigo in ((10, "OP-10"), (2, "OP-02"), (1, "OP-01")):
            operacao = self._op(codigo)
            self._apontar(operacao, f"Estação {numero}")
        nomes = [grupo["nome"] for grupo in self._ler()["estacoes"]]
        self.assertEqual(nomes, ["Estação 1", "Estação 2", "Estação 10"])

    def test_estacao_com_varias_ops_mantem_as_duas_na_mesma_estacao(self):
        primeira = self._op("OP-01")
        segunda = self._op("OP-02")
        self._apontar(primeira, "Estação 4", status="Finalizado", fim=AGORA)
        self._apontar(segunda, "Estação 4")
        grupos = self._ler()["estacoes"]
        self.assertEqual(len(grupos), 1)
        self.assertEqual(grupos[0]["op_count"], 2)
        self.assertEqual({linha["op"] for linha in grupos[0]["ops"]}, {"OP-01", "OP-02"})

    def test_grupo_sem_estacao_vem_depois_das_estacoes_identificadas(self):
        identificada = self._op("OP-01")
        self._apontar(identificada, "Estação 5")
        self._op("OP-02")
        nomes = [grupo["nome"] for grupo in self._ler()["estacoes"]]
        self.assertEqual(nomes, ["Estação 5", None])


class StatusTests(SoldaGerencialBase):
    def test_op_dentro_da_janela_de_prazo_esta_a_vencer(self):
        self._op(
            "OP-01",
            data_emissao=AGORA - timedelta(days=1),
            prazo_entrega=AGORA + timedelta(days=5),
        )
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)
        self.assertEqual(linha["status"]["availability"], "disponivel")

    def test_semana_de_criacao_fechada_sem_apontamento_fica_atrasada(self):
        criacao = AGORA - timedelta(days=14)
        self._op(
            "OP-01",
            data_emissao=criacao,
            prazo_entrega=AGORA + timedelta(days=30),
        )
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_LATE)
        self.assertIn("semana", linha["status"]["reason"].casefold())

    def test_apontamento_na_semana_de_criacao_afasta_o_atraso(self):
        criacao = AGORA - timedelta(days=14)
        operacao = self._op(
            "OP-01",
            data_emissao=criacao,
            prazo_entrega=AGORA + timedelta(days=30),
        )
        inicio, _fim = week_bounds(criacao)
        self._apontar(operacao, "Estação 1", inicio=inicio + timedelta(days=2))
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)

    def test_semana_de_criacao_em_curso_nao_declara_atraso(self):
        """Enquanto a semana corre, a OP ainda pode receber apontamento."""

        self._op(
            "OP-01",
            data_emissao=AGORA - timedelta(days=2),
            prazo_entrega=AGORA + timedelta(days=20),
        )
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)

    def test_janela_de_prazo_vencida_sem_conclusao_fica_atrasada(self):
        self._op(
            "OP-01",
            data_emissao=AGORA - timedelta(days=2),
            prazo_entrega=AGORA - timedelta(days=1),
        )
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_LATE)
        self.assertIn("prazo", linha["status"]["reason"].casefold())

    def test_finalizada_exige_apontamento_concluido(self):
        operacao = self._op(
            "OP-01",
            data_emissao=AGORA - timedelta(days=2),
            prazo_entrega=AGORA + timedelta(days=5),
        )
        self._apontar(operacao, "Estação 2", status="Finalizado", fim=AGORA)
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DONE)
        self.assertEqual(linha["datas"]["fim_real"], AGORA.isoformat())

    def test_fim_planejado_no_passado_nao_finaliza_a_op(self):
        """Data estimada não conclui OP: só o apontamento conclui."""

        self._op("OP-01", fim_planejado=AGORA - timedelta(days=3))
        linha = self._linhas()[0]
        self.assertNotEqual(linha["status"]["value"], WELDING_STATUS_DONE)
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_LATE)

    def test_execucao_em_andamento_nao_finaliza_a_op(self):
        operacao = self._op("OP-01", prazo_entrega=AGORA + timedelta(days=2))
        self._apontar(operacao, "Estação 2", status="Em processo")
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)

    def test_op_sem_base_temporal_fica_sem_estado_com_motivo(self):
        self._op("OP-01")
        linha = self._linhas()[0]
        self.assertIsNone(linha["status"]["value"])
        self.assertEqual(linha["status"]["availability"], "dados_insuficientes")
        self.assertTrue(linha["status"]["reason"])

    def test_fim_planejado_supre_o_prazo_declarando_leitura_parcial(self):
        self._op("OP-01", fim_planejado=AGORA + timedelta(days=4))
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)
        self.assertEqual(linha["status"]["availability"], "parcial")
        self.assertEqual(linha["datas"]["referencia_prazo"]["label"], "Fim planejado")

    def test_resumo_conta_os_tres_estados(self):
        self._op("A-VENCER", prazo_entrega=AGORA + timedelta(days=3))
        self._op("ATRASADA", prazo_entrega=AGORA - timedelta(days=3))
        concluida = self._op("FINALIZADA", prazo_entrega=AGORA + timedelta(days=3))
        self._apontar(concluida, "Estação 1", status="Finalizado", fim=AGORA)
        resumo = self._ler()["resumo"]
        self.assertEqual(resumo["a_vencer"], 1)
        self.assertEqual(resumo["atrasadas"], 1)
        self.assertEqual(resumo["finalizadas"], 1)


class AtrasoNaoBloqueiaTests(SoldaGerencialBase):
    def test_op_atrasada_continua_executavel_pelo_posto(self):
        # SOLDA4 é a etapa de Solda que o roteiro corporativo declara hoje; a
        # estação física continua sendo a escolha do posto.
        operacao = self._op(
            "OP-ATRASADA", recurso="SOLDA4", prazo_entrega=AGORA - timedelta(days=10)
        )
        self.db.cadastrar_operador_apontamento("1", "Iago", fonte="teste")
        self.assertEqual(self._linhas()[0]["status"]["value"], WELDING_STATUS_LATE)

        fluxo = OperatorFlowService(self.db, "OPERADOR 6D")
        contexto = dict(
            op="OP-ATRASADA", setor="Solda", recurso="Estação 7", operacao=operacao
        )
        inicio = fluxo.executar("Início", **contexto)
        self.assertTrue(inicio.ok, inicio.message)
        parada = fluxo.executar(
            "Parada", **contexto, motivo="Aguardando ponte", motivo_codigo="0029"
        )
        self.assertTrue(parada.ok, parada.message)
        retomada = fluxo.executar("Retomar", **contexto)
        self.assertTrue(retomada.ok, retomada.message)

        # O único portão do Finalizar continua sendo o da primeira peça, que já
        # existia antes desta wave. Ele não conhece prazo nem atraso.
        primeira_peca = FirstPieceService(self.db, "OPERADOR 6D")
        produzida = primeira_peca.registrar_producao(**contexto)
        self.assertTrue(produzida.ok, produzida.message)
        inspecionada = primeira_peca.inspecionar(**contexto, resultado="Conforme")
        self.assertTrue(inspecionada.ok, inspecionada.message)
        final = fluxo.executar(
            "Finalizado", **contexto, pecas_boas=1, operadores_cracha=["1"]
        )
        self.assertTrue(final.ok, final.message)

        # A execução do posto realimenta a leitura gerencial: a mesma OP passa a
        # aparecer finalizada, na estação onde realmente foi soldada.
        linha = self._linhas()[0]
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DONE)
        self.assertEqual(linha["estacao"]["value"], "Estação 7")


class AtualizacaoTests(SoldaGerencialBase):
    def test_leitura_seguinte_reflete_o_apontamento_novo(self):
        operacao = self._op("OP-01", prazo_entrega=AGORA + timedelta(days=2))
        primeira = self._linhas()[0]
        self.assertIsNone(primeira["estacao"]["value"])

        self._apontar(operacao, "Estação 6")
        segunda = self._linhas()[0]
        self.assertEqual(segunda["estacao"]["value"], "Estação 6")
        self.assertEqual(segunda["status"]["value"], WELDING_STATUS_DUE)

    def test_visao_sem_op_de_solda_declara_ausencia_de_registros(self):
        leitura = self._ler()
        self.assertEqual(leitura["availability"], "sem_registros")
        self.assertEqual(leitura["estacoes"], [])

    def test_leitura_carrega_o_instante_de_geracao(self):
        self._op("OP-01", prazo_entrega=AGORA + timedelta(days=2))
        self.assertEqual(self._ler()["generated_at"], AGORA.isoformat())


class PivotPorMacroTests(SoldaGerencialBase):
    """O pivô MACRO × prazo conta o que o domínio já classificou."""

    def test_agrupa_ops_do_mesmo_produto_e_cruza_com_o_prazo(self):
        # Duas OPs da mesma MACRO, uma a vencer e uma atrasada, e uma OP de
        # outra MACRO. A contagem tem de seguir exatamente o status da linha.
        self._op("OP-01", produto_descricao="SOLDADO - PLAINA 310",
                 prazo_entrega=AGORA + timedelta(days=2))
        self._op("OP-02", produto_descricao="SOLDADO - PLAINA 310",
                 prazo_entrega=AGORA - timedelta(days=2))
        self._op("OP-03", produto_descricao="SOLDADO - ACOPLAMENTO DRAPPER",
                 prazo_entrega=AGORA + timedelta(days=3))

        macros = {item["nome"]: item for item in self._ler()["macros"]}
        self.assertEqual(set(macros), {"SOLDADO - PLAINA 310", "SOLDADO - ACOPLAMENTO DRAPPER"})

        plaina = macros["SOLDADO - PLAINA 310"]
        self.assertEqual(plaina["a_vencer"], 1)
        self.assertEqual(plaina["atrasadas"], 1)
        self.assertEqual(plaina["total"], 2)

        drapper = macros["SOLDADO - ACOPLAMENTO DRAPPER"]
        self.assertEqual((drapper["a_vencer"], drapper["atrasadas"], drapper["total"]), (1, 0, 1))

    def test_o_pivot_bate_com_o_resumo_que_ja_existia(self):
        self._op("OP-01", prazo_entrega=AGORA + timedelta(days=2))
        self._op("OP-02", prazo_entrega=AGORA - timedelta(days=2))
        leitura = self._ler()
        for chave in ("a_vencer", "atrasadas", "finalizadas", "sem_prazo"):
            self.assertEqual(
                sum(item[chave] for item in leitura["macros"]),
                leitura["resumo"][chave],
                f"o pivô divergiu do resumo em {chave}",
            )

    def test_macro_vem_antes_quando_tem_mais_atraso(self):
        self._op("OP-01", produto_descricao="SEM ATRASO",
                 prazo_entrega=AGORA + timedelta(days=2))
        self._op("OP-02", produto_descricao="COM ATRASO",
                 prazo_entrega=AGORA - timedelta(days=2))
        self.assertEqual(self._ler()["macros"][0]["nome"], "COM ATRASO")

    def test_op_sem_produto_cadastrado_fica_em_grupo_declarado(self):
        self._op("OP-01", produto_codigo=None, produto_descricao=None,
                 prazo_entrega=AGORA + timedelta(days=2))
        macro = self._ler()["macros"][0]
        self.assertIsNone(macro["nome"])
        self.assertEqual(macro["availability"], "nao_configurado")


class ContratoDaFachadaTests(SoldaGerencialBase):
    def test_fachada_expoe_a_visao_sem_filtro_de_periodo(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        self._op("OP-01", prazo_entrega=AGORA + timedelta(days=2))
        fachada = FrontendBackendFacade(self.db, now_func=lambda: AGORA)
        leitura = fachada.solda_gerencial()
        self.assertEqual(leitura["setor"], "Solda")
        self.assertEqual(len(leitura["estacoes"]), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
