"""Wave 5 — primeira peça, autorização por crachá, alertas internos e desenho.

A regra antiga (inspeção obrigatória peça a peça) deixou de ser a principal.
Estes testes provam a nova: a primeira peça é o portão do lote, a aprovação
dela vale para a OP inteira, o retrabalho dela bloqueia a OP até um responsável
designado e o refugo consome saldo sem exigir crachá.
"""

from datetime import datetime, timedelta
import os
import tempfile
import unittest
from pathlib import Path

from mes.domain.first_piece import (
    evaluate_first_piece_gate,
    first_piece_applies,
    normalize_first_piece_result,
    sector_has_setup,
)
from mes.domain.internal_alerts import (
    ALERT_FIRST_PIECE_REWORK,
    ALERT_NEW_ORDER_NEEDED,
    ALERT_REPLACEMENT_NEEDED,
    ALERT_SCRAP,
    RECIPIENT_PCP,
    RECIPIENT_REWORK_RESPONSIBLE,
)
from mes.services.drawings import (
    REASON_NOT_CONFIGURED,
    REASON_NOT_FOUND,
    DrawingLookupService,
    parse_drawing_roots,
)
from mes.services.first_piece import FirstPieceService
from mes.services.operator_flow import OperatorFlowService
from tests.fakes import FakeDatabase


class FirstPieceDomainTests(unittest.TestCase):
    """A regra pura: ordem das pendências e onde o Setup existe."""

    def test_setup_existe_na_caldeiraria_e_nao_em_solda_ou_pintura(self):
        for setor in ("Dobra", "Usinagem", "Serra", "Montagem"):
            self.assertTrue(sector_has_setup(setor), setor)
        for setor in ("Solda Aço", "Pintura", "solda aço", "PINTURA", "Protótipo"):
            self.assertFalse(sector_has_setup(setor), setor)

    def test_inspecao_do_roteiro_e_marco_terminal_ficam_fora_do_portao(self):
        self.assertTrue(first_piece_applies("Dobra", {"numero_operacao": "10"}))
        self.assertFalse(first_piece_applies("Dobra", {"inspecao_qualidade": True}))
        self.assertFalse(first_piece_applies("Dobra", {"marco_terminal": True}))
        for setor in ("Corte", "Destaque", "Qualidade"):
            self.assertFalse(first_piece_applies(setor, {"numero_operacao": "10"}), setor)

    def test_ordem_das_pendencias_do_portao(self):
        pendente = evaluate_first_piece_gate(aplicavel=True, setup_obrigatorio=True)
        self.assertFalse(pendente.liberado)
        self.assertEqual(pendente.code, "primeira_peca_nao_produzida")

        sem_setup = evaluate_first_piece_gate(
            aplicavel=True, status="PRODUZIDA", peca_produzida=True, setup_obrigatorio=True
        )
        self.assertEqual(sem_setup.code, "primeira_peca_setup_pendente")

        sem_inspecao = evaluate_first_piece_gate(
            aplicavel=True,
            status="PRODUZIDA",
            peca_produzida=True,
            setup_obrigatorio=True,
            setup_registrado=True,
        )
        self.assertEqual(sem_inspecao.code, "primeira_peca_inspecao_pendente")

        bloqueada = evaluate_first_piece_gate(
            aplicavel=True,
            status="RETRABALHO",
            peca_produzida=True,
            setup_obrigatorio=True,
            setup_registrado=True,
            bloqueio_ativo=True,
        )
        self.assertEqual(bloqueada.code, "primeira_peca_bloqueada")
        self.assertTrue(bloqueada.bloqueio_ativo)

        liberada = evaluate_first_piece_gate(
            aplicavel=True,
            status="CONFORME",
            peca_produzida=True,
            setup_obrigatorio=True,
            setup_registrado=True,
        )
        self.assertTrue(liberada.liberado)
        self.assertEqual(liberada.pendencias, ())

    def test_operacao_sem_setup_configurado_nao_exige_setup(self):
        gate = evaluate_first_piece_gate(
            aplicavel=True, status="CONFORME", peca_produzida=True, setup_obrigatorio=False
        )
        self.assertTrue(gate.liberado)

    def test_nao_conforme_da_tela_vira_retrabalho(self):
        self.assertEqual(normalize_first_piece_result("Não conforme"), "RETRABALHO")
        self.assertEqual(normalize_first_piece_result("conforme"), "CONFORME")
        self.assertEqual(normalize_first_piece_result("qualquer"), "")


class FirstPieceServiceTests(unittest.TestCase):
    """O ciclo completo no posto, sem exigir setor de Qualidade habilitado."""

    OPERACAO = {
        "id": 77,
        "codigo_op": "OP-PP",
        "numero_operacao": "10",
        "codigo_recurso": "DOBRA1",
        "tipo_setor": "Dobra",
        "produto_codigo": "PECA-PP",
        "quantidade": 10,
    }

    def _servico(self):
        db = FakeDatabase()
        db.cadastrar_operador_apontamento(
            "SIM99", "Responsável da simulação", autorizador_retrabalho=True
        )
        db.cadastrar_operador_apontamento(
            "SIM00", "Crachá não autorizado", autorizador_retrabalho=False
        )
        return db, FirstPieceService(db, "OPERADOR PP")

    def _ciclo_ate_producao(self, servico):
        servico.garantir(
            op="OP-PP", setor="Dobra", recurso="Gasparini", operacao=self.OPERACAO
        )
        return servico.registrar_producao(
            op="OP-PP", setor="Dobra", recurso="Gasparini", operacao=self.OPERACAO
        )

    def test_aprovacao_da_primeira_peca_libera_a_op_inteira(self):
        db, servico = self._servico()
        self.assertTrue(self._ciclo_ate_producao(servico).ok)
        servico.marcar_setup(op="OP-PP", operacao=self.OPERACAO)
        aprovada = servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="CONFORME",
        )
        self.assertTrue(aprovada.ok)
        gate = servico.avaliar_finalizacao(op="OP-PP", setor="Dobra", operacao=self.OPERACAO)
        self.assertTrue(gate.liberado)
        # Uma única linha para a operação inteira: a regra antiga criava uma
        # inspeção por unidade e a Wave 5 proíbe isso explicitamente.
        self.assertEqual(len(db.first_pieces), 1)
        self.assertEqual(db.first_pieces[0]["quantidade_planejada"], 10)

    def test_op_unitaria_segue_a_mesma_regra(self):
        _db, servico = self._servico()
        operacao = {**self.OPERACAO, "id": 78, "quantidade": 1}
        servico.garantir(op="OP-1", setor="Dobra", recurso="Gasparini", operacao=operacao)
        gate = servico.avaliar_finalizacao(op="OP-1", setor="Dobra", operacao=operacao)
        self.assertFalse(gate.liberado)
        servico.registrar_producao(
            op="OP-1", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        servico.marcar_setup(op="OP-1", operacao=operacao)
        servico.inspecionar(
            op="OP-1",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="CONFORME",
        )
        self.assertTrue(
            servico.avaliar_finalizacao(op="OP-1", setor="Dobra", operacao=operacao).liberado
        )

    def test_aprovar_antes_do_setup_e_recusado(self):
        _db, servico = self._servico()
        self._ciclo_ate_producao(servico)
        recusa = servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="CONFORME",
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_setup_pendente")

    def test_retrabalho_bloqueia_e_so_o_responsavel_designado_libera(self):
        db, servico = self._servico()
        self._ciclo_ate_producao(servico)
        servico.marcar_setup(op="OP-PP", operacao=self.OPERACAO)
        retrabalho = servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="RETRABALHO",
        )
        self.assertTrue(retrabalho.ok)
        self.assertEqual(retrabalho.code, "primeira_peca_retrabalho")
        bloqueio = servico.bloqueio_ativo(op="OP-PP", setor="Dobra", operacao=self.OPERACAO)
        self.assertIsNotNone(bloqueio)

        # O alerta nasce com destinatário e notificação pendente; nada é enviado.
        alerta = db.internal_alerts[-1]
        self.assertEqual(alerta["tipo"], ALERT_FIRST_PIECE_REWORK)
        self.assertEqual(alerta["destinatario"], RECIPIENT_REWORK_RESPONSIBLE)
        self.assertEqual(alerta["status_notificacao"], "PENDENTE")
        self.assertEqual(alerta["canal_previsto"], "telegram")

        inexistente = servico.autorizar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            cracha="SIM-NAO-EXISTE",
        )
        self.assertFalse(inexistente.ok)
        self.assertEqual(inexistente.code, "primeira_peca_cracha_invalido")

        nao_autorizado = servico.autorizar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            cracha="SIM00",
        )
        self.assertFalse(nao_autorizado.ok)
        self.assertEqual(nao_autorizado.code, "primeira_peca_cracha_nao_autorizado")

        autorizado = servico.autorizar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            cracha="SIM99",
        )
        self.assertTrue(autorizado.ok)
        self.assertEqual(autorizado.code, "primeira_peca_liberada")

        # Toda tentativa fica auditada, inclusive as recusadas.
        decisoes = [
            (row["decisao"], row["cracha"])
            for row in db.listar_autorizacoes_primeira_peca(codigo_op="OP-PP")
        ]
        self.assertIn(("AUTORIZADA", "SIM99"), decisoes)
        self.assertIn(("RECUSADA", "SIM00"), decisoes)
        self.assertIn(("RECUSADA", "SIM-NAO-EXISTE"), decisoes)
        auditoria = db.listar_autorizacoes_primeira_peca(codigo_op="OP-PP")[0]
        for campo in ("codigo_op", "codigo_recurso", "operador", "ocorrencia", "data_hora"):
            self.assertIsNotNone(auditoria[campo], campo)
        self.assertIsNotNone(auditoria["estado_antes"])
        self.assertIsNotNone(auditoria["estado_depois"])

        # A liberação devolve o fluxo, não a qualidade: o lote ainda espera uma
        # primeira peça conforme.
        gate = servico.avaliar_finalizacao(op="OP-PP", setor="Dobra", operacao=self.OPERACAO)
        self.assertFalse(gate.liberado)
        # Dobra usa o checklist estruturado: a pendência é conferir a peça.
        self.assertEqual(gate.code, "primeira_peca_gate_obrigatorio")
        servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="CONFORME",
        )
        self.assertTrue(
            servico.avaliar_finalizacao(op="OP-PP", setor="Dobra", operacao=self.OPERACAO).liberado
        )

    def test_cracha_inativo_e_recusado(self):
        db, servico = self._servico()
        db.cadastrar_operador_apontamento(
            "SIM55", "Responsável afastado", ativo=False, autorizador_retrabalho=True
        )
        self._ciclo_ate_producao(servico)
        servico.marcar_setup(op="OP-PP", operacao=self.OPERACAO)
        servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="RETRABALHO",
        )
        recusa = servico.autorizar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            cracha="SIM55",
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_cracha_inativo")

    def test_refugo_da_primeira_peca_nao_exige_cracha_e_pede_outra_peca(self):
        db, servico = self._servico()
        self._ciclo_ate_producao(servico)
        servico.marcar_setup(op="OP-PP", operacao=self.OPERACAO)
        refugo = servico.inspecionar(
            op="OP-PP",
            setor="Dobra",
            recurso="Gasparini",
            operacao=self.OPERACAO,
            resultado="REFUGO",
        )
        self.assertTrue(refugo.ok)
        self.assertIsNone(
            servico.bloqueio_ativo(op="OP-PP", setor="Dobra", operacao=self.OPERACAO)
        )
        gate = servico.avaliar_finalizacao(op="OP-PP", setor="Dobra", operacao=self.OPERACAO)
        self.assertFalse(gate.liberado)
        self.assertEqual(gate.code, "primeira_peca_gate_obrigatorio")
        # Nenhuma autorização foi exigida — refugo não é chamado de responsável.
        self.assertEqual(db.listar_autorizacoes_primeira_peca(codigo_op="OP-PP"), [])
        # E o operador consegue produzir outra primeira peça.
        self.assertTrue(
            servico.registrar_producao(
                op="OP-PP", setor="Dobra", recurso="Gasparini", operacao=self.OPERACAO
            ).ok
        )

    def test_solda_finaliza_a_etapa_real_pela_conferencia_simples(self):
        """Regressão: Solda não tinha saída para o portão da primeira peça.

        O posto de Solda não possui Setup nem checklist de cotas, e o único
        caminho do portão nesses setores é ``produzida`` + ``inspecionar`` —
        que é o que a tela agora oferece no Finalizar. Enquanto esse caminho
        não existia, ``pode_finalizar`` ficava permanentemente falso na etapa
        real e o marco terminal era a única linha com o botão liberado.
        """

        db = FakeDatabase()
        tarefa = db.inserir_tarefa("T-SOLDA")
        db.inserir_op_na_tarefa(tarefa, "OP-SOLDA", "PECA", "Solda Aço", 5)
        solda = {
            "id": 10,
            "codigo_op": "OP-SOLDA",
            "numero_operacao": "10",
            "codigo_recurso": "SOLDA1",
            "descricao_operacao": "SOLDA",
            "tipo_setor": "Solda Aço",
            "recurso_tipo_setor": "Solda Aço",
            "produto_codigo": "PECA",
            "quantidade": 5,
        }
        terminal = {
            **solda,
            "id": 99,
            "numero_operacao": "99",
            "codigo_recurso": "ALMOX4",
            "descricao_operacao": "FINALIZADA",
            "tipo_setor": None,
            "recurso_tipo_setor": None,
            "ativo": False,
            "marco_terminal": True,
        }
        db.catalog_operations.extend([solda, terminal])
        db.cadastrar_operador_apontamento("SOLD1", "Soldador")
        flow = OperatorFlowService(db, "OPERADOR SOLDA")
        servico = FirstPieceService(db, "OPERADOR SOLDA")

        self.assertTrue(
            flow.executar(
                "Início", op="OP-SOLDA", setor="Solda Aço", recurso="Estação 6",
                operacao=solda,
            ).ok
        )
        # O marco terminal nunca é o caminho: ele não é apontável e não deve
        # aparecer como alternativa quando a etapa real ainda está presa.
        roteiro = flow.listar_operacoes("OP-SOLDA", "Solda Aço", "Estação 6")
        marco = next(row for row in roteiro if row["numero_operacao"] == "99")
        self.assertFalse(marco["selectable"])
        self.assertFalse(marco["pode_finalizar"])

        self.assertTrue(
            servico.registrar_producao(
                op="OP-SOLDA", setor="Solda Aço", recurso="Estação 6", operacao=solda
            ).ok
        )
        inspecao = servico.inspecionar(
            op="OP-SOLDA", setor="Solda Aço", recurso="Estação 6", operacao=solda,
            resultado="CONFORME",
        )
        self.assertTrue(inspecao.ok)
        self.assertTrue(inspecao.data["liberado"])

        etapa = next(
            row
            for row in flow.listar_operacoes("OP-SOLDA", "Solda Aço", "Estação 6")
            if row["numero_operacao"] == "10"
        )
        self.assertTrue(etapa["pode_finalizar"])
        final = flow.executar(
            "Finalizado", op="OP-SOLDA", setor="Solda Aço", recurso="Estação 6",
            operacao=etapa, pecas_boas=5, operadores_cracha=["SOLD1"],
        )
        self.assertTrue(final.ok, final.message)
        self.assertEqual(
            [row["visual_status"] for row in flow.listar_operacoes("OP-SOLDA", "Solda Aço", "Estação 6")],
            ["done", "done"],
        )

    def test_solda_nao_ganha_setup_artificial(self):
        _db, servico = self._servico()
        operacao = {**self.OPERACAO, "id": 79, "codigo_recurso": "SOLDA4"}
        linha = servico.garantir(
            op="OP-SOLDA", setor="Solda Aço", recurso="Estação 1", operacao=operacao
        )
        self.assertFalse(linha["setup_obrigatorio"])
        servico.registrar_producao(
            op="OP-SOLDA", setor="Solda Aço", recurso="Estação 1", operacao=operacao
        )
        servico.inspecionar(
            op="OP-SOLDA",
            setor="Solda Aço",
            recurso="Estação 1",
            operacao=operacao,
            resultado="CONFORME",
        )
        self.assertTrue(
            servico.avaliar_finalizacao(
                op="OP-SOLDA", setor="Solda Aço", operacao=operacao
            ).liberado
        )


class FirstPieceOperatorFlowTests(unittest.TestCase):
    """O portão dentro do fluxo canônico do operador."""

    def _cenario(self, quantidade=10):
        db = FakeDatabase()
        db.cadastrar_operador_apontamento(
            "SIM99", "Responsável da simulação", autorizador_retrabalho=True
        )
        tarefa = db.inserir_tarefa("T-PP")
        db.inserir_op_na_tarefa(tarefa, "OP-FLUXO", "PECA-PP", "Dobra", quantidade)
        operacao = {
            "id": 90,
            "codigo_op": "OP-FLUXO",
            "numero_operacao": "10",
            "codigo_recurso": "DOBRA1",
            "descricao_operacao": "DOBRA",
            "tipo_setor": "Dobra",
            "produto_codigo": "PECA-PP",
            "produto_descricao": "PECA DE TESTE",
            "quantidade": quantidade,
        }
        db.catalog_operations.append(operacao)
        return db, OperatorFlowService(db, "OPERADOR PP"), operacao

    def _liberar_lote(self, db, servico, operacao, *, com_setup=True):
        primeira = FirstPieceService(db, "OPERADOR PP")
        primeira.registrar_producao(
            op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        if com_setup:
            primeira.marcar_setup(op="OP-FLUXO", operacao=operacao)
        return primeira.inspecionar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="CONFORME",
        )

    def test_finalizar_e_recusado_enquanto_a_primeira_peca_nao_for_validada(self):
        db, servico, operacao = self._cenario()
        # Wave 6B — produzir é livre: o portão aparece só no Finalizar.
        inicio = servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        self.assertTrue(inicio.ok, inicio.message)
        self.assertEqual(len(db.first_pieces), 1)

        # O Setup é apontado pelo botão do posto, como sempre.
        self.assertTrue(
            servico.executar(
                "Setup", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
            ).ok
        )

        recusa = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=10,
            operadores_cracha=["1"],
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_gate_obrigatorio")

    def test_setup_pendente_bloqueia_a_finalizacao_e_o_setup_apontado_libera(self):
        db, servico, operacao = self._cenario()
        primeira = FirstPieceService(db, "OPERADOR PP")
        primeira.registrar_producao(
            op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )

        # Aprovar antes do Setup transformaria o portão em formalidade.
        recusa = primeira.inspecionar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="CONFORME",
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "primeira_peca_setup_pendente")

        # O Setup apontado pelo fluxo canônico satisfaz o portão sozinho: o
        # operador não executa um passo novo só para a primeira peça.
        self.assertTrue(
            servico.executar(
                "Setup", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
            ).ok
        )
        self.assertIsNotNone(db.first_pieces[0]["setup_registrado_em"])

        # Voltar do Setup para a produção é livre: o portão é do Finalizar.
        self.assertTrue(
            servico.executar(
                "Retornar", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
            ).ok
        )
        ainda = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=10,
            operadores_cracha=["1"],
        )
        self.assertFalse(ainda.ok)
        self.assertEqual(ainda.code, "primeira_peca_gate_obrigatorio")

        primeira.inspecionar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="CONFORME",
        )
        final = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=10,
            operadores_cracha=["1"],
        )
        self.assertTrue(final.ok, final.message)

    def test_bloqueio_da_primeira_peca_impede_voltar_a_produzir(self):
        db, servico, operacao = self._cenario()
        servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        primeira = FirstPieceService(db, "OPERADOR PP")
        primeira.registrar_producao(
            op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        primeira.marcar_setup(op="OP-FLUXO", operacao=operacao)
        primeira.inspecionar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="RETRABALHO",
        )

        # Retrabalho e Parada continuam liberados: é com eles que a peça é
        # corrigida enquanto o responsável não chega.
        self.assertTrue(
            servico.executar(
                "Retrabalho",
                op="OP-FLUXO",
                setor="Dobra",
                recurso="Gasparini",
                operacao=operacao,
            ).ok
        )
        bloqueado = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=10,
            operadores_cracha=["1"],
        )
        self.assertFalse(bloqueado.ok)
        self.assertEqual(bloqueado.code, "primeira_peca_bloqueada")

        primeira.autorizar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            cracha="SIM99",
        )
        primeira.inspecionar(
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            resultado="CONFORME",
        )
        liberado = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=10,
            operadores_cracha=["1"],
        )
        self.assertTrue(liberado.ok, liberado.message)

    def test_refugo_fecha_saldo_e_gera_reposicao_e_nova_op(self):
        """Planejado 10, boas 9, refugo 1 → atendido 10, saldo 0, nova OP = 1."""

        db, servico, operacao = self._cenario(quantidade=10)
        # Wave 6B — em Dobra o Iniciar só é aceito depois do portão
        # Setup/Qualidade; o lote é liberado antes de a produção começar.
        self._liberar_lote(db, servico, operacao)
        servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        final = servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=9,
            refugo=1,
            operadores_cracha=["1"],
        )
        self.assertTrue(final.ok, final.message)
        apontamento = final.data or {}
        self.assertEqual(int(apontamento.get("quantidade_boa") or 0), 9)
        self.assertEqual(int(apontamento.get("quantidade_refugo") or 0), 1)
        self.assertEqual(int(apontamento.get("saldo_restante") or 0), 0)

        tipos = [row["tipo"] for row in db.internal_alerts]
        self.assertIn(ALERT_SCRAP, tipos)
        self.assertIn(ALERT_REPLACEMENT_NEEDED, tipos)
        self.assertIn(ALERT_NEW_ORDER_NEEDED, tipos)
        nova_op = next(row for row in db.internal_alerts if row["tipo"] == ALERT_NEW_ORDER_NEEDED)
        self.assertEqual(nova_op["quantidade"], 1)
        self.assertEqual(nova_op["destinatario"], RECIPIENT_PCP)
        self.assertEqual(nova_op["status_notificacao"], "PENDENTE")

    def test_lote_sem_refugo_nao_pede_reposicao(self):
        db, servico, operacao = self._cenario(quantidade=4)
        # Wave 6B — em Dobra o Iniciar só é aceito depois do portão
        # Setup/Qualidade; o lote é liberado antes de a produção começar.
        self._liberar_lote(db, servico, operacao)
        servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        servico.executar(
            "Finalizado",
            op="OP-FLUXO",
            setor="Dobra",
            recurso="Gasparini",
            operacao=operacao,
            pecas_boas=4,
            operadores_cracha=["1"],
        )
        tipos = [row["tipo"] for row in db.internal_alerts]
        self.assertNotIn(ALERT_REPLACEMENT_NEEDED, tipos)
        self.assertNotIn(ALERT_NEW_ORDER_NEEDED, tipos)

    def test_retrabalho_posterior_alerta_e_nao_bloqueia(self):
        db, servico, operacao = self._cenario(quantidade=6)
        # Wave 6B — em Dobra o Iniciar só é aceito depois do portão
        # Setup/Qualidade; o lote é liberado antes de a produção começar.
        self._liberar_lote(db, servico, operacao)
        servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        retrabalho = servico.executar(
            "Retrabalho", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        self.assertTrue(retrabalho.ok)
        self.assertIn("RETRABALHO_PECA_POSTERIOR", [row["tipo"] for row in db.internal_alerts])
        # A OP não fica bloqueada: o fluxo segue pelas regras operacionais.
        self.assertIsNone(
            FirstPieceService(db, "OPERADOR PP").bloqueio_ativo(
                op="OP-FLUXO", setor="Dobra", operacao=operacao
            )
        )

    def test_roteiro_publica_o_portao_para_a_tela(self):
        db, servico, operacao = self._cenario()
        servico.executar(
            "Início", op="OP-FLUXO", setor="Dobra", recurso="Gasparini", operacao=operacao
        )
        linha = next(
            row
            for row in servico.listar_operacoes("OP-FLUXO", "Dobra", "Gasparini")
            if row.get("id") == operacao["id"]
        )
        self.assertIn("primeira_peca", linha)
        self.assertFalse(linha["pode_finalizar"])
        self.assertTrue(linha["primeira_peca"]["aplicavel"])
        self.assertTrue(linha["primeira_peca"]["setup_obrigatorio"])
        # Wave 6B — a tela sabe pelo backend que o Iniciar abre o popup.
        self.assertTrue(linha["primeira_peca"]["gate_estruturado"])
        self.assertTrue(linha["exige_gate_primeira_peca"])

        self._liberar_lote(db, servico, operacao)
        liberada = next(
            row
            for row in servico.listar_operacoes("OP-FLUXO", "Dobra", "Gasparini")
            if row.get("id") == operacao["id"]
        )
        self.assertTrue(liberada["pode_finalizar"])


class DrawingLookupTests(unittest.TestCase):
    """Seleção do PDF: sufixo não é versão; a data de modificação decide."""

    def _arquivo(self, base: Path, nome: str, minutos: int) -> Path:
        caminho = base / nome
        caminho.write_bytes(b"%PDF-1.4 conteudo de teste")
        instante = (datetime(2026, 9, 10, 8, 0) + timedelta(minutes=minutos)).timestamp()
        os.utime(caminho, (instante, instante))
        return caminho

    def test_caminho_nao_configurado_devolve_estado_vazio(self):
        db = FakeDatabase()
        resultado = DrawingLookupService(db, roots=()).buscar("OP-1", produto="PECA123")
        self.assertFalse(resultado.available)
        self.assertEqual(resultado.reason, REASON_NOT_CONFIGURED)
        self.assertNotIn("\\", resultado.message)

    def test_escolhe_o_arquivo_mais_recente_sem_interpretar_sufixo(self):
        db = FakeDatabase()
        with tempfile.TemporaryDirectory() as pasta:
            base = Path(pasta)
            self._arquivo(base, "PECA123.pdf", 0)
            self._arquivo(base, "PECA123_rev2.pdf", 10)
            escolhido = self._arquivo(base, "PECA123_a.pdf", 40)
            self._arquivo(base, "PECA123_m.pdf", 20)
            # Peça diferente com o mesmo prefixo não pode ser confundida.
            self._arquivo(base, "PECA1234.pdf", 999)

            resultado = DrawingLookupService(db, roots=(base,)).buscar(
                "OP-1", produto="PECA123"
            )
            self.assertTrue(resultado.available)
            self.assertEqual(resultado.selected.filename, escolhido.name)
            self.assertEqual(len(resultado.candidates), 4)
            self.assertEqual(resultado.como_dicionario()["candidate_count"], 4)
            self.assertEqual(resultado.path, escolhido)

    def test_peca_sem_desenho_nao_vira_erro_tecnico(self):
        db = FakeDatabase()
        with tempfile.TemporaryDirectory() as pasta:
            resultado = DrawingLookupService(db, roots=(Path(pasta),)).buscar(
                "OP-1", produto="SEM-DESENHO"
            )
            self.assertFalse(resultado.available)
            self.assertEqual(resultado.reason, REASON_NOT_FOUND)
            self.assertEqual(resultado.message, "Nenhum desenho disponível para esta peça.")

    def test_configuracao_aceita_varios_caminhos_de_rede(self):
        caminhos = parse_drawing_roots(r"\\servidor\engenharia\pdf; G:\Desenhos ")
        self.assertEqual(len(caminhos), 2)
        self.assertEqual(str(caminhos[0]), r"\\servidor\engenharia\pdf")
        self.assertEqual(parse_drawing_roots(""), ())


if __name__ == "__main__":
    unittest.main()
