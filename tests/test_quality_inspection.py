"""Etapa 7C — inspeção dimensional da Qualidade.

Duas camadas de prova:

* ``QualityRuleTests`` usa o dublê em memória e cobre as regras funcionais —
  setor habilitado, template, sequência da peça, RNC, resultado e conclusão.
* ``QualityPostgresTests`` usa um schema descartável de ``TEST_DATABASE_URL`` e
  prova o que só o banco garante: a operação ``INSPECAO`` projetada inativa, a
  unicidade da unidade inspecionada e o vínculo com o fluxo canônico do
  operador — o mesmo que produz o movimento TOTVS.
"""

import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.operator_sectors import OPERATOR_SECTORS
from app.core.permissions import (
    USER_LEVELS,
    can_manage_quality_template,
    normalize_user_level,
    quality_sector_for_user_level,
)
from app.core.quality import (
    QUALITY_APPOINTMENT_SECTOR,
    QUALITY_ENABLED_SECTORS,
    sector_has_quality,
)
from app.database.config import load_postgres_config
from app.database.database import Database
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService
from mes.services.operator_flow import OperatorFlowService
from mes.services.quality import QualityInspectionService
from tests.fakes import FakeDatabase
from tests.wave5_helpers import liberar_primeira_peca


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "totvs"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"

RECURSOS_CANONICOS = (
    {"codigo": "PLASMA", "nome": "Plasma TerraBlade 4", "tipo_setor": "Corte"},
    {"codigo": "CNC-01", "nome": "Romi D 1000", "tipo_setor": "Usinagem"},
)


def _cotas(*padroes):
    return [
        {"sequencia": index, "descricao": None, "padrao": padrao, "unidade": "mm"}
        for index, padrao in enumerate(padroes, start=1)
    ]


def _medidas(*valores):
    return [
        {"sequencia": index, "medida": medida, "status": status}
        for index, (medida, status) in enumerate(valores, start=1)
    ]


class QualityCapabilityTests(unittest.TestCase):
    """A Qualidade é uma capacidade de setor, nunca um perfil de usuário."""

    def test_caldeiraria_possui_qualidade_e_corte_nao(self):
        for setor in ("Dobra", "Usinagem", "Serra"):
            with self.subTest(setor=setor):
                self.assertTrue(sector_has_quality(setor))
        for setor in ("Corte", "Pintura", "Solda Aço", "Montagem", "Destaque"):
            with self.subTest(setor=setor):
                self.assertFalse(sector_has_quality(setor))

    def test_nao_existe_perfil_exclusivo_de_qualidade(self):
        self.assertNotIn("qualidade", {level.casefold() for level in USER_LEVELS})
        self.assertNotIn(
            "qualidade",
            {sector.name.casefold() for sector in OPERATOR_SECTORS},
        )
        # A faixa de execução da inspeção não é um setor operacional.
        self.assertNotIn(
            QUALITY_APPOINTMENT_SECTOR.casefold(),
            {sector.name.casefold() for sector in OPERATOR_SECTORS},
        )

    def test_operador_habilitado_acessa_e_corte_nao(self):
        self.assertEqual(
            quality_sector_for_user_level("operador_dobra").name, "Dobra"
        )
        self.assertIsNone(quality_sector_for_user_level("operador_corte"))
        self.assertIsNone(quality_sector_for_user_level("estacao1aco"))

    def test_somente_supervisor_lider_e_admin_editam_template(self):
        for level in ("admin", "supervisor", "lider"):
            with self.subTest(level=level):
                self.assertTrue(can_manage_quality_template(level))
        for level in USER_LEVELS:
            if normalize_user_level(level) in {"admin", "supervisor", "lider"}:
                continue
            with self.subTest(level=level):
                self.assertFalse(can_manage_quality_template(level))

    def test_setores_habilitados_ficam_em_um_unico_lugar(self):
        """Habilitar um setor novo é uma alteração central, não um if espalhado."""

        self.assertEqual(QUALITY_ENABLED_SECTORS, ("Dobra", "Usinagem", "Serra"))


class QualityBoundaryTests(unittest.TestCase):
    """A Qualidade lê a fila local; ela não conhece nem aciona o ERP."""

    FONTES = (
        "backend/api/routers/quality.py",
        "mes/services/quality.py",
        "app/database/quality_repository.py",
        "web/src/pages/operator/QualityPage.tsx",
        "web/src/pages/operator/QualityInspectionPage.tsx",
    )

    def test_nenhuma_fonte_da_qualidade_aciona_busca_sob_demanda(self):
        proibidos = ("provision", "ondemand", "on_demand", "gpopsync", "/sync")
        for caminho in self.FONTES:
            fonte = (ROOT / caminho).read_text(encoding="utf-8").casefold()
            for termo in proibidos:
                with self.subTest(arquivo=caminho, termo=termo):
                    self.assertNotIn(termo, fonte)

    def test_a_qualidade_nao_possui_transporte_proprio_para_o_totvs(self):
        """Movimento empresarial só pelo fluxo canônico do operador."""

        codigo = (ROOT / "mes/services/quality.py").read_text(encoding="utf-8")
        # O único caminho de movimento é o OperatorFlowService.
        self.assertIn("from mes.services.operator_flow import OperatorFlowService", codigo)
        for termo in ("wspcp", "soap", "productionappointment", "enfileirar_outbound"):
            with self.subTest(termo=termo):
                self.assertNotIn(termo, codigo.casefold())


class QualityRuleTests(unittest.TestCase):
    """Regras funcionais da inspeção sobre o dublê em memória."""

    OP = "OP-QUAL-1"
    PRODUTO = "PROD-QUAL"

    def setUp(self):
        self.db = FakeDatabase()
        # Refugo exige o crachá de um responsável autorizado (ajuste da Wave
        # 6B), inclusive quando ele vem da inspeção dimensional.
        self.db.cadastrar_operador_apontamento(
            "77", "Inspetor", autorizador_retrabalho=True
        )
        task = self.db.inserir_tarefa("T-QUAL")
        self.db.inserir_op_na_tarefa(task, self.OP, self.PRODUTO, "Dobra", 3)
        self.db.catalog_operations.append(
            {
                "id": 501,
                "codigo_op": self.OP,
                "numero_operacao": "10",
                "codigo_recurso": "DOBRA3",
                "descricao_operacao": "DOBRA",
                "tipo_setor": "Dobra",
                "produto_codigo": self.PRODUTO,
                "produto_descricao": "Chapa de teste",
                "quantidade": 3,
                "ordem": 1,
                "ativo": True,
            }
        )
        self.db.catalog_operations.append(
            {
                "id": 502,
                "codigo_op": self.OP,
                "numero_operacao": "20",
                "codigo_recurso": "INSPEC",
                "descricao_operacao": "INSPECAO",
                "tipo_setor": None,
                "produto_codigo": self.PRODUTO,
                "produto_descricao": "Chapa de teste",
                "quantidade": 3,
                "ordem": 2,
                "ativo": False,
                "marco_terminal": False,
                "inspecao_qualidade": True,
            }
        )
        self.service = QualityInspectionService(self.db, "INSPETOR")

    # ------------------------------------------------------------------
    def _concluir_operacao_anterior(self):
        flow = OperatorFlowService(self.db, "OPERADOR DOBRA")
        operacao = self.db.listar_operacoes_para_op(self.OP, "Dobra")[0]
        # Wave 6B: em Dobra o portão Setup/Qualidade antecede a produção, e a
        # etapa produtiva só fecha depois da primeira peça aprovada.
        liberar_primeira_peca(
            self.db,
            "OPERADOR DOBRA",
            op=self.OP,
            setor="Dobra",
            recurso="1303",
            operacao=operacao,
        )
        flow.executar("Início", op=self.OP, setor="Dobra", recurso="1303", operacao=operacao)
        flow.executar(
            "Finalizado",
            op=self.OP,
            setor="Dobra",
            recurso="1303",
            operacao=operacao,
            pecas_boas=3,
            operadores_cracha=["77"],
        )

    def _abrir(self):
        self._concluir_operacao_anterior()
        resultado = self.service.abrir_inspecao(self.OP, "Dobra")
        self.assertTrue(resultado.ok, resultado.message)
        return resultado.data

    def _rota_usinagem(self):
        """Segunda OP, com roteiro que termina na Usinagem antes da inspeção."""

        op = "OP-QUAL-2"
        task = self.db.inserir_tarefa("T-QUAL-2")
        self.db.inserir_op_na_tarefa(task, op, self.PRODUTO, "Usinagem", 2)
        self.db.catalog_operations.append({
            "id": 601, "codigo_op": op, "numero_operacao": "10",
            "codigo_recurso": "CNC-01", "descricao_operacao": "USINAGEM",
            "tipo_setor": "Usinagem", "produto_codigo": self.PRODUTO,
            "produto_descricao": "Chapa de teste", "quantidade": 2,
            "ordem": 1, "ativo": True,
        })
        self.db.catalog_operations.append({
            "id": 602, "codigo_op": op, "numero_operacao": "20",
            "codigo_recurso": "INSPEC", "descricao_operacao": "INSPECAO",
            "tipo_setor": None, "produto_codigo": self.PRODUTO,
            "produto_descricao": "Chapa de teste", "quantidade": 2,
            "ordem": 2, "ativo": False, "marco_terminal": False,
            "inspecao_qualidade": True,
        })
        flow = OperatorFlowService(self.db, "OPERADOR USINAGEM")
        operacao = self.db.listar_operacoes_para_op(op, "Usinagem")[0]
        liberar_primeira_peca(
            self.db,
            "OPERADOR USINAGEM",
            op=op,
            setor="Usinagem",
            recurso="Romi D 1000",
            operacao=operacao,
        )
        flow.executar("Início", op=op, setor="Usinagem", recurso="Romi D 1000", operacao=operacao)
        flow.executar(
            "Finalizado", op=op, setor="Usinagem", recurso="Romi D 1000",
            operacao=operacao, pecas_boas=2, operadores_cracha=["77"],
        )
        return op

    def test_fila_de_qualidade_e_do_setor_que_produziu_a_peca(self):
        """Peça pronta na Dobra não aparece na Qualidade da Usinagem."""

        self._concluir_operacao_anterior()
        op_usinagem = self._rota_usinagem()

        dobra = [item["op"] for item in self.service.listar_fila("Dobra")["items"]]
        usinagem = [item["op"] for item in self.service.listar_fila("Usinagem")["items"]]
        self.assertEqual(dobra, [self.OP])
        self.assertEqual(usinagem, [op_usinagem])
        self.assertEqual(self.service.listar_fila("Serra")["items"], [])

        # Digitar a OP do outro setor também não abre a inspeção.
        recusa = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_op_outro_setor")
        self.assertIn("Dobra", recusa.message)

        aceita = self.service.abrir_inspecao(op_usinagem, "Usinagem")
        self.assertTrue(aceita.ok, aceita.message)

    def test_escrita_revalida_o_setor_dono_da_inspecao(self):
        """Trocar o ``inspecao_id`` não atravessa a fronteira de setor.

        Regressão do IDOR M1: a abertura recusava a OP de outro setor, mas
        peça, finalização e leitura recebiam apenas o id e não repetiam a
        checagem — um operador da Usinagem escrevia na inspeção da Dobra.
        """

        estado = self._abrir()
        self._template("125,0 ± 0,5")

        intruso = QualityInspectionService(
            self.db, "OPERADOR USINAGEM", nivel="operador_usinagem"
        )
        peca = intruso.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("125,0", "CONFORME")),
        )
        self.assertFalse(peca.ok)
        self.assertEqual(peca.code, "qualidade_inspecao_outro_setor")
        self.assertIn("Dobra", peca.message)

        fim = intruso.finalizar_inspecao(estado["id"], badges=["77"])
        self.assertFalse(fim.ok)
        self.assertEqual(fim.code, "qualidade_inspecao_outro_setor")

        self.assertIsNone(intruso.obter_inspecao(estado["id"]))
        self.assertEqual(
            len(self.db.listar_pecas_inspecionadas(estado["id"]) or ()), 0
        )

        # E o operador certo continua passando: a guarda não pode criar falso
        # negativo depois que a OP sai da fila de elegíveis.
        dono = QualityInspectionService(
            self.db, "OPERADOR DOBRA", nivel="operador_dobra"
        )
        self.assertIsNotNone(dono.obter_inspecao(estado["id"]))
        registrada = dono.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("125,0", "CONFORME")),
        )
        self.assertTrue(registrada.ok, registrada.message)

    def test_inspecao_legada_sem_origem_continua_visivel_a_todos(self):
        """Linha anterior à migração não bloqueia o operador que a assumir."""

        estado = self._abrir()
        self.db._quality_session(estado["id"])["tipo_setor_origem"] = None

        usinagem = QualityInspectionService(
            self.db, "OPERADOR USINAGEM", nivel="operador_usinagem"
        )
        self.assertIsNotNone(usinagem.obter_inspecao(estado["id"]))

    def _template(self, *padroes):
        resultado = self.service.definir_template(self.PRODUTO, _cotas(*padroes))
        self.assertTrue(resultado.ok, resultado.message)
        return resultado.data

    # ------------------------------------------------------------------
    def test_corte_nao_habilita_a_area_de_qualidade(self):
        fila = self.service.listar_fila("Corte")
        self.assertEqual(fila["items"], [])
        resultado = self.service.abrir_inspecao(self.OP, "Corte")
        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.code, "qualidade_setor_indisponivel")

    def test_op_sem_operacao_de_inspecao_nao_entra_na_fila(self):
        outra = "OP-SEM-INSPECAO"
        self.db.catalog_operations.append(
            {
                "id": 601,
                "codigo_op": outra,
                "numero_operacao": "10",
                "codigo_recurso": "PLASMA",
                "descricao_operacao": "CORTE",
                "tipo_setor": "Corte",
                "produto_codigo": "P2",
                "produto_descricao": "Sem inspeção",
                "quantidade": 5,
                "ordem": 1,
                "ativo": True,
            }
        )
        fila = self.service.listar_fila("Dobra")
        self.assertNotIn(outra, [item["op"] for item in fila["items"]])

    def test_fila_espera_a_operacao_anterior_concluir(self):
        # Antes de concluir a etapa anterior a OP não é elegível.
        self.assertEqual(self.service.listar_fila("Dobra")["items"], [])
        recusa = self.service.abrir_inspecao(self.OP, "Dobra")
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_op_nao_elegivel")

        self._concluir_operacao_anterior()
        fila = self.service.listar_fila("Dobra")
        self.assertEqual([item["op"] for item in fila["items"]], [self.OP])
        self.assertEqual(fila["items"][0]["quantidade"], 3)
        self.assertEqual(fila["resumo"]["aguardando"], 3)

    def test_pesquisa_e_filtro_local_sem_consultar_o_erp(self):
        self._concluir_operacao_anterior()
        # Nenhuma busca sob demanda existe aqui: o dublê falha se alguém tentar.
        self.db.provisionar_op = None
        encontrada = self.service.listar_fila("Dobra", busca=self.OP)
        self.assertEqual([item["op"] for item in encontrada["items"]], [self.OP])
        self.assertIsNone(encontrada["busca"])

        por_produto = self.service.listar_fila("Dobra", busca=self.PRODUTO)
        self.assertEqual([item["op"] for item in por_produto["items"]], [self.OP])

        por_recurso = self.service.listar_fila("Dobra", recurso="INSPEC")
        self.assertEqual([item["op"] for item in por_recurso["items"]], [self.OP])
        self.assertEqual(self.service.listar_fila("Dobra", recurso="OUTRO")["items"], [])

    def test_pesquisa_explica_o_estado_local_da_op(self):
        inexistente = self.service.listar_fila("Dobra", busca="OP-INEXISTENTE")
        self.assertEqual(inexistente["busca"]["message"], "OP não disponível para inspeção.")

        # A OP existe, mas o roteiro ainda não chegou na inspeção.
        pendente = self.service.listar_fila("Dobra", busca=self.OP)
        self.assertEqual(
            pendente["busca"]["message"], "OP ainda não está aguardando inspeção."
        )

        self._abrir()
        self._template("125,0 ± 0,5")
        for numero in (1, 2, 3):
            self.service.registrar_peca(
                1,
                numero_peca=numero,
                resultado="APROVADA",
                medidas=_medidas(("124,9", "CONFORME")),
                badges=["77"],
            )
        concluida = self.service.listar_fila("Dobra", busca=self.OP)
        self.assertEqual(concluida["busca"]["message"], "Inspeção desta OP já concluída.")

    # ------------------------------------------------------------------
    def test_produto_sem_template_comeca_em_cota_1_e_aceita_novas_cotas(self):
        estado = self._abrir()
        self.assertIsNone(estado["template"])
        self.assertTrue(estado["template_editavel"])

        salvo = self._template("125,0 ± 0,5", "80,0 ± 0,5")
        self.assertEqual([cota["sequencia"] for cota in salvo["cotas"]], [1, 2])
        self.assertEqual(salvo["revisao"], 1)

        # Próxima inspeção do mesmo produto reutiliza o template salvo.
        recarregado = self.service.obter_inspecao(estado["id"])
        self.assertEqual(len(recarregado["template"]["cotas"]), 2)
        self.assertFalse(recarregado["template_editavel"])

    def test_template_exige_padrao_em_todas_as_cotas(self):
        self._abrir()
        recusa = self.service.definir_template(
            self.PRODUTO, [{"sequencia": 1, "padrao": "  "}]
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_cota_padrao_obrigatorio")

    def test_operador_nao_altera_template_salvo_e_supervisor_altera(self):
        self._abrir()
        self._template("125,0 ± 0,5")

        operador = self.service.definir_template(self.PRODUTO, _cotas("999,0 ± 9,9"))
        self.assertFalse(operador.ok)
        self.assertEqual(operador.code, "qualidade_template_protegido")

        supervisor = QualityInspectionService(self.db, "SUPERVISOR", nivel="supervisor")
        alterado = supervisor.definir_template(
            self.PRODUTO, _cotas("130,0 ± 0,5"), pode_editar=True
        )
        self.assertTrue(alterado.ok, alterado.message)
        self.assertEqual(alterado.data["revisao"], 2)
        self.assertEqual(alterado.data["cotas"][0]["padrao"], "130,0 ± 0,5")
        self.assertEqual(alterado.data["atualizado_por"], "SUPERVISOR")

    def test_snapshot_da_inspecao_nao_muda_quando_o_template_e_editado(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )
        peca = self.db.listar_pecas_inspecionadas(estado["id"])[0]

        supervisor = QualityInspectionService(self.db, "SUPERVISOR")
        supervisor.definir_template(
            self.PRODUTO, _cotas("500,0 ± 5,0"), pode_editar=True
        )

        cotas = self.service.detalhar_peca(peca["id"])
        self.assertEqual(cotas[0]["padrao"], "125,0 ± 0,5")
        self.assertEqual(cotas[0]["medida"], "124,9")

    # ------------------------------------------------------------------
    def test_inspecao_avanca_peca_a_peca_e_nao_duplica_unidade(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        self.assertEqual(self.service.obter_inspecao(estado["id"])["peca_atual"], 1)

        primeira = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )
        self.assertTrue(primeira.ok, primeira.message)
        self.assertEqual(primeira.data["peca_atual"], 2)

        repetida = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )
        self.assertFalse(repetida.ok)
        self.assertEqual(repetida.code, "qualidade_sequencia_peca")

        adiantada = self.service.registrar_peca(
            estado["id"],
            numero_peca=3,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )
        self.assertFalse(adiantada.ok)
        self.assertEqual(adiantada.code, "qualidade_sequencia_peca")

    def test_medida_ausente_ou_status_vazio_bloqueiam_a_peca(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5", "80,0 ± 0,5")
        faltando = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=[{"sequencia": 1, "medida": "124,9", "status": "CONFORME"}],
        )
        self.assertFalse(faltando.ok)
        self.assertEqual(faltando.code, "qualidade_medida_ausente")

        # Wave 5.1 — com padrão numérico o status deixou de ser escolha do
        # operador: o backend calcula pela faixa `referencia ± margem`, então a
        # ausência do status enviado pelo cliente não bloqueia mais nada.
        sem_status = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=[
                {"sequencia": 1, "medida": "124,9", "status": ""},
                {"sequencia": 2, "medida": "80,1", "status": ""},
            ],
        )
        self.assertTrue(sem_status.ok, sem_status.message)

    def test_status_ainda_e_exigido_quando_o_padrao_nao_e_numerico(self):
        """Template legado em texto livre não tem faixa para comparar."""

        estado = self._abrir()
        self._template("conforme gabarito")
        sem_status = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=[{"sequencia": 1, "medida": "ok", "status": ""}],
        )
        self.assertFalse(sem_status.ok)
        self.assertEqual(sem_status.code, "qualidade_status_cota_invalido")

    def test_cota_fora_do_template_e_recusada(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        recusa = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=[
                {"sequencia": 1, "medida": "124,9", "status": "CONFORME"},
                {"sequencia": 9, "medida": "10,0", "status": "CONFORME"},
            ],
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_cota_desconhecida")

    # ------------------------------------------------------------------
    def test_conforme_nao_aceita_rnc_e_nao_conforme_exige_rnc(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")

        sem_necessidade = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
            rnc={"motivo": "não deveria existir"},
        )
        self.assertFalse(sem_necessidade.ok)
        self.assertEqual(sem_necessidade.code, "qualidade_rnc_sem_nao_conformidade")

        sem_rnc = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="REFUGO",
            medidas=_medidas(("130,0", "NAO_CONFORME")),
        )
        self.assertFalse(sem_rnc.ok)
        self.assertEqual(sem_rnc.code, "qualidade_rnc_obrigatoria")

    def test_nao_conformidade_nunca_resulta_em_aprovada(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        recusa = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("130,0", "NAO_CONFORME")),
            rnc={"motivo": "fora de tolerância"},
        )
        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "qualidade_aprovacao_nao_conforme")

    def test_rnc_fica_ligada_a_peca_e_as_cotas_que_falharam(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5", "80,0 ± 0,5")
        salvo = self.service.registrar_peca(
            estado["id"],
            numero_peca=1,
            resultado="RETRABALHO",
            medidas=_medidas(("124,9", "CONFORME"), ("89,8", "NAO_CONFORME")),
            rnc={"motivo": "Esquadro lateral fora do padrão", "observacao": "reprocessar"},
        )
        self.assertTrue(salvo.ok, salvo.message)

        peca = self.db.listar_pecas_inspecionadas(estado["id"])[0]
        self.assertTrue(peca["possui_nao_conformidade"])
        self.assertIsNotNone(peca["rnc_id"])

        rnc = self.db.quality_rnc[0]
        self.assertEqual(rnc["codigo_op"], self.OP)
        self.assertEqual(rnc["numero_peca"], 1)
        self.assertEqual(rnc["motivo"], "Esquadro lateral fora do padrão")
        self.assertEqual(rnc["codigo_recurso"], "INSPEC")

        cotas = self.service.detalhar_peca(peca["id"])
        self.assertEqual(
            [(cota["sequencia"], cota["status"]) for cota in cotas],
            [(1, "CONFORME"), (2, "NAO_CONFORME")],
        )

    # ------------------------------------------------------------------
    def test_ultima_peca_finaliza_a_inspecao_e_o_historico_registra_tudo(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        resultados = ("APROVADA", "RETRABALHO", "REFUGO")
        for numero, resultado in enumerate(resultados, start=1):
            conforme = resultado == "APROVADA"
            resposta = self.service.registrar_peca(
                estado["id"],
                numero_peca=numero,
                resultado=resultado,
                medidas=_medidas(("124,9" if conforme else "131,0", "CONFORME" if conforme else "NAO_CONFORME")),
                rnc=None if conforme else {"motivo": f"Não conformidade da peça {numero}"},
                badges=["77"],
            )
            self.assertTrue(resposta.ok, resposta.message)

        self.assertEqual(resposta.code, "inspecao_concluida")
        self.assertEqual(resposta.data["aprovadas"], 1)
        self.assertEqual(resposta.data["retrabalho"], 1)
        self.assertEqual(resposta.data["refugo"], 1)
        # Wave 4: boas + refugo atendem o planejado; só o retrabalho continua
        # pendente. 1 aprovada + 1 refugo de 3 deixam a inspeção parcial com
        # saldo de 1 — a peça em retrabalho, que volta para reinspeção.
        self.assertFalse(resposta.data["operacao_finalizada"])
        self.assertEqual(resposta.data["saldo_restante"], 1)

        sessao = self.db.buscar_inspecao_qualidade(estado["id"])
        self.assertEqual(sessao["status"], "CONCLUIDA")
        self.assertIsNotNone(sessao["finalizada_em"])

        historico = self.service.listar_historico("Dobra")
        self.assertEqual(len(historico), 3)
        self.assertEqual({item["op"] for item in historico}, {self.OP})
        self.assertEqual(
            {item["resultado"] for item in historico},
            {"APROVADA", "RETRABALHO", "REFUGO"},
        )
        self.assertEqual(
            sorted(item["peca"] for item in historico), ["1/3", "2/3", "3/3"]
        )
        self.assertEqual(
            len([item for item in historico if item["rnc"]]), 2
        )
        # A inspeção concluída sai da fila enquanto o retrabalho volta para a
        # operação produtiva anterior exata do roteiro.
        fila = self.service.listar_fila("Dobra")["items"]
        self.assertEqual(fila, [])
        retorno = next(
            row for row in self.db.appointments
            if row.get("retorno_retrabalho_qualidade")
        )
        self.assertEqual(retorno["catalogo_operacao_id"], 501)
        self.assertEqual(retorno["quantidade"], 1)
        self.assertEqual(retorno["status"], "Aguardando")
        self.assertEqual(
            self.service.listar_historico("Dobra")[1]["resultado"],
            "RETRABALHO",
        )

    def test_op_totalmente_aprovada_fecha_a_operacao_e_sai_da_fila(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        for numero in (1, 2, 3):
            resposta = self.service.registrar_peca(
                estado["id"],
                numero_peca=numero,
                resultado="APROVADA",
                medidas=_medidas(("124,9", "CONFORME")),
                badges=["77"],
            )
            self.assertTrue(resposta.ok, resposta.message)
        self.assertEqual(resposta.code, "inspecao_concluida")
        self.assertTrue(resposta.data["operacao_finalizada"])
        self.assertEqual(self.service.listar_fila("Dobra")["items"], [])
        apontamento = next(
            row for row in self.db.appointments
            if row.get("tipo_setor") == QUALITY_APPOINTMENT_SECTOR
        )
        self.assertEqual(apontamento["status"], "Finalizado")
        self.assertEqual(apontamento["quantidade_boa"], 3)

    def test_reinspecao_continua_no_mesmo_apontamento_da_operacao(self):
        """Retrabalho devolve a OP à fila e a operação do roteiro continua uma só."""

        estado = self._abrir()
        self._template("125,0 ± 0,5")
        for numero in (1, 2):
            self.service.registrar_peca(
                estado["id"],
                numero_peca=numero,
                resultado="APROVADA",
                medidas=_medidas(("124,9", "CONFORME")),
            )
        self.service.registrar_peca(
            estado["id"],
            numero_peca=3,
            resultado="RETRABALHO",
            medidas=_medidas(("131,0", "NAO_CONFORME")),
            rnc={"motivo": "Fora do padrão"},
            badges=["77"],
        )
        self.assertEqual(len(self.db.appointments), 3)

        retorno = next(
            row for row in self.db.appointments
            if row.get("retorno_retrabalho_qualidade")
        )
        operacao_anterior = self.db.buscar_operacao_produtiva_anterior(self.OP, 2)
        iniciado = OperatorFlowService(self.db, "OPERADOR RETRABALHO").executar(
            "Retrabalho", op=self.OP, setor="Dobra", recurso="1303",
            operacao=operacao_anterior,
        )
        self.assertTrue(iniciado.ok, iniciado.message)
        concluido = OperatorFlowService(self.db, "OPERADOR RETRABALHO").executar(
            "Finalizado", op=self.OP, setor="Dobra", recurso="1303",
            operacao=operacao_anterior, pecas_boas=1, operadores_cracha=["77"],
        )
        self.assertTrue(concluido.ok, concluido.message)
        self.assertEqual(
            self.db.buscar_apontamento_operacional(retorno["id"])["status"],
            "Finalizado",
        )

        reaberta = self.service.abrir_inspecao(self.OP, "Dobra")
        self.assertTrue(reaberta.ok, reaberta.message)
        self.assertNotEqual(reaberta.data["id"], estado["id"])
        self.assertEqual(reaberta.data["quantidade_total"], 1)
        # Nenhum apontamento novo: a operação INSPECAO do roteiro é uma só.
        self.assertEqual(len(self.db.appointments), 3)

        final = self.service.registrar_peca(
            reaberta.data["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
            badges=["77"],
        )
        self.assertTrue(final.ok, final.message)
        self.assertTrue(final.data["operacao_finalizada"])
        self.assertEqual(self.service.listar_fila("Dobra")["items"], [])

    def test_ultima_peca_exige_cracha_antes_de_gravar(self):
        estado = self._abrir()
        self._template("125,0 ± 0,5")
        for numero in (1, 2):
            self.service.registrar_peca(
                estado["id"],
                numero_peca=numero,
                resultado="APROVADA",
                medidas=_medidas(("124,9", "CONFORME")),
            )
        sem_cracha = self.service.registrar_peca(
            estado["id"],
            numero_peca=3,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )
        self.assertFalse(sem_cracha.ok)
        self.assertEqual(sem_cracha.code, "qualidade_cracha_obrigatorio")
        # A peça não foi gravada: a inspeção continua na unidade 3.
        self.assertEqual(self.service.obter_inspecao(estado["id"])["peca_atual"], 3)

    def test_inspecao_totalmente_em_retrabalho_sai_da_fila_e_retorna_ao_roteiro(self):

        estado = self._abrir()
        self._template("125,0 ± 0,5")
        for numero in (1, 2):
            self.service.registrar_peca(
                estado["id"],
                numero_peca=numero,
                resultado="RETRABALHO",
                medidas=_medidas(("131,0", "NAO_CONFORME")),
                rnc={"motivo": f"Fora do padrão na peça {numero}"},
            )
        ultima = self.service.registrar_peca(
            estado["id"],
            numero_peca=3,
            resultado="RETRABALHO",
            medidas=_medidas(("131,0", "NAO_CONFORME")),
            rnc={"motivo": "Fora do padrão na peça 3"},
            badges=["77"],
        )
        self.assertTrue(ultima.ok, ultima.message)
        self.assertEqual(ultima.code, "inspecao_concluida")
        self.assertEqual(
            self.db.buscar_inspecao_qualidade(estado["id"])["status"], "CONCLUIDA"
        )
        self.assertEqual(self.service.listar_fila("Dobra")["items"], [])
        retorno = next(
            row for row in self.db.appointments
            if row.get("retorno_retrabalho_qualidade")
        )
        self.assertEqual(retorno["quantidade"], 3)
        self.assertEqual(retorno["catalogo_operacao_id"], 501)

    def test_abertura_reutiliza_a_sessao_existente_sem_duplicar(self):
        primeiro = self._abrir()
        segundo = self.service.abrir_inspecao(self.OP, "Dobra")
        self.assertTrue(segundo.ok, segundo.message)
        self.assertEqual(segundo.data["id"], primeiro["id"])
        self.assertEqual(len(self.db.quality_inspections), 1)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class QualityPostgresTests(unittest.TestCase):
    """Vínculo canônico com a operação INSPECAO e garantias do banco."""

    OP = "A9716901001"

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_etapa7c_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
            )
        self.admin_dsn = base.dsn
        # Relógio compartilhado por todo o teste: a outbox ligada abaixo ativa
        # a duração mínima de 60s entre Início e Finalizado (A680HORA), e
        # avançamos este relógio manualmente para não depender de tempo de
        # parede real.
        self.clock = {"now": datetime(2026, 1, 1, 8, 0, 0)}
        # A outbox é ligada explicitamente no schema descartável: é assim que a
        # obrigação outbound fica observável sem depender do .env do workspace.
        self.db = Database(
            make_conninfo(base.dsn, options=f"-c search_path={self.schema}"),
            totvs_outbox_config=OutboundEnqueueConfig(enabled=True),
        )
        self.db.publicar_recursos_pcfactory(RECURSOS_CANONICOS)
        self.ingestion = TotvsProductionOrderIngestionService(
            self.db,
            enabled=True,
            parser=TotvsMessageParser(),
            mapper=TotvsProductionOrderMapper(
                TotvsResourceResolver(
                    known_resource_codes=self.db.listar_codigos_recursos_totvs(),
                    known_resource_sectors=self.db.listar_setores_recursos_totvs(),
                )
            ),
        )
        self.ingestion.ingest(REAL_OP.read_text(encoding="utf-8"))
        self.db.cadastrar_operador_apontamento("77", "Inspetor", fonte="teste")
        # O schema descartável não recebe o catálogo PCFactory do ambiente.
        # Publica somente o status mínimo necessário para exercitar a máquina
        # de estados de retrabalho sem depender de dado externo de TESTE.
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO catalogo_status_recursos (
                    codigo, nome, grupo_codigo, grupo_nome, habilitado,
                    setup, retrabalho, oculto, requer_comentario, fonte, sincronizado_em
                ) VALUES (
                    '0401', 'RETRABALHO', '0004', 'RETRABALHO', TRUE,
                    FALSE, TRUE, FALSE, FALSE, 'teste_isolado', CURRENT_TIMESTAMP
                )
                """
            )
        self.service = QualityInspectionService(
            self.db, "INSPETOR", now_func=lambda: self.clock["now"]
        )

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _concluir_roteiro(self):
        # A outbox nasce ligada neste schema (ver setUp), o que ativa a
        # duração mínima de 60s entre Início e Finalizado (A680HORA). O
        # relógio compartilhado da classe avança o suficiente entre as duas
        # chamadas para não depender de tempo de parede real no teste.
        flow = OperatorFlowService(self.db, "OPERADOR", now_func=lambda: self.clock["now"])
        for setor, recurso in (("Corte", "Plasma TerraBlade 4"), ("Usinagem", "Romi D 1000")):
            operacao = next(
                row for row in self.db.listar_operacoes_para_op(self.OP)
                if row["tipo_setor"] == setor
            )
            liberar_primeira_peca(
                self.db,
                "OPERADOR",
                op=self.OP,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
            )
            flow.executar("Início", op=self.OP, setor=setor, recurso=recurso, operacao=operacao)
            self.clock["now"] += timedelta(seconds=90)
            resultado = flow.executar(
                "Finalizado",
                op=self.OP,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
                pecas_boas=10,
                operadores_cracha=["77"],
            )
            self.assertTrue(resultado.ok, resultado.message)

    # O roteiro desta OP é Corte → Usinagem → INSPEC: a inspeção pertence à
    # Usinagem, que é a última etapa apontável antes dela.
    def test_operacao_inspecao_e_projetada_inativa_e_vira_vinculo_canonico(self):
        inspecao = self.db.buscar_operacao_inspecao(self.OP)
        self.assertIsNotNone(inspecao)
        self.assertEqual(inspecao["numero_operacao"], "30")
        self.assertEqual(inspecao["codigo_recurso"], "INSPEC")
        self.assertEqual(inspecao["totvs_activity_id"], "108763")
        self.assertFalse(inspecao["ativo"])
        self.assertIsNone(inspecao["tipo_setor"])
        # A Tela do Operador continua cega para ela.
        self.assertNotIn(
            "30",
            [row["numero_operacao"] for row in self.db.listar_operacoes_para_op(self.OP)],
        )

        self._concluir_roteiro()
        abertura = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.clock["now"] += timedelta(seconds=90)
        self.assertTrue(abertura.ok, abertura.message)

        # A inspeção usa o MESMO apontamento canônico do operador.
        apontamento = self._rows(
            """
            SELECT a.id, a.op, a.tipo_setor, a.maquina, a.status, a.numero_operacao,
                   a.catalogo_operacao_id
            FROM apontamentos_operacionais a
            WHERE a.tipo_setor = %s
            """,
            (QUALITY_APPOINTMENT_SECTOR,),
        )
        self.assertEqual(len(apontamento), 1)
        self.assertEqual(apontamento[0]["numero_operacao"], "30")
        self.assertEqual(apontamento[0]["maquina"], "INSPEC")
        self.assertEqual(apontamento[0]["status"], "Em processo")
        self.assertEqual(apontamento[0]["catalogo_operacao_id"], inspecao["id"])

        sessao = self.db.buscar_inspecao_aberta(self.OP, "30")
        self.assertEqual(sessao["apontamento_id"], apontamento[0]["id"])

    def test_cotas_e_rnc_nao_geram_outbound_e_a_conclusao_usa_o_fluxo_canonico(self):
        self._concluir_roteiro()
        abertura = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.clock["now"] += timedelta(seconds=90)
        inspecao_id = abertura.data["id"]
        self.service.definir_template(
            abertura.data["produto"], _cotas("125,0 ± 0,5")
        )

        eventos_antes = self._rows(
            "SELECT COUNT(*) AS total FROM eventos_apontamento_operador e "
            "JOIN apontamentos_operacionais a ON a.id = e.apontamento_id "
            "WHERE a.tipo_setor = %s",
            (QUALITY_APPOINTMENT_SECTOR,),
        )[0]["total"]
        # As operações produtivas anteriores já produziram sua obrigação; o que
        # se mede aqui é o delta causado pela Qualidade.
        outbox_antes = self._rows("SELECT COUNT(*) AS total FROM totvs_outbox")[0]["total"]

        total = self.db.buscar_inspecao_qualidade(inspecao_id)["quantidade_total"]
        for numero in range(1, total):
            resposta = self.service.registrar_peca(
                inspecao_id,
                numero_peca=numero,
                resultado="RETRABALHO" if numero == 2 else "APROVADA",
                medidas=_medidas(
                    ("131,0", "NAO_CONFORME") if numero == 2 else ("124,9", "CONFORME")
                ),
                rnc={"motivo": "Fora do padrão"} if numero == 2 else None,
            )
            self.assertTrue(resposta.ok, resposta.message)

        # Preencher cota e abrir RNC não criam evento canônico nem outbound.
        self.assertEqual(
            self._rows(
                "SELECT COUNT(*) AS total FROM eventos_apontamento_operador e "
                "JOIN apontamentos_operacionais a ON a.id = e.apontamento_id "
                "WHERE a.tipo_setor = %s",
                (QUALITY_APPOINTMENT_SECTOR,),
            )[0]["total"],
            eventos_antes,
        )
        self.assertEqual(
            self._rows("SELECT COUNT(*) AS total FROM totvs_outbox")[0]["total"],
            outbox_antes,
        )

        ultima = self.service.registrar_peca(
            inspecao_id,
            numero_peca=total,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
            badges=["77"],
        )
        self.assertTrue(ultima.ok, ultima.message)
        self.assertEqual(ultima.code, "inspecao_concluida")
        # Uma peça foi para retrabalho: somente peça boa reduz o planejado, então
        # a operação fica parcialmente finalizada com saldo de 1.
        self.assertFalse(ultima.data["operacao_finalizada"])
        self.assertEqual(ultima.data["saldo_restante"], 1)

        apontamento = self._rows(
            "SELECT id, status, quantidade_boa, quantidade_refugo, "
            "quantidade_retrabalho FROM apontamentos_operacionais WHERE tipo_setor = %s",
            (QUALITY_APPOINTMENT_SECTOR,),
        )
        self.assertEqual(len(apontamento), 1)
        self.assertEqual(apontamento[0]["quantidade_boa"], total - 1)
        self.assertEqual(apontamento[0]["quantidade_retrabalho"], 1)

        # Enquanto o retorno produtivo está pendente, a inspeção concluída não
        # permanece artificialmente na fila da Qualidade.
        fila = self.service.listar_fila("Usinagem")["items"]
        self.assertEqual(fila, [])
        retorno = self._rows(
            "SELECT * FROM apontamentos_operacionais "
            "WHERE retorno_retrabalho_qualidade IS TRUE"
        )
        self.assertEqual(len(retorno), 1)
        self.assertEqual(retorno[0]["tipo_setor"], "Usinagem")
        self.assertEqual(retorno[0]["status"], "Aguardando")
        self.assertEqual(retorno[0]["quantidade"], 1)
        vinculo = self._rows(
            "SELECT retrabalho_apontamento_id FROM qualidade_pecas_inspecionadas "
            "WHERE resultado = 'RETRABALHO'"
        )
        self.assertEqual(vinculo[0]["retrabalho_apontamento_id"], retorno[0]["id"])

        ordem_inspecao = self.db.buscar_operacao_inspecao(self.OP)["ordem"]
        anterior = self.db.buscar_operacao_produtiva_anterior(
            self.OP, ordem_inspecao
        )
        fluxo = OperatorFlowService(
            self.db, "OPERADOR USINAGEM", now_func=lambda: self.clock["now"]
        )
        iniciado = fluxo.executar(
            "Retrabalho", op=self.OP, setor="Usinagem", recurso="Romi D 1000",
            operacao=anterior,
        )
        self.assertTrue(iniciado.ok, iniciado.message)
        self.clock["now"] += timedelta(seconds=90)
        concluido = fluxo.executar(
            "Finalizado", op=self.OP, setor="Usinagem", recurso="Romi D 1000",
            operacao=anterior, pecas_boas=1, operadores_cracha=["77"],
        )
        self.assertTrue(concluido.ok, concluido.message)

        # Concluído o retrabalho, o saldo volta à inspeção e continua no
        # mesmo apontamento canônico da operação INSPECAO.
        reaberta = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.assertTrue(reaberta.ok, reaberta.message)
        self.clock["now"] += timedelta(seconds=90)
        final = self.service.registrar_peca(
            reaberta.data["id"],
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
            badges=["77"],
        )
        self.assertTrue(final.ok, final.message)
        self.assertTrue(final.data["operacao_finalizada"])

        # O fechamento é o fluxo canônico: mesmo apontamento, agora finalizado,
        # com o evento canônico que alimenta a outbox homologada.
        fechado = self._rows(
            "SELECT id, status, quantidade_boa FROM apontamentos_operacionais "
            "WHERE tipo_setor = %s",
            (QUALITY_APPOINTMENT_SECTOR,),
        )
        self.assertEqual(len(fechado), 1)
        self.assertEqual(fechado[0]["id"], apontamento[0]["id"])
        self.assertEqual(fechado[0]["status"], "Finalizado")
        self.assertEqual(fechado[0]["quantidade_boa"], total)
        self.assertEqual(
            self._rows(
                "SELECT COUNT(*) AS total FROM eventos_apontamento_operador e "
                "JOIN apontamentos_operacionais a ON a.id = e.apontamento_id "
                "WHERE a.tipo_setor = %s AND e.estado = 'finalizado'",
                (QUALITY_APPOINTMENT_SECTOR,),
            )[0]["total"],
            1,
        )
        self.assertEqual(self.service.listar_fila("Usinagem")["items"], [])

    def test_conclusao_gera_a_obrigacao_outbound_da_operacao_inspecao(self):
        """O movimento empresarial vem do fluxo canônico, não de um transporte novo."""

        self._concluir_roteiro()
        abertura = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.clock["now"] += timedelta(seconds=90)
        inspecao_id = abertura.data["id"]
        self.service.definir_template(abertura.data["produto"], _cotas("125,0 ± 0,5"))
        total = self.db.buscar_inspecao_qualidade(inspecao_id)["quantidade_total"]

        outbox_antes = self._rows(
            "SELECT event_type, operation_code FROM totvs_outbox ORDER BY id"
        )
        for numero in range(1, total):
            self.service.registrar_peca(
                inspecao_id,
                numero_peca=numero,
                resultado="APROVADA",
                medidas=_medidas(("124,9", "CONFORME")),
            )
        # Cota preenchida não é movimento empresarial.
        self.assertEqual(
            self._rows("SELECT event_type, operation_code FROM totvs_outbox ORDER BY id"),
            outbox_antes,
        )

        final = self.service.registrar_peca(
            inspecao_id,
            numero_peca=total,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
            badges=["77"],
        )
        self.assertTrue(final.ok, final.message)
        self.assertTrue(final.data["operacao_finalizada"])

        novos = [
            row for row in self._rows(
                "SELECT event_type, operation_code, transaction, payload_xml, "
                "idempotency_key FROM totvs_outbox ORDER BY id"
            )
            if (row["event_type"], row["operation_code"])
            not in {(item["event_type"], item["operation_code"]) for item in outbox_antes}
        ]
        inspecao_outbound = [
            row for row in novos
            if row["event_type"] == "production_appointment"
            and row["operation_code"] == "30"
        ]
        self.assertEqual(len(inspecao_outbound), 1)
        item = inspecao_outbound[0]
        self.assertEqual(item["transaction"], "productionappointment")
        self.assertIn("<ActivityCode>30</ActivityCode>", item["payload_xml"])
        self.assertIn("<MachineCode>INSPEC</MachineCode>", item["payload_xml"])

        # Idempotência: a mesma obrigação lógica não pode ser duplicada.
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO totvs_outbox (
                        event_type, aggregate_type, aggregate_id, idempotency_key,
                        transaction, production_order, operation_code, payload_xml,
                        status, next_attempt_at
                    ) VALUES (
                        'production_appointment', 'execution_event', %s, %s,
                        'productionappointment', %s, '30', '<x/>', 'PENDING',
                        CURRENT_TIMESTAMP
                    )
                    """,
                    (self.OP, item["idempotency_key"], self.OP),
                )

    def test_banco_recusa_unidade_duplicada_e_aprovacao_nao_conforme(self):
        self._concluir_roteiro()
        abertura = self.service.abrir_inspecao(self.OP, "Usinagem")
        self.clock["now"] += timedelta(seconds=90)
        inspecao_id = abertura.data["id"]
        self.service.definir_template(abertura.data["produto"], _cotas("125,0 ± 0,5"))
        self.service.registrar_peca(
            inspecao_id,
            numero_peca=1,
            resultado="APROVADA",
            medidas=_medidas(("124,9", "CONFORME")),
        )

        # A unicidade da unidade é do banco, não do frontend.
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qualidade_pecas_inspecionadas (
                        inspecao_id, numero_peca, resultado, operador
                    ) VALUES (%s, 1, 'APROVADA', 'OUTRO')
                    """,
                    (inspecao_id,),
                )
        # Peça não conforme aprovada é recusada pela constraint.
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qualidade_pecas_inspecionadas (
                        inspecao_id, numero_peca, resultado,
                        possui_nao_conformidade, operador
                    ) VALUES (%s, 2, 'APROVADA', TRUE, 'OUTRO')
                    """,
                    (inspecao_id,),
                )

    def test_uma_unica_inspecao_aberta_por_op(self):
        self._concluir_roteiro()
        self.service.abrir_inspecao(self.OP, "Usinagem")
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO qualidade_inspecoes (
                        codigo_op, numero_operacao, produto_codigo, tipo_setor,
                        codigo_recurso, quantidade_total, status, operador
                    ) VALUES (%s, '30', 'X', %s, 'INSPEC', 1, 'EM_INSPECAO', 'OUTRO')
                    """,
                    (self.OP, QUALITY_APPOINTMENT_SECTOR),
                )


if __name__ == "__main__":
    unittest.main()
