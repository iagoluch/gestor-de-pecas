"""Wave 3 — o fluxo oficial de apontamento aplicado ao sistema.

Fonte funcional: ``Fluxo de apontamento.docx``. Estes testes fixam as regras
que a Wave 3 precisou tornar explícitas no código:

* **o Gestor controla o avanço da fila.** Depois que a OP e o roteiro existem
  localmente, concluir a etapa atual libera a próxima — sem esperar o TOTVS
  dizer onde a OP está, e sem depender de o WSPCP ter entregue o apontamento;
* ``IMPRESSAO OP`` já nasce satisfeita e ``FINALIZADA`` só é alcançada no fim;
* etapa fora da atual continua exigindo confirmação, e recurso incompatível
  continua bloqueado;
* a inspeção pode ser **executada** ou **dispensada**; dispensar não fabrica
  aprovação, cota nem RNC;
* Solda e Pintura não ficam presas esperando um checklist dimensional que
  ainda não existe para elas.
"""

from __future__ import annotations

import unittest

from app.core.quality import sector_has_quality
from mes.integrations.totvs.mapper import TotvsActivityClassification
from mes.services.operator_flow import OperatorFlowService
from mes.services.quality import QualityInspectionService
from tests.fakes import FakeDatabase
from tests.wave5_helpers import liberar_primeira_peca


def _operacao(**extra):
    base = {
        "codigo_op": "OP-W3",
        "produto_codigo": "PECA-W3",
        "produto_descricao": "Peça da Wave 3",
        "quantidade": 4,
        "ativo": True,
        "marco_terminal": False,
        "inspecao_qualidade": False,
    }
    base.update(extra)
    return base


class FluxoLocalDeFilaTests(unittest.TestCase):
    """A etapa atual é do Gestor; o TOTVS fornece o roteiro, não a posição."""

    def _cenario(self):
        db = FakeDatabase()
        tarefa = db.inserir_tarefa("T-W3")
        db.inserir_op_na_tarefa(tarefa, "OP-W3", "PECA-W3", "Dobra", 4)
        db.catalog_operations.extend([
            _operacao(id=1, numero_operacao="10", codigo_recurso="DOBRA3",
                      descricao_operacao="DOBRA", tipo_setor="Dobra", ordem=2),
            _operacao(id=2, numero_operacao="20", codigo_recurso="CNC-01",
                      descricao_operacao="USINAGEM", tipo_setor="Usinagem", ordem=3),
            _operacao(id=3, numero_operacao="99", codigo_recurso="ALMOX4",
                      descricao_operacao="FINALIZADA", tipo_setor=None, ordem=4,
                      ativo=False, marco_terminal=True),
        ])
        return db, OperatorFlowService(db, "OPERADOR W3")

    @staticmethod
    def _proximas(db, setor):
        return [
            row for row in db.listar_proximas_operacoes_roteiro(setor)
            if row.get("codigo_op") == "OP-W3"
        ]

    def test_concluir_a_etapa_atual_libera_a_proxima_fila_localmente(self):
        db, fluxo = self._cenario()
        dobra = db.catalog_operations[0]

        # Antes: só a Dobra enxerga a OP.
        self.assertEqual(len(self._proximas(db, "Dobra")), 1)
        self.assertEqual(self._proximas(db, "Usinagem"), [])

        liberar_primeira_peca(db, "OPERADOR W3", op="OP-W3", setor="Dobra",
                              recurso="1303", operacao=dobra)
        self.assertTrue(
            fluxo.executar("Início", op="OP-W3", setor="Dobra", recurso="1303",
                           operacao=dobra).ok
        )
        concluido = fluxo.executar(
            "Finalizado", op="OP-W3", setor="Dobra", recurso="1303",
            operacao=dobra, pecas_boas=4, operadores_cracha=["1"],
        )
        self.assertTrue(concluido.ok, concluido.message)

        # Depois: a Usinagem passa a enxergar, sem nenhuma consulta ao TOTVS.
        self.assertEqual(self._proximas(db, "Dobra"), [])
        liberadas = self._proximas(db, "Usinagem")
        self.assertEqual([row["numero_operacao"] for row in liberadas], ["20"])

    def test_avanco_nao_depende_de_entrega_ao_totvs(self):
        """WSPCP em RETRY não pode travar a fábrica."""

        db, fluxo = self._cenario()
        dobra = db.catalog_operations[0]
        liberar_primeira_peca(db, "OPERADOR W3", op="OP-W3", setor="Dobra",
                              recurso="1303", operacao=dobra)
        fluxo.executar("Início", op="OP-W3", setor="Dobra", recurso="1303", operacao=dobra)
        fluxo.executar(
            "Finalizado", op="OP-W3", setor="Dobra", recurso="1303",
            operacao=dobra, pecas_boas=4, operadores_cracha=["1"],
        )
        # Nenhum item foi entregue ao ERP; a próxima fila já está liberada.
        pendentes = [
            item for item in getattr(db, "totvs_outbox", [])
            if item.get("status") in {"PENDING", "RETRY", "SENDING"}
        ]
        self.assertEqual(len(self._proximas(db, "Usinagem")), 1, pendentes)

    def test_roteiro_nao_avanca_sozinho_sem_conclusao(self):
        db, _fluxo = self._cenario()
        self.assertEqual(self._proximas(db, "Usinagem"), [])

    def test_marco_terminal_nunca_entra_na_fila(self):
        db, fluxo = self._cenario()
        for indice in (0, 1):
            operacao = db.catalog_operations[indice]
            setor = operacao["tipo_setor"]
            recurso = "1303" if setor == "Dobra" else "Romi D 1000"
            liberar_primeira_peca(db, "OPERADOR W3", op="OP-W3", setor=setor,
                                  recurso=recurso, operacao=operacao)
            fluxo.executar("Início", op="OP-W3", setor=setor, recurso=recurso, operacao=operacao)
            fluxo.executar(
                "Finalizado", op="OP-W3", setor=setor, recurso=recurso,
                operacao=operacao, pecas_boas=4, operadores_cracha=["1"],
            )
        todas = db.listar_proximas_operacoes_roteiro()
        self.assertNotIn(
            "FINALIZADA", [row.get("descricao_operacao") for row in todas]
        )

    def test_impressao_op_nao_e_projetada_nem_exige_apontamento(self):
        """A etapa automática é satisfeita sem apontamento fictício."""

        from mes.integrations.totvs.mapper import TotvsProductionOrderMapper

        classificacao = TotvsProductionOrderMapper._special_treatment(
            type("A", (), {
                "activity_code": "01",
                "activity_description": "IMPRESSAO OP",
                "work_center_code": "PCP",
                "machine_code": "PCP",
            })()
        )
        self.assertIsNotNone(classificacao)
        self.assertIs(classificacao[0], TotvsActivityClassification.AUTOMATIC_SATISFIED)
        self.assertIn("nem cria apontamento fictício", classificacao[1])

    def test_etapa_fora_da_atual_exige_confirmacao_inclusive_em_outro_recurso(self):
        db, fluxo = self._cenario()
        rota = fluxo.listar_operacoes("OP-W3", "Dobra", "1303")
        # A Usinagem não pertence ao posto de Dobra, mas o roteiro completo
        # pode selecioná-la mediante a confirmação canônica.
        usinagem = next(row for row in rota if row["numero_operacao"] == "20")
        self.assertTrue(usinagem["selectable"])
        self.assertTrue(usinagem["requires_confirmation"])
        pendente = fluxo.executar(
            "Início", op="OP-W3", setor="Dobra", recurso="1303", operacao=usinagem
        )
        self.assertEqual(pendente.code, "confirmacao_etapa_anterior_obrigatoria")


class InspecaoTransitoriaTests(unittest.TestCase):
    """A inspeção pode ser executada ou pulada — nunca falsificada."""

    def _cenario(self, setor_anterior="Dobra", recurso_anterior="DOBRA3"):
        db = FakeDatabase()
        tarefa = db.inserir_tarefa("T-INSP")
        db.inserir_op_na_tarefa(tarefa, "OP-INSP", "PECA-INSP", setor_anterior, 3)
        db.catalog_operations.extend([
            _operacao(codigo_op="OP-INSP", produto_codigo="PECA-INSP", quantidade=3,
                      id=11, numero_operacao="10", codigo_recurso=recurso_anterior,
                      descricao_operacao=setor_anterior.upper(),
                      tipo_setor=setor_anterior, ordem=2),
            _operacao(codigo_op="OP-INSP", produto_codigo="PECA-INSP", quantidade=3,
                      id=12, numero_operacao="20", codigo_recurso="INSPEC",
                      descricao_operacao="INSPECAO", tipo_setor=None, ordem=3,
                      ativo=False, inspecao_qualidade=True),
            _operacao(codigo_op="OP-INSP", produto_codigo="PECA-INSP", quantidade=3,
                      id=13, numero_operacao="99", codigo_recurso="ALMOX4",
                      descricao_operacao="FINALIZADA", tipo_setor=None, ordem=4,
                      ativo=False, marco_terminal=True),
        ])
        fluxo = OperatorFlowService(db, "OPERADOR INSP")
        anterior = db.catalog_operations[0]
        recurso_posto = {"Dobra": "1303", "Solda Aço": "Estação 1", "Pintura": "Pintura"}[setor_anterior]
        liberar_primeira_peca(db, "OPERADOR INSP", op="OP-INSP", setor=setor_anterior,
                              recurso=recurso_posto, operacao=anterior)
        fluxo.executar("Início", op="OP-INSP", setor=setor_anterior,
                       recurso=recurso_posto, operacao=anterior)
        fluxo.executar("Finalizado", op="OP-INSP", setor=setor_anterior,
                       recurso=recurso_posto, operacao=anterior,
                       pecas_boas=3, operadores_cracha=["1"])
        return db, fluxo

    def test_inspecao_executada_continua_disponivel_na_fila(self):
        db, _fluxo = self._cenario()
        fila = QualityInspectionService(db, "INSPETOR").listar_fila("Dobra")
        self.assertEqual([item["op"] for item in fila["items"]], ["OP-INSP"])

    def test_dispensa_exige_cracha_valido(self):
        db, _fluxo = self._cenario()
        servico = QualityInspectionService(db, "INSPETOR")
        sem_cracha = servico.dispensar_inspecao("OP-INSP", "Dobra", badges=[])
        self.assertEqual(sem_cracha.code, "qualidade_dispensa_cracha_obrigatorio")
        invalido = servico.dispensar_inspecao("OP-INSP", "Dobra", badges=["9999"])
        self.assertEqual(invalido.code, "qualidade_dispensa_cracha_invalido")

    def test_dispensa_tira_a_op_da_fila_sem_falsificar_a_inspecao(self):
        db, _fluxo = self._cenario()
        servico = QualityInspectionService(db, "INSPETOR")
        resultado = servico.dispensar_inspecao(
            "OP-INSP", "Dobra", badges=["1"], motivo="Operador treinado inspecionou."
        )
        self.assertTrue(resultado.ok, resultado.message)
        self.assertEqual(resultado.code, "qualidade_inspecao_dispensada")

        registro = db.buscar_dispensa_inspecao("OP-INSP")
        self.assertEqual(registro["status"], "DISPENSADA")
        # Nada de inspeção fabricada:
        self.assertIsNone(registro["apontamento_id"])
        self.assertIsNone(registro["template_id"])
        self.assertEqual(db.quality_pieces, [])
        self.assertEqual(getattr(db, "quality_rnc", []), [])
        self.assertFalse(
            any(row["status"] == "CONCLUIDA" for row in db.quality_inspections)
        )
        # E a OP sai da fila da Qualidade.
        fila = QualityInspectionService(db, "INSPETOR").listar_fila("Dobra")
        self.assertEqual(fila["items"], [])

    def test_dispensa_e_auditada_com_autor_cracha_e_motivo(self):
        db, _fluxo = self._cenario()
        QualityInspectionService(db, "INSPETOR").dispensar_inspecao(
            "OP-INSP", "Dobra", badges=["1"], motivo="Treinamento em andamento."
        )
        registro = db.buscar_dispensa_inspecao("OP-INSP")
        self.assertEqual(registro["dispensa_cracha"], "1")
        self.assertTrue(registro["dispensa_autorizada_por"])
        self.assertEqual(registro["dispensa_motivo"], "Treinamento em andamento.")
        evento = next(
            item for item in db.events
            if item["tipo"] == "qualidade_inspecao_dispensada"
        )
        self.assertEqual(evento["referencia"], "OP-INSP")

    def test_dispensa_repetida_e_idempotente(self):
        db, _fluxo = self._cenario()
        servico = QualityInspectionService(db, "INSPETOR")
        servico.dispensar_inspecao("OP-INSP", "Dobra", badges=["1"])
        segunda = servico.dispensar_inspecao("OP-INSP", "Dobra", badges=["1"])
        self.assertTrue(segunda.ok)
        self.assertEqual(segunda.code, "qualidade_dispensa_existente")
        self.assertEqual(
            sum(1 for row in db.quality_inspections if row["status"] == "DISPENSADA"), 1
        )

    def test_solda_aponta_a_inspecao_so_para_contar_tempo(self):
        """Solda/Pintura não têm checklist dimensional; o tempo é contado."""

        self.assertFalse(sector_has_quality("Solda Aço"))
        db, fluxo = self._cenario(setor_anterior="Solda Aço", recurso_anterior="SOLDA4")
        rota = fluxo.listar_operacoes("OP-INSP", "Solda Aço", "Estação 1")
        inspecao = next(row for row in rota if row["descricao_operacao"] == "INSPECAO")

        self.assertTrue(inspecao["inspecao_sem_checklist"])
        self.assertEqual(inspecao["setor_efetivo"], "Solda Aço")
        self.assertTrue(inspecao["station_eligible"])
        self.assertTrue(inspecao["actionable"])

        iniciado = fluxo.executar(
            "Início", op="OP-INSP", setor="Solda Aço", recurso="Estação 1", operacao=inspecao
        )
        self.assertTrue(iniciado.ok, iniciado.message)
        concluido = fluxo.executar(
            "Finalizado", op="OP-INSP", setor="Solda Aço", recurso="Estação 1",
            operacao=inspecao, pecas_boas=3, operadores_cracha=["1"],
        )
        self.assertTrue(concluido.ok, concluido.message)
        # Contou tempo e seguiu: nenhuma sessão de inspeção foi criada.
        self.assertEqual(db.quality_inspections, [])
        # Wave 5: a operação INSPECAO fica fora do portão da primeira peça —
        # ela não produz peça, só contabiliza o tempo do posto.
        self.assertEqual(
            [row for row in db.first_pieces if row["numero_operacao"] == "20"], []
        )

    def test_dobra_continua_usando_a_aba_da_qualidade(self):
        """Setor com Qualidade não ganha atalho pelo roteiro do posto."""

        self.assertTrue(sector_has_quality("Dobra"))
        db, fluxo = self._cenario()
        rota = fluxo.listar_operacoes("OP-INSP", "Dobra", "1303")
        inspecao = next(row for row in rota if row["descricao_operacao"] == "INSPECAO")
        self.assertFalse(inspecao["inspecao_sem_checklist"])
        self.assertFalse(inspecao["station_eligible"])
        del db


if __name__ == "__main__":
    unittest.main()
