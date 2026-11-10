"""Inspeção progressiva do setup (patch da manufatura, 09/11/2026).

Regras em uma frase cada:

* O nível vai de 5 a 1, é guardado por produto + operação e começa em 5.
  A 1ª peça conta como 1 das N (nível 5 = 1ª peça + 4; nível 1 = só ela).
* N nunca passa da quantidade da OP.
* A OP só finaliza depois das N peças medidas.
* OP com as N peças conformes faz a próxima medir 1 a menos (mínimo 1).
* NC numa peça abre RNC (vai para a Decisão de RNC) e o nível não desce.
* NC no meio (ex. 2/5) não avança: a mesma peça é refeita (10/11/2026).
* As boas da inspeção NÃO entram no total (10/11/2026): o operador informa
  todas as boas no Finalizar.
"""

import unittest

from mes.domain.first_piece import FIRST_PIECE_GATE_REQUIRED
from mes.services.first_piece import FirstPieceService
from tests.test_wave6b_gate_setup_qualidade import cenario, finalizar, medidas


BOA = ("12,0", "40,0")
RUIM = ("12,9", "40,0")


def medir(servico, contexto, valores=BOA):
    resultado = servico.registrar_checklist(**contexto, medidas=medidas(*valores))
    assert resultado.ok, resultado.message
    return resultado


def preparar(**kwargs):
    db, fluxo, contexto = cenario("Dobra", **kwargs)
    servico = FirstPieceService(db, "OPERADOR 6B")
    chave = (contexto["operacao"]["produto_codigo"], contexto["operacao"]["numero_operacao"])
    return db, fluxo, contexto, servico, chave


class InspecaoProgressivaTests(unittest.TestCase):
    def test_nivel_5_mede_a_primeira_e_mais_quatro_antes_de_finalizar(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)

        medir(servico, contexto)
        estado = servico.estado(**contexto)
        self.assertEqual((estado["pecas_medidas"], estado["pecas_exigidas"]), (1, 5))
        self.assertFalse(estado["liberado"])
        recusa = finalizar(fluxo, contexto, pecas_boas=9)
        self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)
        self.assertIn("peça 2 de 5", recusa.message)

        for _ in range(4):
            medir(servico, contexto)
        estado = servico.estado(**contexto)
        self.assertEqual((estado["pecas_medidas"], estado["pecas_exigidas"]), (5, 5))
        self.assertTrue(estado["liberado"])

    def test_tela_ja_sabe_o_n_antes_da_primeira_medicao_sem_gravar(self):
        db, fluxo, contexto, servico, chave = preparar(nivel_inspecao=5)
        db.progressive_levels.pop(chave, None)

        estado = servico.estado(**contexto)
        self.assertEqual((estado["pecas_previstas"], estado["pecas_exigidas"]), (5, 0))
        self.assertNotIn(chave, db.progressive_levels)  # só leitura

        db.progressive_levels[chave] = 2
        self.assertEqual(servico.estado(**contexto)["pecas_previstas"], 2)
        medir(servico, contexto)
        db.progressive_levels[chave] = 4  # N já fixado na 1ª medição não muda
        self.assertEqual(servico.estado(**contexto)["pecas_previstas"], 2)

    def test_n_nunca_passa_da_quantidade_da_op(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5, quantidade=3)

        medir(servico, contexto)

        self.assertEqual(servico.estado(**contexto)["pecas_exigidas"], 3)

    def test_nivel_e_lido_por_produto_e_operacao(self):
        db, fluxo, contexto, servico, chave = preparar(nivel_inspecao=5)
        db.progressive_levels[chave] = 2  # OPs anteriores já desceram o nível

        medir(servico, contexto)

        self.assertEqual(servico.estado(**contexto)["pecas_exigidas"], 2)

    def test_op_sem_nc_faz_a_proxima_medir_uma_a_menos_ate_o_minimo_1(self):
        db, fluxo, contexto, servico, chave = preparar(nivel_inspecao=5)
        for _ in range(5):
            medir(servico, contexto)
        self.assertEqual(db.progressive_levels[chave], 4)

        db2, _f, contexto2, servico2, chave2 = preparar(nivel_inspecao=1)
        db2.progressive_levels[chave2] = 1
        medir(servico2, contexto2)
        self.assertEqual(db2.progressive_levels[chave2], 1)

    def test_nc_abre_rnc_para_a_decisao_e_o_nivel_nao_desce(self):
        db, fluxo, contexto, servico, chave = preparar(nivel_inspecao=3)

        medir(servico, contexto)
        nc = medir(servico, contexto, RUIM)
        medir(servico, contexto)

        self.assertFalse(nc.data["conforme"])
        self.assertEqual(len(db.quality_rnc), 1)
        rnc = db.quality_rnc[0]
        self.assertEqual(rnc["primeira_peca_id"], db.first_pieces[0]["id"])
        self.assertEqual(rnc["numero_peca"], 2)
        self.assertIn("Cota 1", rnc["motivo"])
        self.assertTrue(db.first_pieces[0]["inspecao_com_nc"])
        # Fica em 3 até a Qualidade decidir (volta para 5 / fica onde está).
        self.assertEqual(db.progressive_levels[chave], 3)

    def test_interromper_volta_para_a_fila_sem_quantidade_e_inspecao_continua(self):
        # Botão "Interromper OP" / Cancelar do Setup Ferramental (10/11/2026).
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        medir(servico, contexto)
        medir(servico, contexto)

        parou = fluxo.executar("Interromper", **contexto)

        self.assertTrue(parou.ok, parou.message)
        self.assertEqual(parou.data["status"], "Aguardando")
        self.assertEqual(int(parou.data.get("quantidade_boa") or 0), 0)
        self.assertEqual(int(parou.data.get("quantidade_refugo") or 0), 0)

        # Pegou a OP de novo: o Setup volta e a inspeção segue na peça 3/5.
        self.assertTrue(fluxo.executar("Setup", **contexto).ok)
        estado = servico.estado(**contexto)
        self.assertEqual((estado["pecas_medidas"], estado["pecas_exigidas"]), (2, 5))

    def test_interromper_na_fila_e_recusado(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        self.assertTrue(fluxo.executar("Interromper", **contexto).ok)

        self.assertFalse(fluxo.executar("Interromper", **contexto).ok)

    def test_nc_no_meio_refaz_a_mesma_peca(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        medir(servico, contexto)

        nc = medir(servico, contexto, RUIM)

        self.assertEqual(servico.estado(**contexto)["pecas_medidas"], 1)
        self.assertIn("Refaça a peça 2 de 5", nc.message)
        refeita = medir(servico, contexto)
        self.assertIn("Peça 2 de 5 conforme", refeita.message)
        for _ in range(3):
            medir(servico, contexto)
        estado = servico.estado(**contexto)
        self.assertEqual((estado["pecas_medidas"], estado["pecas_exigidas"]), (5, 5))

    def test_boas_da_inspecao_nao_somam_no_total_da_finalizacao(self):
        # Decisão da manufatura (10/11/2026): a medição do setup é conferência
        # de qualidade; o operador informa TODAS as peças boas ao finalizar.
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=2, quantidade=10)
        medir(servico, contexto)
        medir(servico, contexto)

        final = finalizar(fluxo, contexto, pecas_boas=10)

        self.assertTrue(final.ok, final.message)
        self.assertEqual(int(final.data["quantidade_boa"]), 10)
        self.assertEqual(int(final.data["saldo_restante"] or 0), 0)

    def test_finalizar_so_com_a_diferenca_deixa_saldo_pendente(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=2, quantidade=10)
        medir(servico, contexto)
        medir(servico, contexto)

        parcial = finalizar(fluxo, contexto, pecas_boas=8)

        self.assertTrue(parcial.ok, parcial.message)
        self.assertEqual(int(parcial.data["quantidade_boa"]), 8)
        self.assertEqual(int(parcial.data["saldo_restante"]), 2)

    def test_op_pequena_com_inspecao_nao_fica_com_peca_a_mais(self):
        # Caso da OP PCMCY901001 (2 peças, 2 medidas no setup, 2 informadas).
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=2, quantidade=2)
        medir(servico, contexto)
        medir(servico, contexto)

        final = finalizar(fluxo, contexto, pecas_boas=2)

        self.assertTrue(final.ok, final.message)
        self.assertEqual(int(final.data["quantidade_boa"]), 2)
        self.assertEqual(int(final.data["saldo_restante"] or 0), 0)

    # --- Achados do Codex (09/11/2026): envio duplo e janela entre transações ---

    def enviar(self, servico, contexto, vista, valores=BOA):
        return servico.registrar_checklist(**contexto, medidas=medidas(*valores), pecas_registradas=vista)

    def test_envio_duplo_de_peca_nc_abre_uma_rnc_e_conta_uma_vez(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        self.assertTrue(self.enviar(servico, contexto, 0).ok)

        # Clique duplo / 2 abas: os dois envios viram "1 peça medida".
        primeiro = self.enviar(servico, contexto, 1, RUIM)
        segundo = self.enviar(servico, contexto, 1, RUIM)

        self.assertTrue(primeiro.ok, primeiro.message)
        self.assertFalse(segundo.ok)
        self.assertEqual(segundo.code, "primeira_peca_ja_registrada")
        self.assertEqual(len(db.quality_rnc), 1)
        # NC não avança (10/11/2026): continua 1 conforme; a peça 2 é refeita.
        self.assertEqual(db.first_pieces[0]["inspecao_pecas_medidas"], 1)
        self.assertEqual(len(db.progressive_pieces), 2)

    def test_envio_duplo_de_peca_conforme_conta_uma_vez(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        # Duplo na 1ª peça: o segundo não pode virar a peça 2.
        self.assertTrue(self.enviar(servico, contexto, 0).ok)
        repetido = self.enviar(servico, contexto, 0)
        self.assertEqual(repetido.code, "primeira_peca_ja_registrada")
        # Duplo numa peça do meio.
        self.assertTrue(self.enviar(servico, contexto, 1).ok)
        self.assertEqual(self.enviar(servico, contexto, 1).code, "primeira_peca_ja_registrada")

        self.assertEqual(db.first_pieces[0]["inspecao_pecas_medidas"], 2)
        self.assertEqual(len(db.progressive_pieces), 2)

    def test_envio_duplo_da_primeira_peca_nao_conforme_abre_uma_rnc(self):
        # Antes da aprovação a peça reprovada não conta em "medidas"; a senha
        # é o total de medições gravadas, então o 2º envio é recusado.
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        self.assertTrue(self.enviar(servico, contexto, 0, RUIM).ok)
        repetido = self.enviar(servico, contexto, 0, RUIM)
        self.assertEqual(repetido.code, "primeira_peca_ja_registrada")
        self.assertEqual(len(db.quality_rnc), 1)

        # Remedição legítima depois do retrabalho: a tela já viu 1 gravada.
        self.assertTrue(self.enviar(servico, contexto, 1, RUIM).ok)
        self.assertEqual(len(db.quality_rnc), 2)
        self.assertTrue(self.enviar(servico, contexto, 2).ok)
        self.assertEqual(db.first_pieces[0]["inspecao_pecas_medidas"], 1)
        self.assertEqual(servico.estado(**contexto)["pecas_registradas"], 3)

    def test_tela_atrasada_nao_regrava_a_decisao_da_primeira_peca(self):
        # Codex rodada 3: a aba A mede a 1ª peça fora da faixa; a aba B, que
        # ainda via 0 medições, manda cotas boas. B é recusada ANTES de gravar:
        # a peça não vira conforme e o lote continua travado.
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        self.assertTrue(self.enviar(servico, contexto, 0, RUIM).ok)
        antes = dict(db.first_pieces[0])

        atrasada = self.enviar(servico, contexto, 0, BOA)

        self.assertEqual(atrasada.code, "primeira_peca_ja_registrada")
        linha = db.first_pieces[0]
        self.assertNotEqual(linha["status"], "CONFORME")
        self.assertEqual((linha["status"], linha["tentativas"]), (antes["status"], antes["tentativas"]))
        self.assertEqual(linha["inspecao_pecas_exigidas"], antes["inspecao_pecas_exigidas"])
        self.assertFalse(servico.estado(**contexto)["liberado"])
        self.assertEqual(len(db.progressive_pieces), 1)

    def test_aprovar_pela_acao_inspecionar_tambem_exige_as_n_pecas(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        self.assertTrue(servico.registrar_producao(**contexto).ok)

        aprovada = servico.inspecionar(**contexto, resultado="CONFORME")

        self.assertTrue(aprovada.ok, aprovada.message)
        self.assertEqual(db.first_pieces[0]["inspecao_pecas_exigidas"], 5)
        recusa = finalizar(fluxo, contexto, pecas_boas=9)
        self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)

    def test_finalizar_no_meio_da_aprovacao_da_primeira_peca_e_recusado(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=5)
        gravar = servico._gravar_peca_progressiva
        recusas = []

        def finalizar_concorrente(*args, **kwargs):
            # Outro tablet clica Finalizar depois da aprovação da 1ª peça e
            # antes de a peça 1 ser gravada.
            recusas.append(finalizar(fluxo, contexto, pecas_boas=9))
            return gravar(*args, **kwargs)

        servico._gravar_peca_progressiva = finalizar_concorrente
        self.assertTrue(self.enviar(servico, contexto, 0).ok)

        self.assertEqual(len(recusas), 1)
        self.assertFalse(recusas[0].ok)
        self.assertEqual(recusas[0].code, FIRST_PIECE_GATE_REQUIRED)
        self.assertEqual(db.first_pieces[0]["inspecao_pecas_exigidas"], 5)

    def test_primeira_peca_nao_pede_cracha(self):
        db, fluxo, contexto, servico, _ = preparar(nivel_inspecao=1)

        resultado = servico.registrar_checklist(**contexto, medidas=medidas(*BOA))

        self.assertTrue(resultado.ok, resultado.message)
        self.assertTrue(servico.estado(**contexto)["liberado"])
        self.assertEqual(db.listar_autorizacoes_primeira_peca(codigo_op=contexto["op"]), [])


if __name__ == "__main__":
    unittest.main()
