"""Etapa 3 — planejamento TOTVS entrando na fila e na Tela do Operador atuais.

A lógica de apontamento do Gestor é canônica. Estes testes provam que uma OP
originada no TOTVS percorre exatamente os mesmos serviços, filas, estados e
eventos das demais OPs, sem criar caminho paralelo, tabela paralela ou branch
de execução por origem.

Todo acesso a PostgreSQL usa um schema descartável criado dentro de
``TEST_DATABASE_URL``. Nenhum teste escreve no banco REAL.
"""

from datetime import datetime
import os
from pathlib import Path
import re
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.operator_sectors import OPERATOR_SECTOR_BY_ROUTE, OPERATOR_SECTORS
from app.core.permissions import USER_LEVELS, navigation_for_level
from app.core.resource_mapping import (
    SECTOR_OWNED_RESOURCE_SECTORS,
    resource_display_name,
    station_matches_route,
)
from app.database.config import load_postgres_config
from app.database.database import Database
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import (
    OFFICIAL_RESOURCE_ALIASES,
    RESOURCE_OWNED_POINTABLE_SECTORS,
    TotvsResourceResolver,
)
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService
from mes.services.cut import CutService
from mes.services.operator_flow import OperatorFlowService
from mes.services.production import ProductionService
from mes.services.quality import QualityInspectionService
from tests.wave5_helpers import liberar_primeira_peca


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "totvs"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"
PEND_OP = FIXTURES / "pend_productionorder_20260818165346_10796502001.xml"

# Cadastro mínimo e exato espelhando o catálogo oficial de TESTE. Somente
# códigos reais; nenhum recurso é inventado para fazer teste passar.
RECURSOS_CANONICOS = (
    {"codigo": "PLASMA", "nome": "Plasma TerraBlade 4", "tipo_setor": "Corte"},
    {"codigo": "LASER1", "nome": "Laser Ensis 3015", "tipo_setor": "Corte"},
    {"codigo": "CNC-01", "nome": "Romi D 1000", "tipo_setor": "Usinagem"},
    {"codigo": "CNC-02", "nome": "Eurostec", "tipo_setor": "Usinagem"},
    {"codigo": "PINT.L", "nome": "Pintura", "tipo_setor": "Pintura"},
    {"codigo": "INSPE2", "nome": "Inspeção de Pintura", "tipo_setor": "Pintura"},
    {"codigo": "PREP", "nome": "Preparação", "tipo_setor": "Pintura"},
    {"codigo": "ESTUFA", "nome": "Estufa", "tipo_setor": "Pintura"},
    {"codigo": "RETOQ", "nome": "Retoque", "tipo_setor": "Pintura"},
    {"codigo": "TINTA", "nome": "Tinta", "tipo_setor": "Pintura"},
    # JATO permanece com tipo_setor nulo no cadastro; a associação a Pintura
    # foi validada diretamente pela Manufatura.
    {"codigo": "JATO", "nome": "Jateamento", "tipo_setor": None},
    {"codigo": "SOLDA4", "nome": "Solda", "tipo_setor": "Solda"},
    {"codigo": "MT NT", "nome": "MONT SOLDA TILLER", "tipo_setor": "Solda"},
    # Recursos cujo nome lembra Montagem, porém sem pertencimento cadastral.
    {"codigo": "MPRT1", "nome": "MONTAGEM", "tipo_setor": None},
    {"codigo": "MONTAGEM PM05", "nome": "MONTAGEM PM 05", "tipo_setor": None},
)


def _isolated_database():
    base = load_postgres_config(testing=True)
    schema = "gestor_etapa3_" + uuid4().hex
    with psycopg.connect(base.dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(base.dsn, options=f"-c search_path={schema}")
    return Database(isolated), base.dsn, schema


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TotvsOperatorQueuePostgresTests(unittest.TestCase):
    """Fronteira ProductionOrder → catálogo → fila → Tela do Operador."""

    def setUp(self):
        self.db, self.admin_dsn, self.schema = _isolated_database()
        self.db.publicar_recursos_pcfactory(RECURSOS_CANONICOS)
        self.service = TotvsProductionOrderIngestionService(
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
        self.flow = OperatorFlowService(self.db, "OPERADOR ETAPA 3")

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema))
            )

    # ------------------------------------------------------------------
    # Utilitários de fixture
    # ------------------------------------------------------------------
    @staticmethod
    def _real_payload() -> str:
        return REAL_OP.read_text(encoding="utf-8")

    @classmethod
    def _payload_sem_corte(cls, numero="B0000000001") -> str:
        """Mesma OP real sem a atividade de CORTE, preservando o contrato."""

        raw = cls._real_payload()
        corte = re.search(
            r"<ActivityOrder>(?:(?!</ActivityOrder>).)*?"
            r"<ActivityID>108761</ActivityID>.*?</ActivityOrder>",
            raw,
            re.S,
        )
        assert corte is not None, "fixture real perdeu a atividade de CORTE"
        return (
            raw.replace(corte.group(0), "")
            .replace("A9716901001", numero)
            .replace("<UUID>1</UUID>", f"<UUID>{numero}</UUID>")
        )

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _scalar(self, query, params=()):
        return next(iter(self._rows(query, params)[0].values()))

    def _fila(self, setor, recurso):
        cards = self.flow.listar_cartoes(setor, recurso)
        return [
            (str(card.get("op") or ""), str(card.get("operation") or ""))
            for card in cards["queue"]
        ]

    def _seed_execucao(self):
        """Catálogo mínimo de motivos e crachá, usados por qualquer OP."""

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
                -- Wave 6B: refugo exige crachá de responsável autorizado.
                INSERT INTO operadores_apontamento
                    (cracha, nome, ativo, fonte, autorizador_retrabalho)
                VALUES ('9001', 'OPERADOR ETAPA 3', TRUE, 'teste', TRUE)
                """
            )

    def _seed_rota_manual(self, codigo_op, operacoes, quantidade=10):
        """Cria uma OP e um roteiro mínimos direto no catálogo canônico.

        Usado apenas para isolar a regra de elegibilidade posto/setor sem
        depender de um XML corporativo específico.
        """

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
            for operacao in operacoes:
                cursor.execute(
                    """
                    INSERT INTO catalogo_operacoes_op (
                        codigo_op, produto_codigo, produto_descricao,
                        numero_operacao, codigo_recurso, descricao_operacao,
                        tipo_setor, ordem, fonte, ativo, sincronizado_em
                    ) VALUES (
                        %s, 'PROD-1', 'PRODUTO DE TESTE',
                        %s, %s, %s, %s, %s, 'teste_etapa3', TRUE, %s
                    )
                    """,
                    (
                        codigo_op,
                        operacao["numero_operacao"],
                        operacao["codigo_recurso"],
                        operacao["descricao_operacao"],
                        operacao["tipo_setor"],
                        operacao["ordem"],
                        agora,
                    ),
                )

    def _quantidade_da_op(self, codigo_op):
        return int(
            self._scalar(
                "SELECT quantidade FROM catalogo_pcp_ops WHERE codigo_op = %s",
                (codigo_op,),
            )
        )

    def _executar_etapa_completa(self, codigo_op, setor, posto, numero_operacao=None):
        """Roda Início → Finalizado de uma etapa pelo serviço canônico."""

        operacoes = self.db.listar_operacoes_para_op(codigo_op)
        if numero_operacao is not None:
            operacao = next(
                item for item in operacoes
                if item["numero_operacao"] == numero_operacao
            )
        else:
            projetadas = {
                row["id"]
                for row in self.db.listar_proximas_operacoes_roteiro(setor)
                if row["codigo_op"] == codigo_op
            }
            operacao = next(item for item in operacoes if item["id"] in projetadas)
        contexto = dict(op=codigo_op, setor=setor, recurso=posto, operacao=operacao)
        # Wave 6B: em Dobra/Usinagem/Serra o portão Setup/Qualidade antecede a
        # produção; a etapa também só fecha com a primeira peça aprovada.
        liberar_primeira_peca(self.db, "OPERADOR TOTVS", **contexto)
        inicio = self.flow.executar("Início", **contexto)
        self.assertTrue(inicio.ok, inicio.message)
        fim = self.flow.executar(
            "Finalizado",
            **contexto,
            pecas_boas=self._quantidade_da_op(codigo_op),
            operadores_cracha=["9001"],
        )
        self.assertTrue(fim.ok, fim.message)
        return operacao

    def _concluir_ate_pintura(self, codigo_op):
        """Conclui Corte (nesting) e Dobra para liberar a primeira etapa de Pintura."""

        self._seed_execucao()
        tarefa = self._publicar_nesting_do_corte(codigo_op, codigo_tarefa="TSK-PINT")
        # O Corte precede o Destaque: só um plano de Laser concluído libera o
        # posto. Apontar o Destaque antes do Corte é recusado com
        # ``destaque_nao_liberado``, como na fábrica.
        cut = CutService(self.db, "OPERADOR CORTE", cutoff_date="2026-08-01")
        self.assertTrue(cut.iniciar("plano-1", "Laser Ensis 3015").ok)
        ativo = next(
            row
            for row in self.db.listar_fila_corte("2026-08-01", maquina_sigmanest="AMADA_ENSIS")
            if row["status"] == "Em processo"
        )
        self.assertTrue(cut.finalizar(ativo["id"]).ok)
        destaque = ProductionService(self.db, "OPERADOR DESTAQUE")
        self.assertTrue(
            destaque.registrar_destacando(tarefa["id"], "TSK-PINT").ok
        )
        self.assertTrue(
            destaque.registrar_finalizado(tarefa["id"], "TSK-PINT").ok
        )
        self._executar_etapa_completa(codigo_op, "Dobra", "Gasparini", "20")
        qualidade = QualityInspectionService(self.db, "INSPETOR")
        inspecao = qualidade.abrir_inspecao(codigo_op, "Dobra", badges=["9001"])
        self.assertTrue(inspecao.ok, inspecao.message)
        produto = inspecao.data["produto"]
        template = qualidade.definir_template(
            produto,
            [{"sequencia": 1, "descricao": "Controle", "padrao": "10,0", "unidade": "mm"}],
        )
        self.assertTrue(template.ok, template.message)
        total = int(inspecao.data["quantidade_total"])
        for numero in range(1, total + 1):
            resultado = qualidade.registrar_peca(
                inspecao.data["id"],
                numero_peca=numero,
                resultado="APROVADA",
                medidas=[{"sequencia": 1, "medida": "10,0", "status": "CONFORME"}],
                badges=["9001"] if numero == total else None,
            )
            self.assertTrue(resultado.ok, resultado.message)

    def _finalizar_etapa_de_pintura(self, codigo_op):
        self._executar_etapa_completa(codigo_op, "Pintura", "Pintura")

    def _publicar_nesting_do_corte(self, codigo_op, codigo_tarefa="TSK-ETAPA3"):
        """Planejamento de Corte pela fonte existente (SIGMANEST/nesting)."""

        self.db.publicar_catalogo_sigmanest(
            tarefas=[{"codigo_tarefa": codigo_tarefa, "material": "A36", "espessura": 6.35}],
            programas=[{"codigo_tarefa": codigo_tarefa, "programa": "PRG-1"}],
            ops=[
                {
                    "linha_hash": "linha-1",
                    "codigo_tarefa": codigo_tarefa,
                    "codigo_op": codigo_op,
                    "id_peca": "PECA-1",
                    "setor_destino": "Usinagem",
                    "quantidade": 10,
                }
            ],
            planos_corte=[
                {
                    "plano_hash": "plano-1",
                    "codigo_tarefa": codigo_tarefa,
                    "programa": "PRG-1",
                    "sequencia_nesting": 1,
                    "maquina_sigmanest": (
                        "AMADA_ENSIS" if codigo_tarefa == "TSK-PINT" else "MESSER_XPR_300"
                    ),
                    "data_programa": "2026-08-27",
                    "quantidade_processo": 1,
                }
            ],
        )
        return self.db.materializar_tarefa_catalogo(codigo_tarefa)

    # ------------------------------------------------------------------
    # 3C — a OP TOTVS entra no contrato de fila já existente
    # ------------------------------------------------------------------
    def test_op_totvs_entra_na_fila_canonica_do_recurso_correto(self):
        result = self.service.ingest(self._payload_sem_corte())
        self.assertEqual(result.status, "processed")
        self.assertEqual(result.activities_projected, 1)

        projetadas = self.db.listar_proximas_operacoes_roteiro("Usinagem")
        self.assertEqual(
            [(row["codigo_op"], row["numero_operacao"], row["codigo_recurso"]) for row in projetadas],
            [("B0000000001", "20", "CNC-01")],
        )

        cards = self.flow.listar_cartoes("Usinagem", "Romi D 1000")
        self.assertEqual(len(cards["queue"]), 1)
        card = cards["queue"][0]
        self.assertEqual(card["op"], "B0000000001")
        self.assertEqual(card["operation"], "20 - USINAGEM")
        self.assertEqual(card["product"], "PNT002002003")
        self.assertEqual(card["description"], "BRACO ARTICULACAO")
        self.assertEqual(int(card["qty"]), 10)
        self.assertTrue(card["virtual_queue"])
        self.assertEqual(cards["production"], [])

        # Recurso incompatível do mesmo setor não recebe a OP.
        self.assertEqual(self._fila("Usinagem", "Eurostec"), [])
        # Nenhum apontamento foi criado apenas por projetar a fila.
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM apontamentos_operacionais"), 0
        )

    def test_op_real_a9716901001_respeita_a_sequencia_e_o_fluxo_de_corte_existente(self):
        self.service.ingest(self._real_payload())

        roteiro = self.db.listar_operacoes_para_op("A9716901001")
        self.assertEqual(
            [(row["numero_operacao"], row["tipo_setor"], row["codigo_recurso"]) for row in roteiro],
            [("10", "Corte", "PLASMA"), ("20", "Usinagem", "CNC-01")],
        )

        # Sem nesting publicado, a etapa de Corte não é elegível e a Usinagem
        # continua bloqueada pela sequência. Nada é forçado para a fila.
        cut = CutService(self.db, "OPERADOR CORTE", cutoff_date="2026-08-01")
        self.assertEqual(cut.listar_fila("Plasma TerraBlade 4"), [])
        self.assertEqual(self.db.listar_proximas_operacoes_roteiro("Usinagem"), [])
        self.assertEqual(self._fila("Usinagem", "Romi D 1000"), [])

        # O planejamento de Corte chega pela fonte existente de nesting.
        self._publicar_nesting_do_corte("A9716901001")
        fila_corte = cut.listar_fila("Plasma TerraBlade 4")
        self.assertEqual([row["codigo_tarefa"] for row in fila_corte], ["TSK-ETAPA3"])
        self.assertEqual(fila_corte[0]["status"], "Aguardando")
        # A fila do LASER continua vazia: o nesting pertence ao PLASMA.
        self.assertEqual(cut.listar_fila("Laser Ensis 3015"), [])

        self.assertTrue(cut.iniciar("plano-1", "Plasma TerraBlade 4").ok)
        ativo = next(
            row
            for row in self.db.listar_fila_corte("2026-08-01", maquina_sigmanest="MESSER_XPR_300")
            if row["status"] == "Em processo"
        )
        self.assertTrue(cut.finalizar(ativo["id"]).ok)

        # Concluído o Corte pelo caminho canônico, a Usinagem é liberada.
        self.assertEqual(
            [
                (row["codigo_op"], row["numero_operacao"], row["codigo_recurso"])
                for row in self.db.listar_proximas_operacoes_roteiro("Usinagem")
            ],
            [("A9716901001", "20", "CNC-01")],
        )
        self.assertEqual(
            self._fila("Usinagem", "Romi D 1000"),
            [("A9716901001", "20 - USINAGEM")],
        )
        self.assertEqual(self._fila("Usinagem", "Eurostec"), [])

    def test_etapas_nao_apontaveis_nao_viram_fila_nem_finalizam_a_op(self):
        result = self.service.ingest(self._real_payload())
        self.assertEqual(result.activities_parsed, 5)
        self.assertEqual(result.activities_projected, 2)

        numeros = {
            row["numero_operacao"]
            for row in self.db.listar_operacoes_para_op("A9716901001")
        }
        # IMPRESSAO OP, INSPECAO e FINALIZADA não entram no roteiro do posto.
        self.assertEqual(numeros, {"10", "20"})

        # A inspeção existe no catálogo como metadado do roteiro, inativa: ela
        # alimenta a aba Qualidade e o outbound, nunca a fila do operador.
        inspecao = self._rows(
            "SELECT numero_operacao, ativo, tipo_setor, codigo_recurso, "
            "totvs_activity_id FROM catalogo_operacoes_op "
            "WHERE codigo_op = %s AND inspecao_qualidade IS TRUE",
            ("A9716901001",),
        )
        self.assertEqual(len(inspecao), 1)
        self.assertEqual(inspecao[0]["numero_operacao"], "30")
        self.assertFalse(inspecao[0]["ativo"])
        self.assertIsNone(inspecao[0]["tipo_setor"])
        self.assertEqual(inspecao[0]["codigo_recurso"], "INSPEC")
        self.assertEqual(inspecao[0]["totvs_activity_id"], "108763")

        diagnostico = " | ".join(result.warnings)
        self.assertIn("AUTOMÁTICA/NÃO MANUAL SATISFEITA", diagnostico)
        self.assertIn("INSPEÇÃO DE QUALIDADE CONFIRMADA", diagnostico)
        self.assertIn("ETAPA TERMINAL CONFIRMADA", diagnostico)

        # O marco terminal não finaliza a OP durante a ingestão.
        self.assertTrue(
            self._scalar(
                "SELECT ativo FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("A9716901001",),
            )
        )
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM apontamentos_operacionais"), 0
        )
        # Nenhuma etapa não apontável alcança qualquer fila operacional.
        for setor in ("Usinagem", "Serra", "Dobra", "Pintura", "Solda", "Montagem"):
            self.assertEqual(self.db.listar_proximas_operacoes_roteiro(setor), [])

    def test_marco_terminal_e_persistido_mas_invisivel_para_o_operador(self):
        """O 99/ALMOX4 existe no roteiro para o outbound e nunca vira posto."""

        self.service.ingest(self._real_payload())

        terminal = self._rows(
            "SELECT numero_operacao, codigo_recurso, tipo_setor, ativo, "
            "marco_terminal, totvs_activity_id, totvs_machine_code "
            "FROM catalogo_operacoes_op "
            "WHERE codigo_op = %s AND marco_terminal IS TRUE",
            ("A9716901001",),
        )
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["numero_operacao"], "99")
        self.assertEqual(terminal[0]["codigo_recurso"], "ALMOX4")
        self.assertEqual(terminal[0]["totvs_machine_code"], "ALMOX4")
        self.assertEqual(terminal[0]["totvs_activity_id"], "128285")
        self.assertIsNone(terminal[0]["tipo_setor"])
        # Inativo: todas as consultas do operador filtram ativo IS TRUE.
        self.assertFalse(terminal[0]["ativo"])

        # Não aparece no roteiro da OP nem em nenhuma fila de posto.
        self.assertEqual(
            {
                row["numero_operacao"]
                for row in self.db.listar_operacoes_para_op("A9716901001")
            },
            {"10", "20"},
        )
        for setor in ("Corte", "Usinagem", "Serra", "Dobra", "Pintura", "Solda"):
            for item in self.db.listar_proximas_operacoes_roteiro(setor):
                self.assertNotEqual(item.get("numero_operacao"), "99")
                self.assertNotEqual(item.get("codigo_recurso"), "ALMOX4")

    def test_fila_ignora_operacao_inativa_e_op_inativa_sem_perder_rastreabilidade(self):
        self.service.ingest(self._payload_sem_corte())
        self.assertEqual(len(self._fila("Usinagem", "Romi D 1000")), 1)

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET ativo = FALSE "
                "WHERE codigo_op = %s AND marco_terminal IS FALSE "
                "AND inspecao_qualidade IS FALSE",
                ("B0000000001",),
            )
        self.assertEqual(self._fila("Usinagem", "Romi D 1000"), [])

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                # Marco terminal e inspeção da Qualidade jamais podem ser
                # reativados: a constraint ck_catalogo_operacao_marco_terminal
                # recusaria as linhas.
                "UPDATE catalogo_operacoes_op SET ativo = TRUE "
                "WHERE codigo_op = %s AND marco_terminal IS FALSE "
                "AND inspecao_qualidade IS FALSE",
                ("B0000000001",),
            )
            cursor.execute(
                "UPDATE catalogo_pcp_ops SET ativo = FALSE WHERE codigo_op = %s",
                ("B0000000001",),
            )
        self.assertEqual(self._fila("Usinagem", "Romi D 1000"), [])
        # O roteiro recebido continua auditável mesmo com a OP inativa.
        self.assertEqual(len(self.db.listar_operacoes_para_op("B0000000001")), 1)
        # A tentativa de tornar o marco terminal apontável é recusada pelo banco.
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE catalogo_operacoes_op SET ativo = TRUE "
                    "WHERE codigo_op = %s AND marco_terminal IS TRUE",
                    ("B0000000001",),
                )
        # A operação de inspeção também é recusada como etapa de bancada.
        with self.assertRaises(Exception):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE catalogo_operacoes_op SET ativo = TRUE "
                    "WHERE codigo_op = %s AND inspecao_qualidade IS TRUE",
                    ("B0000000001",),
                )

    def test_reenvio_do_production_order_nao_duplica_operacao_nem_fila(self):
        payload = self._payload_sem_corte()
        primeiro = self.service.ingest(payload)
        self.assertEqual(primeiro.action, "inserted")

        repetido = self.service.ingest(payload)
        self.assertTrue(repetido.idempotent)

        atualizado = self.service.ingest(
            payload.replace(
                "<GeneratedOn>2026-08-27T12:02:32</GeneratedOn>",
                "<GeneratedOn>2026-08-27T13:02:32</GeneratedOn>",
            )
        )
        self.assertEqual(atualizado.action, "updated")

        operacoes = self._rows(
            "SELECT id, numero_operacao, ativo, marco_terminal, inspecao_qualidade "
            "FROM catalogo_operacoes_op WHERE codigo_op = %s ORDER BY ordem",
            ("B0000000001",),
        )
        apontaveis = [
            item for item in operacoes
            if not item["marco_terminal"] and not item["inspecao_qualidade"]
        ]
        terminais = [item for item in operacoes if item["marco_terminal"]]
        self.assertEqual(len(apontaveis), 1)
        self.assertTrue(apontaveis[0]["ativo"])
        # O reenvio não duplica nem reativa o marco terminal.
        self.assertEqual(len(terminais), 1)
        self.assertFalse(terminais[0]["ativo"])
        self.assertEqual(terminais[0]["numero_operacao"], "99")
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("B0000000001",),
            ),
            1,
        )
        self.assertEqual(
            self._fila("Usinagem", "Romi D 1000"),
            [("B0000000001", "20 - USINAGEM")],
        )

    def test_roteiro_multissetor_usa_alias_e_cadastro_canonicos_sem_inventar_montagem(self):
        result = self.service.ingest(PEND_OP.read_text(encoding="utf-8"))
        self.assertEqual(result.status, "processed")

        projetadas = [
            (row["numero_operacao"], row["tipo_setor"], row["codigo_recurso"])
            for row in self.db.listar_operacoes_para_op("10796502001")
        ]
        self.assertEqual(
            projetadas,
            [
                # Alias oficial exato LASER → LASER1.
                ("10", "Corte", "LASER1"),
                ("20", "Dobra", "DOBRA1"),
                # Pintura mantém seus recursos canônicos, inclusive JATO.
                ("40", "Pintura", "PINT.L"),
                ("50", "Pintura", "JATO"),
                ("60", "Pintura", "PINT.L"),
                ("70", "Pintura", "INSPE2"),
            ],
        )
        # INSPECAO QUALIDADE e FINALIZADA continuam fora do roteiro executável.
        self.assertNotIn("30", [item[0] for item in projetadas])
        self.assertNotIn("99", [item[0] for item in projetadas])
        # A inspeção existe, porém como metadado inativo do roteiro.
        self.assertEqual(
            [
                (row["numero_operacao"], row["codigo_recurso"], row["ativo"])
                for row in self._rows(
                    "SELECT numero_operacao, codigo_recurso, ativo "
                    "FROM catalogo_operacoes_op "
                    "WHERE codigo_op = %s AND inspecao_qualidade IS TRUE",
                    ("10796502001",),
                )
            ],
            [("30", "INSPEC", False)],
        )

        # O nome do recurso nunca cria pertencimento: MPRT1 e MONTAGEM PM05
        # estão no catálogo, porém sem tipo_setor, e não viram Montagem.
        setores = dict(self.db.listar_setores_recursos_totvs())
        self.assertNotIn("MPRT1", setores)
        self.assertNotIn("MONTAGEM PM05", setores)
        self.assertNotIn("Montagem", set(setores.values()))
        self.assertEqual(self.db.listar_proximas_operacoes_roteiro("Montagem"), [])

    def test_postos_de_pintura_e_solda_enxergam_todos_os_recursos_do_setor(self):
        """Elegibilidade por setor sem remapear a identidade do recurso."""

        self.service.ingest(PEND_OP.read_text(encoding="utf-8"))
        # A rota de Pintura da fixture usa PINT.L, JATO e INSPE2. Libera-se a
        # sequência concluindo Corte e Dobra pelo caminho canônico do roteiro.
        self._concluir_ate_pintura("10796502001")

        fila = self.flow.listar_cartoes("Pintura", "Pintura")["queue"]
        self.assertEqual(
            [(card["op"], card["operation"], card["codigo_recurso"]) for card in fila],
            [("10796502001", "40 - PREPARACAO", "PINT.L")],
        )
        # O recurso do roteiro nunca é convertido para o código do posto.
        self.assertEqual(fila[0]["codigo_recurso"], "PINT.L")
        self.assertEqual(fila[0]["maquina"], "Pintura")

        # Cada etapa seguinte de Pintura chega ao mesmo posto com seu próprio
        # recurso canônico, incluindo JATO e INSPE2.
        esperado = [("50", "JATO"), ("60", "PINT.L"), ("70", "INSPE2")]
        for numero, codigo_recurso in esperado:
            self._finalizar_etapa_de_pintura("10796502001")
            fila = self.flow.listar_cartoes("Pintura", "Pintura")["queue"]
            with self.subTest(operacao=numero):
                self.assertEqual(len(fila), 1)
                self.assertEqual(fila[0]["numero_operacao"], numero)
                self.assertEqual(fila[0]["codigo_recurso"], codigo_recurso)

    def test_solda_enxerga_recurso_canonico_do_setor_em_qualquer_estacao(self):
        self._seed_rota_manual(
            "SOLDA-ETAPA3",
            [
                {
                    "numero_operacao": "10",
                    "descricao_operacao": "SOLDA",
                    "tipo_setor": "Solda",
                    "codigo_recurso": "MT NT",
                    "ordem": 1,
                }
            ],
        )
        for estacao in ("Estação 1", "Estação 7"):
            with self.subTest(estacao=estacao):
                fila = self.flow.listar_cartoes("Solda", estacao)["queue"]
                self.assertEqual(len(fila), 1)
                self.assertEqual(fila[0]["codigo_recurso"], "MT NT")

    def test_recurso_de_outro_setor_nao_vaza_para_pintura_ou_solda(self):
        self._seed_rota_manual(
            "VAZAMENTO-ETAPA3",
            [
                {
                    "numero_operacao": "10",
                    "descricao_operacao": "USINAGEM",
                    "tipo_setor": "Usinagem",
                    "codigo_recurso": "CNC-01",
                    "ordem": 1,
                }
            ],
        )
        self.assertEqual(self.flow.listar_cartoes("Pintura", "Pintura")["queue"], [])
        self.assertEqual(self.flow.listar_cartoes("Solda", "Estação 1")["queue"], [])
        # O posto correto continua enxergando normalmente.
        self.assertEqual(
            len(self.flow.listar_cartoes("Usinagem", "Romi D 1000")["queue"]), 1
        )

    def test_apontar_recurso_canonico_de_pintura_nao_exige_autorizacao_de_excecao(self):
        self._seed_rota_manual(
            "PINTURA-ETAPA3",
            [
                {
                    "numero_operacao": "50",
                    "descricao_operacao": "JATEAMENTO",
                    "tipo_setor": "Pintura",
                    "codigo_recurso": "JATO",
                    "ordem": 1,
                }
            ],
        )
        self._seed_execucao()
        operacao = self.db.listar_operacoes_para_op("PINTURA-ETAPA3")[0]
        resultado = self.flow.executar(
            "Início",
            op="PINTURA-ETAPA3",
            setor="Pintura",
            recurso="Pintura",
            operacao=operacao,
        )
        self.assertTrue(resultado.ok, resultado.message)

        registro = self._rows(
            "SELECT * FROM apontamentos_operacionais WHERE op = %s", ("PINTURA-ETAPA3",)
        )[0]
        # Identidade canônica preservada: o recurso do roteiro continua JATO.
        self.assertEqual(registro["codigo_recurso"], "JATO")
        self.assertEqual(registro["maquina"], "Pintura")
        evento = self._rows(
            "SELECT * FROM eventos_apontamento_operador WHERE apontamento_id = %s ORDER BY id",
            (registro["id"],),
        )[-1]
        self.assertEqual(evento["recurso_roteiro_codigo"], "JATO")
        self.assertEqual(evento["recurso_apontado"], "Pintura")
        self.assertFalse(evento["recurso_divergente"])

    def test_ambiente_de_execucao_dos_testes_e_isolado_do_banco_real(self):
        alvo = self.db.safe_target
        self.assertIn("test", str(alvo.get("dbname") or "").casefold())
        self.assertNotEqual(str(alvo.get("dbname") or ""), "gestor_pecas")

    # ------------------------------------------------------------------
    # 3E — a execução continua sendo a do Gestor
    # ------------------------------------------------------------------
    def test_ciclo_de_apontamento_da_op_totvs_usa_a_maquina_de_estados_canonica(self):
        self.service.ingest(self._payload_sem_corte())
        self._seed_execucao()
        operacao = self.db.listar_operacoes_para_op("B0000000001")[0]
        contexto = dict(
            op="B0000000001",
            setor="Usinagem",
            recurso="Romi D 1000",
            operacao=operacao,
        )

        def executar(acao, **extra):
            return self.flow.executar(acao, **contexto, **extra)

        # Wave 5/6B: a primeira peça é o portão do lote. Em Usinagem ela é
        # liberada antes de produzir, e sem ela não há finalização.
        liberar_primeira_peca(self.db, "OPERADOR TOTVS", **contexto)

        self.assertTrue(executar("Início").ok)
        self.assertEqual(self._estado_atual(), "Em processo")

        self.assertTrue(executar("Setup").ok)
        self.assertEqual(self._estado_atual(), "Setup")
        self.assertTrue(executar("Retornar").ok)
        self.assertEqual(self._estado_atual(), "Em processo")

        self.assertTrue(executar("Parada", motivo_codigo="0201").ok)
        self.assertEqual(self._estado_atual(), "Parada")
        self.assertTrue(executar("Retomar").ok)
        self.assertEqual(self._estado_atual(), "Em processo")

        self.assertTrue(executar("Retrabalho").ok)
        self.assertEqual(self._estado_atual(), "Retrabalho")
        # Regra homologada: Retrabalho não volta direto para Produção.
        direto = executar("Início")
        self.assertFalse(direto.ok)
        self.assertEqual(direto.code, "transicao_invalida")

        # Peças boas não podem exceder o saldo previsto da OP.
        excedente = executar("Finalizado", pecas_boas=11, operadores_cracha=["9001"])
        self.assertFalse(excedente.ok)
        self.assertEqual(excedente.code, "quantidade_inconsistente")
        # Finalização exige crachá.
        sem_cracha = executar("Finalizado", pecas_boas=10)
        self.assertFalse(sem_cracha.ok)
        self.assertEqual(sem_cracha.code, "cracha_obrigatorio")

        # Wave 4: boas + refugo consomem o planejado. 6 boas + 2 refugos
        # atendem 8 de 10 e mantêm a OP aberta com saldo de 2; a parcial
        # devolve a OP à fila, de onde o operador reabre para encerrar.
        parcial = executar(
            "Finalizado", pecas_boas=6, refugo=2, operadores_cracha=["9001"]
        )
        self.assertTrue(parcial.ok)
        self.assertEqual(parcial.code, "finalizacao_parcial")
        self.assertEqual(int(parcial.data["saldo_restante"]), 2)
        self.assertEqual(self._estado_atual(), "Aguardando")

        self.assertTrue(executar("Início").ok)
        final = executar("Finalizado", pecas_boas=2, operadores_cracha=["9001"])
        self.assertTrue(final.ok)
        self.assertEqual(self._estado_atual(), "Finalizado")

        registro = self._rows(
            "SELECT * FROM apontamentos_operacionais WHERE op = %s", ("B0000000001",)
        )[0]
        # Refugo é registrado separadamente e nunca vira peça boa.
        self.assertEqual(int(registro["quantidade_boa"]), 8)
        self.assertEqual(int(registro["quantidade_refugo"]), 2)
        self.assertEqual(registro["catalogo_operacao_id"], operacao["id"])

        estados = [
            row["estado"]
            for row in self.db.listar_eventos_apontamento_operador(registro["id"])
        ]
        self.assertEqual(
            estados,
            [
                "fila",
                "producao",
                "setup",
                "producao",
                "parada",
                "producao",
                "retrabalho",
                "parcial",
                "producao",
                "finalizado",
            ],
        )

        # A etapa concluída não volta indevidamente para a fila.
        self.assertEqual(self._fila("Usinagem", "Romi D 1000"), [])
        reabertura = executar("Início")
        self.assertFalse(reabertura.ok)
        self.assertEqual(reabertura.code, "operacao_finalizada")

    def test_execucao_da_op_totvs_nao_grava_marca_de_origem_corporativa(self):
        self.service.ingest(self._payload_sem_corte())
        self._seed_execucao()
        operacao = self.db.listar_operacoes_para_op("B0000000001")[0]
        contexto = dict(
            op="B0000000001",
            setor="Usinagem",
            recurso="Romi D 1000",
            operacao=operacao,
        )
        liberar_primeira_peca(self.db, "OPERADOR TOTVS", **contexto)
        self.assertTrue(self.flow.executar("Início", **contexto).ok)

        colunas = {
            row["column_name"]
            for row in self._rows(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name IN (
                      'apontamentos_operacionais',
                      'eventos_apontamento_operador',
                      'eventos_estado_recurso',
                      'eventos_quantidade_producao'
                  )
                """
            )
        }
        self.assertFalse({coluna for coluna in colunas if "totvs" in coluna.casefold()})

        # Os metadados corporativos permanecem exclusivamente no planejamento.
        planejamento = {
            row["column_name"]
            for row in self._rows(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'catalogo_pcp_ops'
                """
            )
        }
        self.assertIn("totvs_unique_id", planejamento)

    def _estado_atual(self):
        return self._scalar(
            "SELECT status FROM apontamentos_operacionais WHERE op = %s ORDER BY id DESC LIMIT 1",
            ("B0000000001",),
        )


class ElegibilidadeDePostoTests(unittest.TestCase):
    """Posto ↔ setor/recurso: correção complementar da Etapa 3."""

    def test_posto_de_maquina_continua_exigindo_recurso_exato(self):
        for setor, posto, recurso, esperado in (
            ("Usinagem", "Romi D 1000", "CNC-01", True),
            ("Usinagem", "Romi D 1000", "CNC-02", False),
            ("Usinagem", "Eurostec", "CNC-01", False),
            ("Dobra", "Gasparini", "DOBRA1", True),
            ("Dobra", "Gasparini", "DOBRA2", False),
            ("Corte", "Plasma TerraBlade 4", "PLASMA", True),
            ("Corte", "Plasma TerraBlade 4", "LASER1", False),
        ):
            with self.subTest(setor=setor, posto=posto, recurso=recurso):
                self.assertIs(
                    station_matches_route(
                        setor, posto, recurso, resource_sector=setor
                    ),
                    esperado,
                )

    def test_pintura_aceita_todo_recurso_com_pertencimento_canonico(self):
        for recurso, cadastro in (
            ("PINT.L", "Pintura"),
            ("INSPE2", "Pintura"),
            ("PREP", "Pintura"),
            ("ESTUFA", "Pintura"),
            ("RETOQ", "Pintura"),
            ("TINTA", "Pintura"),
            # JATO ainda está com tipo_setor nulo; vale a associação oficial.
            ("JATO", None),
        ):
            with self.subTest(recurso=recurso):
                self.assertTrue(
                    station_matches_route(
                        "Pintura", "Pintura", recurso, resource_sector=cadastro
                    )
                )

    def test_solda_aceita_recurso_canonico_em_qualquer_estacao(self):
        for numero in range(1, 11):
            with self.subTest(estacao=numero):
                self.assertTrue(
                    station_matches_route(
                        "Solda", f"Estação {numero}", "MT NT", resource_sector="Solda"
                    )
                )
                self.assertTrue(
                    station_matches_route(
                        "Solda", f"Estação {numero}", "SOLDA4", resource_sector="Solda"
                    )
                )

    def test_recurso_de_outro_setor_nunca_entra_em_pintura_ou_solda(self):
        for setor, posto in (("Pintura", "Pintura"), ("Solda", "Estação 1")):
            for recurso, cadastro in (
                ("CNC-01", "Usinagem"),
                ("PLASMA", "Corte"),
                ("DOBRA1", "Dobra"),
                ("SERRA1", "Serra"),
            ):
                with self.subTest(setor=setor, recurso=recurso):
                    self.assertFalse(
                        station_matches_route(
                            setor, posto, recurso, resource_sector=cadastro
                        )
                    )

    def test_nome_semelhante_e_cadastro_vazio_nao_criam_elegibilidade(self):
        for recurso in ("MPRT1", "MONTAGEM PM05", "PINTURA", "SOLDAGEM", "PINT.X"):
            with self.subTest(recurso=recurso):
                self.assertFalse(
                    station_matches_route(
                        "Pintura", "Pintura", recurso, resource_sector=None
                    )
                )
                self.assertFalse(
                    station_matches_route(
                        "Solda", "Estação 1", recurso, resource_sector=None
                    )
                )

    def test_elegibilidade_nao_cria_alias_nem_altera_identidade(self):
        """Nenhum recurso de Pintura/Solda é convertido para o código do posto."""

        for recurso in ("JATO", "INSPE2", "PREP", "ESTUFA", "RETOQ", "TINTA"):
            with self.subTest(recurso=recurso):
                self.assertNotIn(recurso.casefold(), OFFICIAL_RESOURCE_ALIASES)
                # O rótulo de tela nunca vira o código de outro recurso.
                self.assertNotEqual(resource_display_name(recurso), "PINT.L")
        for recurso in ("MT NT", "SOLDA4"):
            with self.subTest(recurso=recurso):
                self.assertNotIn(recurso.casefold(), OFFICIAL_RESOURCE_ALIASES)
        # O único alias oficial continua sendo LASER → LASER1.
        self.assertEqual(OFFICIAL_RESOURCE_ALIASES, {"laser": "LASER1"})

    def test_regra_canonica_nao_esta_duplicada_no_adaptador_totvs(self):
        self.assertIs(RESOURCE_OWNED_POINTABLE_SECTORS, SECTOR_OWNED_RESOURCE_SECTORS)
        self.assertEqual(
            SECTOR_OWNED_RESOURCE_SECTORS, {"pintura", "solda", "montagem"}
        )
        adaptador = (ROOT / "mes/integrations/totvs/resource_mapping.py").read_text(
            encoding="utf-8"
        )
        # A associação oficial vive apenas no núcleo canônico.
        self.assertNotIn('OFFICIAL_RESOURCE_SECTORS = {', adaptador)


class Etapa3FronteiraCanonicaTests(unittest.TestCase):
    """Garantias estáticas: a origem TOTVS não vaza para a execução."""

    EXECUCAO = (
        "mes/services/operator_flow.py",
        "mes/services/cut.py",
        "mes/services/production.py",
        "mes/domain/operator_state_machine.py",
        "mes/domain/manufacturing_rules.py",
        "backend/api/routers/operator.py",
        "backend/api/routers/cutting.py",
    )
    INTEGRACAO = (
        "mes/integrations/totvs/mapper.py",
        "mes/integrations/totvs/service.py",
        "mes/integrations/totvs/parser.py",
        "mes/integrations/totvs/resource_mapping.py",
        "mes/integrations/totvs/response.py",
        "app/database/totvs_repository.py",
    )
    OUTBOUND = (
        "mes/integrations/totvs/outbound_models.py",
        "mes/integrations/totvs/outbound_mapper.py",
        "mes/integrations/totvs/outbound_ack.py",
        "mes/integrations/totvs/outbound_service.py",
        "backend/integrations/totvs_wspcp.py",
        "app/database/totvs_outbound_repository.py",
    )

    @staticmethod
    def _source(relative):
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_execucao_nao_conhece_a_origem_totvs(self):
        for relative in self.EXECUCAO:
            with self.subTest(arquivo=relative):
                self.assertNotIn("totvs", self._source(relative).casefold())

    def test_integracao_totvs_nao_reimplementa_apontamento(self):
        proibidos = (
            "apontamentos_operacionais",
            "apontamentos_corte",
            "eventos_apontamento_operador",
            "eventos_estado_recurso",
            "eventos_quantidade_producao",
            "enfileirar_apontamento",
            "transicionar_apontamento",
            "OperatorState",
            "OperatorAction",
            "OperatorFlowService",
            "CutService",
        )
        for relative in self.INTEGRACAO:
            source = self._source(relative)
            for termo in proibidos:
                with self.subTest(arquivo=relative, termo=termo):
                    self.assertNotIn(termo, source)

    def test_outbound_totvs_consume_fatos_sem_reimplementar_apontamento(self):
        mapper = self._source("mes/integrations/totvs/outbound_mapper.py")
        self.assertIn("ProductionAppointment", mapper)
        self.assertIn("StopReport", mapper)
        repository = self._source("app/database/totvs_outbound_repository.py")
        self.assertIn("eventos_apontamento_operador", repository)
        self.assertIn("eventos_quantidade_producao", repository)
        self.assertIsNone(
            re.search(r"\b(?:INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM)\b", repository, re.I)
        )
        proibidos = (
            "enfileirar_apontamento",
            "transicionar_apontamento",
            "OperatorState",
            "OperatorAction",
            "OperatorFlowService",
            "CutService",
            "origem_op",
            "origem ==",
        )
        for relative in self.OUTBOUND:
            source = self._source(relative)
            for termo in proibidos:
                with self.subTest(arquivo=relative, termo=termo):
                    self.assertNotIn(termo, source)

    def test_nenhuma_dependencia_funcional_de_qlik_no_produto_web(self):
        """Qlik está fora da arquitetura alvo: nada do produto pode importá-lo."""

        importacao = re.compile(r"^\s*(from|import)\s+qlik(?![A-Za-z0-9_])", re.M)
        for pasta in ("app", "backend", "mes", "scripts", "tools"):
            for arquivo in sorted((ROOT / pasta).rglob("*.py")):
                if "__pycache__" in arquivo.parts:
                    continue
                with self.subTest(arquivo=str(arquivo.relative_to(ROOT))):
                    self.assertIsNone(
                        importacao.search(arquivo.read_text(encoding="utf-8"))
                    )

    def test_qlik_nao_existe_mais_no_codigo_executavel(self):
        """Wave 3: a remoção é definitiva, não mais uma dívida congelada.

        A única sobrevida permitida é o SQL histórico das migrations 2 e 3, que
        criou as colunas com o nome antigo e **não pode ser reescrito** — a
        migration 23 as renomeia para ``maquina_sigmanest``. Reescrever o
        histórico quebraria a reconstrução do schema a partir do zero.
        """

        # Exceções declaradas: ambos reconstroem o schema histórico, onde a
        # coluna ainda se chamava `maquina_qlik` até a migration 23.
        historico = {
            "app/database/migrations.py",
            "scripts/ensaiar_migracao_11_19.py",
        }
        for pasta in ("app", "backend", "mes", "scripts", "tools"):
            raiz = ROOT / pasta
            if not raiz.is_dir():
                continue
            for arquivo in sorted(raiz.rglob("*.py")):
                if "__pycache__" in arquivo.parts:
                    continue
                relativo = arquivo.relative_to(ROOT).as_posix()
                if relativo in historico:
                    continue
                with self.subTest(arquivo=relativo):
                    self.assertNotIn(
                        "qlik", arquivo.read_text(encoding="utf-8").casefold()
                    )

    def test_pasta_qlik_da_raiz_foi_removida(self):
        """O pacote órfão saiu do repositório, não apenas do import."""

        self.assertFalse((ROOT / "qlik").exists())

    def test_migration_historica_de_qlik_so_sobrevive_como_rename(self):
        """No schema atual o nome herdado já foi substituído."""

        schema = (ROOT / "app" / "database" / "migrations.py").read_text(encoding="utf-8")
        self.assertIn("RENAME COLUMN maquina_qlik TO maquina_sigmanest", schema)
        # Fora do SQL histórico, do rename e do comentário que o explica,
        # nenhuma linha nova pode mencionar o produto.
        for linha in schema.splitlines():
            texto = linha.strip()
            if "qlik" not in texto.casefold():
                continue
            if texto.startswith("#") or "RENAME COLUMN" in texto:
                continue
            with self.subTest(linha=texto[:70]):
                self.assertIn("maquina_qlik", texto)

    def test_correlacao_de_corte_e_por_produto_e_nao_por_tarefa_ou_plano(self):
        """Tarefa, plano e nesting agrupam produtos e não possuem OP própria."""

        schema = (ROOT / "app" / "database" / "migrations.py").read_text(encoding="utf-8")

        def colunas(tabela):
            trecho = schema.split(f"CREATE TABLE {tabela} (", 1)[1].split(chr(10) + "    )", 1)[0]
            return {
                linha.strip().split()[0]
                for linha in trecho.splitlines()
                if linha.strip() and not linha.strip().startswith(("CONSTRAINT", "PRIMARY", "CHECK"))
            }

        # A OP só existe na linha de produto/peça da tarefa.
        self.assertIn("codigo_op", colunas("catalogo_sigmanest_ops"))
        self.assertIn("id_peca", colunas("catalogo_sigmanest_ops"))
        # Agrupamentos não carregam OP.
        for agrupamento in (
            "catalogo_sigmanest_tarefas",
            "catalogo_sigmanest_programas",
            "catalogo_sigmanest_planos_corte",
            "apontamentos_corte",
        ):
            with self.subTest(tabela=agrupamento):
                self.assertNotIn("codigo_op", colunas(agrupamento))

    def test_montagem_possui_representacao_estrutural_sem_recurso_inventado(self):
        montagem = OPERATOR_SECTOR_BY_ROUTE.get("Montagem")
        self.assertIsNotNone(montagem)
        self.assertEqual(montagem.level, "operador_montagem")
        self.assertFalse(montagem.automatic_queue)
        # Pendência cadastral registrada: nenhum posto é inventado.
        self.assertEqual(montagem.resources, ())
        self.assertIn("operador_montagem", USER_LEVELS)
        self.assertEqual(navigation_for_level("operador_montagem"), ("Montagem",))
        self.assertIn("montagem", RESOURCE_OWNED_POINTABLE_SECTORS)

    def test_catalogo_de_setores_operacionais_permanece_sem_duplicidade(self):
        rotas = [sector.route for sector in OPERATOR_SECTORS]
        self.assertEqual(len(rotas), len(set(rotas)))
        niveis = [sector.level for sector in OPERATOR_SECTORS]
        self.assertEqual(len(niveis), len(set(niveis)))
        for nivel in niveis:
            self.assertIn(nivel, USER_LEVELS)


if __name__ == "__main__":
    unittest.main()
