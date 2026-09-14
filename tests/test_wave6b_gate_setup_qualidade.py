"""Wave 6B — o portão Setup/Qualidade no botão Finalizar.

Regra funcional em uma frase: em Dobra, Usinagem e Serra o operador produz
normalmente, mas a operação não fecha antes de o Setup ter sido apontado, a
primeira peça ter sido medida no checklist do produto e o sistema ter
aprovado essa peça.

O que estes testes provam, e que não pode regredir:

* **O Iniciar é livre.** Produzir nunca é bloqueado pelo portão: o operador
  dá Início, produz e aponta o Setup como sempre. O portão aparece no
  Finalizar.
* **Aprovada a primeira peça, o lote inteiro é liberado.** O restante da
  produção segue o apontamento normal do setor — um Início, um Finalizar com
  as quantidades — sem repetir o portão e sem apontamento peça a peça.
* **A regra não mudou, só o momento em que ela é avaliada.** O motor continua
  sendo ``FirstPieceService``/``QualityService``; nenhum estado novo foi
  persistido e nenhuma segunda máquina de estados existe.
* **O escopo é a Caldeiraria.** Solda, Pintura e Corte continuam exatamente
  como estavam: o portão estruturado não se aplica a eles.
* **Fechar o popup nunca aprova nada.** Cancelar não deixa rastro de estado e
  a operação continua sem poder ser finalizada.
* **A conformidade é conta do backend (Wave 5.1).** O operador informa só a
  medida; ``referencia ± margem`` decide, com o limite pertencendo à faixa.
"""

from concurrent.futures import ThreadPoolExecutor
import unittest

from mes.domain.first_piece import (
    FIRST_PIECE_GATE_REQUIRED,
    first_piece_gate_is_structured,
    sector_has_setup,
)
from mes.services.first_piece import FirstPieceService
from mes.services.operator_flow import OperatorFlowService
from tests.fakes import FakeDatabase


COTAS_PADRAO = (
    {"sequencia": 1, "descricao": "Altura", "padrao": "12,0 +/- 0,2"},
    {"sequencia": 2, "descricao": "Largura", "padrao": "40,0 +/- 1,0"},
)

POSTOS = {
    "Dobra": "1303",
    "Usinagem": "Romi D 1000",
    "Serra": "S4220",
    "Solda Aço": "Estação 1",
}

RECURSOS_ROTEIRO = {
    "Dobra": "DOBRA3",
    "Usinagem": "CNC-01",
    "Serra": "SERRA1",
    "Solda Aço": "SOLDA4",
}


def cenario(
    setor="Dobra",
    *,
    quantidade=10,
    com_checklist=True,
    cotas=COTAS_PADRAO,
    setup_apontado=True,
):
    """OP de uma etapa no setor pedido, com o crachá e o checklist do produto."""

    db = FakeDatabase()
    codigo_op = f"OP-6B-{setor.upper()}"
    produto = f"PECA-6B-{setor.upper()}"
    tarefa = db.inserir_tarefa(f"T-6B-{setor.upper()}")
    db.inserir_op_na_tarefa(tarefa, codigo_op, produto, setor, quantidade)
    operacao = {
        "id": 6000 + len(db.catalog_operations),
        "codigo_op": codigo_op,
        "numero_operacao": "20",
        "codigo_recurso": RECURSOS_ROTEIRO[setor],
        "descricao_operacao": setor.upper(),
        "tipo_setor": setor,
        "produto_codigo": produto,
        "produto_descricao": f"Peça de teste {setor}",
        "quantidade": quantidade,
    }
    db.catalog_operations.append(operacao)
    db.cadastrar_operador_apontamento("1", "Iago", fonte="teste")
    db.cadastrar_operador_apontamento(
        "2", "Maria", fonte="teste", autorizador_retrabalho=False
    )
    db.cadastrar_operador_apontamento(
        "SIM99", "Responsável", fonte="teste", autorizador_retrabalho=True
    )
    if com_checklist:
        db.salvar_template_qualidade(produto, list(cotas), produto_descricao=produto)
    contexto = dict(
        op=codigo_op, setor=setor, recurso=POSTOS[setor], operacao=operacao
    )
    fluxo = OperatorFlowService(db, "OPERADOR 6B")
    if setup_apontado and sector_has_setup(setor):
        apontar_setup(fluxo, contexto)
    return db, fluxo, contexto


def apontar_setup(fluxo, contexto):
    """Aponta o Setup pelo botão Setup — a fonte única de `setup_registrado_em`.

    O popup não confirma Setup: quem grava esse fato é o apontamento de estado
    que já existia antes da Wave 6B.
    """

    resultado = fluxo.executar("Setup", **contexto)
    assert resultado.ok, resultado.message
    return resultado


def finalizar(fluxo, contexto, **extra):
    """Finalização do lote: quantidades e crachá, como no posto."""

    dados = {"pecas_boas": 1, "operadores_cracha": ["1"], **extra}
    return fluxo.executar("Finalizado", **contexto, **dados)


def medidas(*valores):
    return [
        {"sequencia": indice, "medida": valor}
        for indice, valor in enumerate(valores, start=1)
    ]


class GateEstruturadoPorSetorTests(unittest.TestCase):
    """Quem tem checklist estruturado é a Caldeiraria — e só ela."""

    def test_iniciar_e_livre_em_dobra_usinagem_e_serra(self):
        """Produzir nunca é bloqueado pelo portão: ele é do Finalizar."""

        for setor in ("Dobra", "Usinagem", "Serra"):
            with self.subTest(setor=setor):
                _db, fluxo, contexto = cenario(setor, setup_apontado=False)

                inicio = fluxo.executar("Início", **contexto)

                self.assertTrue(inicio.ok, inicio.message)
                self.assertEqual(inicio.data["status"], "Em processo")

    def test_finalizar_antes_da_conferencia_manda_apontar_o_setup(self):
        """A recusa é a orientação: quem abre o checklist é o botão Setup."""

        for setor in ("Dobra", "Usinagem", "Serra"):
            with self.subTest(setor=setor):
                _db, fluxo, contexto = cenario(setor, setup_apontado=False)
                fluxo.executar("Início", **contexto)

                recusa = finalizar(fluxo, contexto)

                self.assertFalse(recusa.ok)
                self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)
                self.assertIn("Aponte o Setup", recusa.message)

    def test_finalizar_com_setup_apontado_continua_recusado_ate_a_aprovacao(self):
        for setor in ("Dobra", "Usinagem", "Serra"):
            with self.subTest(setor=setor):
                db, fluxo, contexto = cenario(setor)
                fluxo.executar("Início", **contexto)

                recusa = finalizar(fluxo, contexto)

                self.assertFalse(recusa.ok)
                self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)
                self.assertTrue(recusa.data["primeira_peca"]["gate_estruturado"])
                # A recusa não registra quantidade nenhuma.
                self.assertEqual(int(db.appointments[0]["quantidade_boa"] or 0), 0)

                linha = next(
                    row
                    for row in fluxo.listar_operacoes(
                        contexto["op"], setor, contexto["recurso"]
                    )
                    if row.get("id") == contexto["operacao"]["id"]
                )
                self.assertTrue(linha["exige_gate_primeira_peca"])
                self.assertFalse(linha["pode_finalizar"])

    def test_setor_fora_da_caldeiraria_nao_recebe_este_portao(self):
        db, fluxo, contexto = cenario("Solda Aço", com_checklist=False)
        self.assertFalse(
            first_piece_gate_is_structured("Solda Aço", contexto["operacao"])
        )

        inicio = fluxo.executar("Início", **contexto)

        self.assertTrue(inicio.ok, inicio.message)
        linha = next(
            row
            for row in fluxo.listar_operacoes(
                contexto["op"], "Solda Aço", contexto["recurso"]
            )
            if row.get("id") == contexto["operacao"]["id"]
        )
        self.assertFalse(linha["primeira_peca"]["gate_estruturado"])
        self.assertFalse(linha["exige_gate_primeira_peca"])

    def test_corte_e_pintura_continuam_fora_do_portao_estruturado(self):
        for setor in ("Corte", "Pintura"):
            with self.subTest(setor=setor):
                self.assertFalse(
                    first_piece_gate_is_structured(setor, {"numero_operacao": "20"})
                )


class ChecklistDoPopupTests(unittest.TestCase):
    """O popup carrega o cadastro que já existe; ele não cria um editor novo."""

    def test_checklist_existente_e_carregado_com_os_limites_calculados(self):
        db, _fluxo, contexto = cenario("Dobra")
        estado = FirstPieceService(db, "OPERADOR 6B").estado(**contexto)

        checklist = estado["checklist"]
        self.assertFalse(checklist["configuravel"])
        self.assertEqual(checklist["produto"], "PECA-6B-DOBRA")
        cotas = checklist["template"]["cotas"]
        self.assertEqual([item["sequencia"] for item in cotas], [1, 2])
        self.assertEqual(cotas[0]["unidade"], "mm")
        self.assertEqual(cotas[0]["referencia"], 12.0)
        self.assertEqual(cotas[0]["margem"], 0.2)
        self.assertEqual(cotas[0]["limite_inferior"], 11.8)
        self.assertEqual(cotas[0]["limite_superior"], 12.2)
        self.assertTrue(cotas[0]["conformidade_automatica"])

    def test_checklist_inexistente_fica_configuravel_e_nao_libera_o_lote(self):
        db, fluxo, contexto = cenario("Dobra", com_checklist=False)
        servico = FirstPieceService(db, "OPERADOR 6B")

        estado = servico.estado(**contexto)
        self.assertTrue(estado["checklist"]["configuravel"])
        self.assertIsNone(estado["checklist"]["template"])

        recusa = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0")
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_checklist_ausente")
        fluxo.executar("Início", **contexto)
        self.assertFalse(finalizar(fluxo, contexto).ok)

        # A configuração usa a lógica que já existe na Qualidade.
        db.salvar_template_qualidade("PECA-6B-DOBRA", list(COTAS_PADRAO))
        aprovado = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        self.assertTrue(aprovado.ok, aprovado.message)
        self.assertTrue(finalizar(fluxo, contexto).ok)


class CancelamentoDoPopupTests(unittest.TestCase):
    """Fechar ou cancelar o popup nunca libera a OP."""

    def test_fechar_o_popup_sem_submeter_nao_finaliza_nem_cria_estado(self):
        db, fluxo, contexto = cenario("Dobra")
        fluxo.executar("Início", **contexto)
        # Abrir o popup é leitura: consultar o estado não inspeciona nada.
        FirstPieceService(db, "OPERADOR 6B").estado(**contexto)

        self.assertEqual(db.first_pieces[0]["status"], "PENDENTE")
        self.assertIsNone(db.first_pieces[0]["inspecionada_em"])
        recusa = finalizar(fluxo, contexto)
        self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)
        # A OP continua em processo; nada foi finalizado.
        self.assertEqual(db.appointments[0]["status"], "Em processo")
        self.assertEqual(int(db.appointments[0]["quantidade_boa"] or 0), 0)

    def test_cancelar_apos_abrir_e_medir_sem_submeter_mantem_a_op_em_processo(self):
        db, fluxo, contexto = cenario("Dobra")
        fluxo.executar("Início", **contexto)
        servico = FirstPieceService(db, "OPERADOR 6B")
        # O operador declarou a peça produzida e desistiu antes de medir.
        servico.registrar_producao(**contexto)

        self.assertEqual(len(db.first_pieces), 1)
        self.assertEqual(db.first_pieces[0]["status"], "PRODUZIDA")
        recusa = finalizar(fluxo, contexto)
        self.assertEqual(recusa.code, FIRST_PIECE_GATE_REQUIRED)
        self.assertEqual(db.appointments[0]["status"], "Em processo")
        self.assertFalse(servico.estado(**contexto)["liberado"])


class ConformidadeAutomaticaTests(unittest.TestCase):
    """Wave 5.1 preservada: o operador informa a medida, o sistema decide."""

    def _submeter(self, *valores, setor="Dobra", destino=None):
        db, fluxo, contexto = cenario(setor)
        servico = FirstPieceService(db, "OPERADOR 6B")
        resultado = servico.registrar_checklist(
            **contexto,
            medidas=medidas(*valores),
            destino=destino,
        )
        return db, fluxo, contexto, servico, resultado

    def test_cotas_numericas_decidem_a_conformidade_sem_o_operador(self):
        _db, _fluxo, _contexto, _servico, resultado = self._submeter("12,0", "40,0")

        self.assertTrue(resultado.ok, resultado.message)
        self.assertTrue(resultado.data["conforme"])
        for cota in resultado.data["cotas"]:
            self.assertEqual(cota["status"], "CONFORME")
            self.assertTrue(cota["avaliacao"]["conformidade_calculada"])

    def test_limite_inferior_pertence_a_faixa(self):
        _db, _fluxo, _contexto, _servico, resultado = self._submeter("11,8", "39,0")

        self.assertTrue(resultado.ok, resultado.message)
        self.assertTrue(resultado.data["conforme"])
        self.assertEqual(resultado.data["cotas"][0]["avaliacao"]["limite_inferior"], 11.8)

    def test_limite_superior_pertence_a_faixa(self):
        _db, _fluxo, _contexto, _servico, resultado = self._submeter("12,2", "41,0")

        self.assertTrue(resultado.ok, resultado.message)
        self.assertTrue(resultado.data["conforme"])
        self.assertEqual(resultado.data["cotas"][0]["avaliacao"]["limite_superior"], 12.2)

    def test_medida_fora_da_faixa_e_nao_conforme_e_nao_libera(self):
        db, fluxo, contexto, servico, resultado = self._submeter("12,3", "40,0")

        self.assertTrue(resultado.ok, resultado.message)
        self.assertFalse(resultado.data["conforme"])
        self.assertEqual(resultado.data["cotas"][0]["status"], "NAO_CONFORME")
        self.assertFalse(servico.estado(**contexto)["liberado"])
        self.assertEqual(db.first_pieces[0]["status"], "RETRABALHO")
        self.assertTrue(db.first_pieces[0]["bloqueio_ativo"])

    def test_medicao_invalida_e_recusada_sem_gravar_resultado(self):
        for valores, codigo in (
            (("", "40,0"), "qualidade_medida_ausente"),
            (("doze", "40,0"), "qualidade_status_cota_invalido"),
            (("12,0",), "qualidade_medida_ausente"),
        ):
            with self.subTest(valores=valores):
                db, fluxo, contexto = cenario("Dobra")
                servico = FirstPieceService(db, "OPERADOR 6B")
                recusa = servico.registrar_checklist(
                    **contexto, medidas=medidas(*valores)
                )

                self.assertFalse(recusa.ok)
                self.assertEqual(recusa.code, codigo)
                self.assertEqual(db.first_pieces[0]["status"], "PENDENTE")
                self.assertIsNone(db.first_pieces[0]["inspecionada_em"])
                fluxo.executar("Início", **contexto)
                self.assertFalse(finalizar(fluxo, contexto).ok)

    def test_cota_fora_do_template_e_recusada(self):
        db, _fluxo, contexto = cenario("Dobra")
        recusa = FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto,
            medidas=[
                {"sequencia": 1, "medida": "12,0"},
                {"sequencia": 2, "medida": "40,0"},
                {"sequencia": 9, "medida": "10,0"},
            ],
        )

        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_cota_desconhecida")


class LiberacaoDoLoteTests(unittest.TestCase):
    """Aprovada a primeira peça, o lote é liberado e a produção é normal."""

    def test_primeira_peca_conforme_libera_o_lote_e_a_finalizacao(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=1)
        servico = FirstPieceService(db, "OPERADOR 6B")
        self.assertTrue(fluxo.executar("Início", **contexto).ok)

        aprovado = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        self.assertTrue(aprovado.ok, aprovado.message)
        # Feedback pontual do lote liberado — não um card permanente.
        self.assertIn("Primeira peça aprovada", aprovado.message)
        self.assertIn("Lote liberado", aprovado.message)
        self.assertTrue(aprovado.data["liberado"])
        self.assertEqual(db.first_pieces[0]["status"], "CONFORME")
        self.assertIn("Cota 1: 12,0 mm", db.first_pieces[0]["observacao"])

        final = finalizar(fluxo, contexto)
        self.assertTrue(final.ok, final.message)
        self.assertEqual(db.appointments[0]["status"], "Finalizado")

    def test_sem_o_botao_setup_apontado_o_popup_recusa_liberar_o_lote(self):
        """O popup não confirma Setup: quem grava esse fato é o botão Setup."""

        db, fluxo, contexto = cenario("Dobra", setup_apontado=False)
        servico = FirstPieceService(db, "OPERADOR 6B")

        fluxo.executar("Início", **contexto)
        sem_setup = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        self.assertFalse(sem_setup.ok)
        self.assertEqual(sem_setup.code, "primeira_peca_setup_pendente")
        self.assertIn("botão Setup", sem_setup.message)

        # O botão Setup continua sendo apontamento de estado do posto.
        setup = apontar_setup(fluxo, contexto)
        self.assertEqual(setup.data["status"], "Setup")
        self.assertIsNotNone(db.first_pieces[0]["setup_registrado_em"])

        com_setup = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        self.assertTrue(com_setup.ok, com_setup.message)
        self.assertTrue(finalizar(fluxo, contexto).ok)


class RetrabalhoDaPrimeiraPecaTests(unittest.TestCase):
    """Bloqueio, crachá do responsável designado e reinspeção."""

    def _bloquear(self, setor="Dobra"):
        db, fluxo, contexto = cenario(setor)
        servico = FirstPieceService(db, "OPERADOR 6B")
        servico.registrar_checklist(
            **contexto, medidas=medidas("12,9", "40,0")
        )
        return db, fluxo, contexto, servico

    def test_retrabalho_da_primeira_peca_bloqueia_a_op(self):
        db, fluxo, contexto, _servico = self._bloquear()

        recusa = fluxo.executar("Início", **contexto)

        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_bloqueada")
        self.assertEqual(finalizar(fluxo, contexto).code, "primeira_peca_bloqueada")
        self.assertTrue(db.first_pieces[0]["bloqueio_ativo"])
        self.assertIn(
            "PRIMEIRA_PECA_RETRABALHO",
            [row["tipo"] for row in db.internal_alerts],
        )

    def test_cracha_nao_autorizado_e_recusado_e_o_autorizado_libera_o_fluxo(self):
        db, fluxo, contexto, servico = self._bloquear()

        recusado = servico.autorizar(**contexto, cracha="2")
        self.assertFalse(recusado.ok)
        self.assertEqual(recusado.code, "primeira_peca_cracha_nao_autorizado")
        self.assertTrue(db.first_pieces[0]["bloqueio_ativo"])

        liberado = servico.autorizar(**contexto, cracha="SIM99")
        self.assertTrue(liberado.ok, liberado.message)
        self.assertFalse(db.first_pieces[0]["bloqueio_ativo"])
        # A autorização libera o fluxo, não a qualidade.
        self.assertFalse(servico.estado(**contexto)["liberado"])
        self.assertTrue(fluxo.executar("Início", **contexto).ok)
        self.assertEqual(finalizar(fluxo, contexto).code, FIRST_PIECE_GATE_REQUIRED)

    def test_reinspecao_conforme_apos_a_autorizacao_libera_o_lote(self):
        db, fluxo, contexto, servico = self._bloquear()
        servico.autorizar(**contexto, cracha="SIM99")

        reinspecao = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        self.assertTrue(reinspecao.ok, reinspecao.message)
        self.assertTrue(reinspecao.data["conforme"])
        self.assertEqual(db.first_pieces[0]["status"], "CONFORME")
        self.assertTrue(finalizar(fluxo, contexto).ok)

    def test_refugo_da_primeira_peca_exige_o_cracha_do_responsavel(self):
        """Descartar peça é decisão de responsável, igual ao retrabalho."""

        db, fluxo, contexto = cenario("Dobra")
        servico = FirstPieceService(db, "OPERADOR 6B")

        sem_cracha = servico.registrar_checklist(
            **contexto, medidas=medidas("13,0", "40,0"), destino="REFUGO"
        )
        self.assertFalse(sem_cracha.ok)
        self.assertEqual(sem_cracha.code, "primeira_peca_cracha_obrigatorio")
        self.assertIsNone(db.first_pieces[0]["resultado"])

        nao_autorizado = servico.registrar_checklist(
            **contexto,
            medidas=medidas("13,0", "40,0"),
            destino="REFUGO",
            cracha_responsavel="2",
        )
        self.assertFalse(nao_autorizado.ok)
        self.assertEqual(nao_autorizado.code, "primeira_peca_cracha_nao_autorizado")
        self.assertIsNone(db.first_pieces[0]["resultado"])

        refugada = servico.registrar_checklist(
            **contexto,
            medidas=medidas("13,0", "40,0"),
            destino="REFUGO",
            cracha_responsavel="SIM99",
        )
        self.assertTrue(refugada.ok, refugada.message)
        self.assertEqual(db.first_pieces[0]["status"], "REFUGO")
        # Refugo não bloqueia a OP; o que ele exige é a autorização.
        self.assertFalse(db.first_pieces[0]["bloqueio_ativo"])
        decisoes = [
            (row["ocorrencia"], row["decisao"])
            for row in db.listar_autorizacoes_primeira_peca()
        ]
        self.assertIn(("REFUGO_PRIMEIRA_PECA", "AUTORIZADA"), decisoes)
        self.assertIn(("REFUGO_PRIMEIRA_PECA", "RECUSADA"), decisoes)
        # Refugo não bloqueia produzir; o que ele impede é finalizar.
        self.assertTrue(fluxo.executar("Início", **contexto).ok)
        self.assertEqual(finalizar(fluxo, contexto).code, FIRST_PIECE_GATE_REQUIRED)

        outra = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        self.assertTrue(outra.ok, outra.message)
        self.assertTrue(finalizar(fluxo, contexto).ok)

    def test_refugo_apontado_na_finalizacao_exige_responsavel_autorizado(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=10)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        fluxo.executar("Início", **contexto)

        recusa = fluxo.executar(
            "Finalizado", **contexto, pecas_boas=9, refugo=1, operadores_cracha=["2"]
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "refugo_autorizacao_obrigatoria")

        autorizado = fluxo.executar(
            "Finalizado",
            **contexto,
            pecas_boas=9,
            refugo=1,
            operadores_cracha=["2"],
            cracha_refugo="SIM99",
        )
        self.assertTrue(autorizado.ok, autorizado.message)
        decisoes = [
            (row["ocorrencia"], row["decisao"])
            for row in db.listar_autorizacoes_primeira_peca()
        ]
        self.assertIn(("REFUGO_APONTAMENTO", "AUTORIZADA"), decisoes)
        self.assertIn(("REFUGO_APONTAMENTO", "RECUSADA"), decisoes)

    def test_finalizacao_sem_refugo_nao_pede_responsavel(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=4)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        fluxo.executar("Início", **contexto)

        final = fluxo.executar(
            "Finalizado", **contexto, pecas_boas=4, operadores_cracha=["2"]
        )

        self.assertTrue(final.ok, final.message)
        self.assertEqual(
            [row["ocorrencia"] for row in db.listar_autorizacoes_primeira_peca()], []
        )

    def test_destino_informado_nunca_transforma_nao_conforme_em_aprovada(self):
        db, _fluxo, contexto = cenario("Dobra")
        resultado = FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto,
            medidas=medidas("15,0", "40,0"),
            destino="CONFORME",
        )

        self.assertTrue(resultado.ok, resultado.message)
        self.assertFalse(resultado.data["conforme"])
        self.assertEqual(db.first_pieces[0]["status"], "RETRABALHO")


class RetrabalhoPosteriorTests(unittest.TestCase):
    """§8 preservado: retrabalho depois do lote liberado não é primeira peça."""

    def test_retrabalho_posterior_alerta_e_nao_bloqueia_a_op(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=6)
        servico = FirstPieceService(db, "OPERADOR 6B")
        servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        self.assertTrue(fluxo.executar("Início", **contexto).ok)

        retrabalho = fluxo.executar("Retrabalho", **contexto)

        self.assertTrue(retrabalho.ok, retrabalho.message)
        self.assertIn(
            "RETRABALHO_PECA_POSTERIOR", [row["tipo"] for row in db.internal_alerts]
        )
        self.assertIsNone(servico.bloqueio_ativo(
            op=contexto["op"], setor=contexto["setor"], operacao=contexto["operacao"]
        ))
        self.assertFalse(db.first_pieces[0]["bloqueio_ativo"])


class QuantidadesDoLoteTests(unittest.TestCase):
    """Atendido = Boas + Refugo; Saldo = Planejado - Atendido."""

    def test_refugo_consome_o_planejado_sem_virar_peca_boa(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=10)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        fluxo.executar("Início", **contexto)

        final = fluxo.executar(
            "Finalizado", **contexto, pecas_boas=9, refugo=1, operadores_cracha=["1"]
        )

        self.assertTrue(final.ok, final.message)
        self.assertEqual(int(final.data["quantidade_boa"]), 9)
        self.assertEqual(int(final.data["quantidade_refugo"]), 1)
        self.assertEqual(int(final.data["saldo_restante"] or 0), 0)

    def test_retrabalho_pendente_nao_consome_o_saldo(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=10)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        fluxo.executar("Início", **contexto)

        parcial = fluxo.executar(
            "Finalizado",
            **contexto,
            pecas_boas=6,
            refugo=0,
            retrabalho_quantidade=2,
            operadores_cracha=["1"],
        )

        self.assertTrue(parcial.ok, parcial.message)
        self.assertEqual(parcial.code, "finalizacao_parcial")
        self.assertEqual(int(parcial.data["saldo_restante"]), 4)


class RestanteDoLoteTests(unittest.TestCase):
    """Aprovada a primeira peça, o lote segue o apontamento normal do setor."""

    def test_apos_a_liberacao_o_lote_segue_com_inicio_e_fim_normais(self):
        """Um Início, um Finalizar com as quantidades — sem portão de novo.

        O apontamento de Dobra, Usinagem e Serra nunca foi peça a peça: o
        operador abre a operação, produz o lote e fecha com as quantidades. O
        portão da Wave 6B só condiciona a **primeira** finalização da operação.
        """

        db, fluxo, contexto = cenario("Dobra", quantidade=10)
        fluxo.executar("Início", **contexto)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        # Primeira finalização: parcial, já liberada pelo portão.
        parcial = finalizar(fluxo, contexto, pecas_boas=6)
        self.assertTrue(parcial.ok, parcial.message)
        self.assertEqual(parcial.code, "finalizacao_parcial")
        self.assertEqual(int(parcial.data["saldo_restante"]), 4)

        linha = next(
            row
            for row in fluxo.listar_operacoes(
                contexto["op"], contexto["setor"], contexto["recurso"]
            )
            if row.get("id") == contexto["operacao"]["id"]
        )
        self.assertFalse(linha["exige_gate_primeira_peca"])
        self.assertTrue(linha["pode_finalizar"])

        # Ciclo seguinte do mesmo lote: Início e Finalizar sem portão algum.
        self.assertTrue(fluxo.executar("Início", **contexto).ok)
        final = finalizar(fluxo, contexto, pecas_boas=4)
        self.assertTrue(final.ok, final.message)
        self.assertEqual(db.appointments[0]["status"], "Finalizado")
        self.assertEqual(int(db.appointments[0]["quantidade_boa"]), 10)
        # Uma única primeira peça para a operação inteira.
        self.assertEqual(len(db.first_pieces), 1)

    def test_parada_e_retomada_depois_da_liberacao_nao_reabrem_o_portao(self):
        db, fluxo, contexto = cenario("Dobra", quantidade=4)
        fluxo.executar("Início", **contexto)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        self.assertTrue(
            fluxo.executar("Parada", **contexto, motivo_codigo="0029").ok
        )
        self.assertTrue(fluxo.executar("Retomar", **contexto).ok)

        final = finalizar(fluxo, contexto, pecas_boas=4)
        self.assertTrue(final.ok, final.message)


class IdempotenciaEConcorrenciaTests(unittest.TestCase):
    """Duplo clique, reenvio e corrida produzem uma única transição válida."""

    def test_duplo_clique_em_iniciar_nao_duplica_estado(self):
        db, fluxo, contexto = cenario("Dobra")

        primeiro = fluxo.executar("Início", **contexto)
        segundo = fluxo.executar("Início", **contexto)

        self.assertTrue(primeiro.ok, primeiro.message)
        self.assertFalse(segundo.ok)
        self.assertEqual(segundo.code, "acao_ja_registrada")
        ativos = [
            row for row in db.appointments
            if row.get("status") in {"Em processo", "Parada", "Setup", "Retrabalho"}
        ]
        self.assertEqual(len(ativos), 1)

    def test_duplo_clique_em_finalizar_antes_do_portao_nao_altera_estado(self):
        db, fluxo, contexto = cenario("Dobra")
        fluxo.executar("Início", **contexto)

        recusas = [finalizar(fluxo, contexto) for _ in range(2)]

        self.assertEqual(
            [item.code for item in recusas],
            [FIRST_PIECE_GATE_REQUIRED, FIRST_PIECE_GATE_REQUIRED],
        )
        self.assertEqual(db.appointments[0]["status"], "Em processo")
        self.assertEqual(int(db.appointments[0]["quantidade_boa"] or 0), 0)
        self.assertIsNone(db.first_pieces[0]["inspecionada_em"])

    def test_submissao_repetida_do_checklist_e_idempotente(self):
        db, fluxo, contexto = cenario("Dobra")
        servico = FirstPieceService(db, "OPERADOR 6B")

        primeira = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )
        segunda = servico.registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        self.assertTrue(primeira.ok, primeira.message)
        self.assertTrue(segunda.ok, segunda.message)
        self.assertEqual(segunda.code, "primeira_peca_ja_aprovada")
        self.assertEqual(len(db.first_pieces), 1)
        self.assertEqual(db.first_pieces[0]["status"], "CONFORME")
        self.assertEqual(
            db.first_pieces[0]["inspecionada_em"], primeira.data["registro"]["inspecionada_em"]
        )
        fluxo.executar("Início", **contexto)
        self.assertTrue(finalizar(fluxo, contexto).ok)

    def test_duas_submissoes_simultaneas_produzem_uma_unica_transicao(self):
        db, _fluxo, contexto = cenario("Dobra")
        servico = FirstPieceService(db, "OPERADOR 6B")

        def submeter():
            return servico.registrar_checklist(
                **contexto, medidas=medidas("12,9", "40,0")
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = [item.result() for item in [pool.submit(submeter) for _ in range(2)]]

        # A primeira submissão bloqueia a OP; a segunda não pode inspecionar de
        # novo a mesma peça nem reabrir o bloqueio.
        self.assertEqual(len(db.first_pieces), 1)
        self.assertTrue(db.first_pieces[0]["bloqueio_ativo"])
        self.assertEqual(
            sum(1 for item in resultados if item.ok and item.data.get("cotas")), 1
        )

    def test_duas_finalizacoes_simultaneas_fecham_a_operacao_uma_vez_so(self):
        """Concorrência no Finalizar: uma transição e um desconto de saldo."""

        db, fluxo, contexto = cenario("Dobra", quantidade=2)
        fluxo.executar("Início", **contexto)
        FirstPieceService(db, "OPERADOR 6B").registrar_checklist(
            **contexto, medidas=medidas("12,0", "40,0")
        )

        def concluir():
            return finalizar(fluxo, contexto, pecas_boas=2)

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = [item.result() for item in [pool.submit(concluir) for _ in range(2)]]

        aceitos = [item for item in resultados if item.ok]
        self.assertEqual(len(aceitos), 1, [item.code for item in resultados])
        self.assertEqual(int(db.appointments[0]["quantidade_boa"]), 2)
        self.assertEqual(db.appointments[0]["status"], "Finalizado")

    def test_dois_inicios_simultaneos_geram_um_apontamento(self):
        db, fluxo, contexto = cenario("Dobra")

        def iniciar():
            return fluxo.executar("Início", **contexto, recurso_exclusivo=True)

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = [item.result() for item in [pool.submit(iniciar) for _ in range(2)]]

        self.assertEqual(
            len([item for item in resultados if item.ok]),
            1,
            [item.code for item in resultados],
        )
        ativos = [
            row for row in db.appointments
            if row.get("status") in {"Em processo", "Parada", "Setup", "Retrabalho"}
        ]
        self.assertEqual(len(ativos), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
