"""Consulta de OP e etapa adicionada no Gestor ao roteiro (migration 72).

Todo acesso a PostgreSQL usa um schema descartável criado dentro de
``TEST_DATABASE_URL``. Nada daqui chega ao TOTVS: o outbound roda com a
integração ligada só para provar que a etapa do Gestor é ignorada.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from types import SimpleNamespace

import psycopg

import tests.test_totvs_outbox as outbox_tests
from app.core.areas import recursos_da_area
from app.core.permissions import can_manage_route_steps
from app.database.database import Database
from app.database.migrations import MIGRATIONS
from mes.integrations.totvs.outbound_enqueue import (
    OutboundEnqueueConfig,
    plan_execution_event,
)
from mes.services.order_route import (
    NOTA_TEMPO_NAO_CADASTRADO,
    RouteStepError,
    OrderRouteService,
    _tempo_padrao,
)
from mes.services.manual_queue import ManualQueueService
from tests.test_area_queue import OP_A, _PostgresCase
from tests.test_totvs_outbound import canonical_event

PCP = {"user_id": 7, "user_name": "PCP TESTE", "user_role": "lider", "assigned_level": "pcp"}
ADMIN = {"user_id": 1, "user_name": "ADMIN TESTE", "user_role": "admin", "assigned_level": None}
LIDER = {"user_id": 9, "user_name": "LIDER TESTE", "user_role": "lider", "assigned_level": None}
MOTIVO = "Retrabalho de usinagem pedido pela engenharia"


class PermissaoETempoTests(unittest.TestCase):
    def test_quem_pode_alterar_o_roteiro(self):
        casos = (
            ("admin", None, True),
            ("manufatura", None, True),
            ("lider", "pcp", True),
            ("supervisor", "pcp", True),
            ("lider", None, False),
            ("supervisor", None, False),
            ("gestor", None, False),
            ("qualidade", None, False),
            ("diretoria", None, False),
            ("operador_dobra", None, False),
            ("operador_dobra", "pcp", False),  # nível atribuído sem acesso à gestão
            ("andon", "pcp", False),
        )
        for nivel, atribuido, esperado in casos:
            with self.subTest(nivel=nivel, atribuido=atribuido):
                self.assertIs(can_manage_route_steps(nivel, atribuido), esperado)

    def test_tempo_nulo_ou_001_do_protheus_vira_na_com_a_nota(self):
        for valor in (None, 0, 0.01, "0.01", "abc"):
            with self.subTest(valor=valor):
                tempo = _tempo_padrao(valor)
                self.assertFalse(tempo["disponivel"])
                self.assertIsNone(tempo["segundos"])
                self.assertEqual(
                    tempo["nota"],
                    "Tempo padrão não cadastrado no Protheus. "
                    "A engenharia de manufatura ajusta direto no ERP.",
                )
        self.assertEqual(NOTA_TEMPO_NAO_CADASTRADO, _tempo_padrao(None)["nota"])
        real = _tempo_padrao(120)
        self.assertTrue(real["disponivel"])
        self.assertEqual(real["segundos"], 120.0)
        self.assertIsNone(real["nota"])

    def test_outbound_ignora_evento_de_etapa_do_gestor(self):
        config = OutboundEnqueueConfig(enabled=True)
        self.assertTrue(plan_execution_event(canonical_event(), config=config))
        self.assertEqual(
            plan_execution_event(canonical_event(gestor_added_step=True), config=config),
            [],
        )


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class _OpRealCase(unittest.TestCase):
    """Reaproveita a OP real do Protheus (roteiro 10/20/99) do teste de outbox."""

    _Base = outbox_tests.TotvsOutboxPostgresTests
    CONFIG = _Base.CONFIG
    setUp = _Base.setUp
    tearDown = _Base.tearDown
    _seed_production_order = _Base._seed_production_order
    _rows = _Base._rows
    _scalar = _Base._scalar
    _operation = _Base._operation
    _queue = _Base._queue
    _transition = _Base._transition
    _outbox = _Base._outbox
    _produce_and_finish = _Base._produce_and_finish

    def servico(self, usuario=PCP):
        return OrderRouteService(self.db, **usuario)

    def _id(self, numero):
        return int(self._operation(numero)["id"])

    def _etapas_do_gestor(self):
        return self._rows(
            "SELECT * FROM catalogo_operacoes_op WHERE codigo_op = %s AND etapa_gestor IS TRUE"
            " ORDER BY id",
            (self.op,),
        )

    def _adicionar(self, usuario=PCP, *, depois_de="20", recurso="CNC-01", descricao="Rebarbar furo"):
        return self.servico(usuario).adicionar_etapa(
            self.op,
            apos_operacao_id=self._id(depois_de) if depois_de else None,
            descricao=descricao,
            recurso=recurso,
            motivo=MOTIVO,
        )


class ConsultaDaOpTests(_OpRealCase):
    def test_consulta_traz_op_roteiro_e_tempo_n_a(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET tempo_medio_segundos = 0.01"
                " WHERE codigo_op = %s AND numero_operacao = '20'",
                (self.op,),
            )
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET tempo_medio_segundos = 120"
                " WHERE codigo_op = %s AND numero_operacao = '10'",
                (self.op,),
            )
        dados = self.servico(LIDER).consultar(self.op)
        self.assertEqual(dados["order"]["codigo_op"], self.op)
        self.assertTrue(dados["order"]["produto_codigo"])
        linhas = {l["numero_operacao"]: l for l in dados["route"]}
        self.assertFalse(linhas["20"]["tempo_padrao"]["disponivel"])
        self.assertEqual(linhas["20"]["tempo_padrao"]["nota"], NOTA_TEMPO_NAO_CADASTRADO)
        self.assertTrue(linhas["10"]["tempo_padrao"]["disponivel"])
        self.assertEqual(linhas["10"]["tempo_padrao"]["segundos"], 120.0)
        self.assertTrue(all(l["origem"] == "protheus" for l in dados["route"]))
        # Quem não altera o roteiro não recebe as opções de adição.
        self.assertFalse(dados["permissions"]["can_add_step"])
        self.assertIsNone(dados["add_options"])

    def test_op_inexistente_devolve_404(self):
        with self.assertRaises(RouteStepError) as erro:
            self.servico().consultar("NAO-EXISTE-1")
        self.assertEqual((erro.exception.code, erro.exception.status_code), ("order_not_found", 404))

    def test_busca_por_codigo(self):
        achados = self.servico().buscar(self.op[:6])
        self.assertIn(self.op, [item["codigo_op"] for item in achados])
        self.assertEqual(self.servico().buscar("a"), [])


class _FakeProvisioning:
    unavailable_message = "Protheus fora."

    def __init__(self, status, found):
        self.status, self.found = status, found

    def provision(self, codigo):
        from mes.services.order_provisioning import OrderProvisioningResult

        return OrderProvisioningResult(op=codigo, status=self.status, found=self.found, message="msg")


class PassagemPeloSistemaTests(_OpRealCase):
    def test_op_no_gestor_sem_apontamento_e_depois_com_apontamento(self):
        self.assertEqual(self.servico().consultar(self.op)["system"]["situacao"], "no_sistema_sem_apontamento")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO apontamentos_operacionais (op, tipo_setor, maquina, operador_fila,"
                " data_entrada, data_inicio) VALUES (%s, 'Corte', 'LASER1', 'X', now(), now())",
                (self.op,),
            )
        sistema = self.servico().consultar(self.op)["system"]
        self.assertEqual((sistema["situacao"], sistema["iniciados"]), ("ja_passou", 1))

    def test_consulta_protheus_de_op_que_o_gestor_nao_tem(self):
        resposta = self.servico().consultar_protheus("OP-SO-PROTHEUS", _FakeProvisioning("nao_encontrada", False))
        self.assertFalse(resposta["estava_no_gestor"])
        self.assertEqual(resposta["protheus"]["status"], "nao_encontrada")
        self.assertEqual(resposta["system"]["situacao"], "so_protheus")

    def test_consulta_protheus_de_op_que_ja_estava_no_gestor(self):
        resposta = self.servico().consultar_protheus(self.op, _FakeProvisioning("local", True))
        self.assertTrue(resposta["estava_no_gestor"])
        self.assertFalse(resposta["protheus"]["consultado"])
        self.assertEqual(resposta["system"]["situacao"], "no_sistema_sem_apontamento")


class EtapaDoGestorTests(_OpRealCase):
    def test_nivel_sem_permissao_e_recusado_e_nada_e_gravado(self):
        with self.assertRaises(RouteStepError) as erro:
            self._adicionar(LIDER)
        self.assertEqual((erro.exception.code, erro.exception.status_code), ("route_step_access_denied", 403))
        self.assertEqual(self._etapas_do_gestor(), [])
        self.assertEqual(self.db.listar_auditoria(entidade="roteiro_etapa"), [])

    def test_pcp_manufatura_e_admin_adicionam(self):
        ids = []
        for usuario in (
            PCP,
            {**LIDER, "user_role": "manufatura"},
            ADMIN,
        ):
            ids.append(self._adicionar(usuario)["id"])
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(
            [e["numero_operacao"] for e in self._etapas_do_gestor()], ["G01", "G02", "G03"]
        )

    def test_etapa_entra_depois_da_operacao_escolhida_e_vem_marcada(self):
        criada = self._adicionar()
        self.assertEqual(criada["numero_operacao"], "G01")
        dados = self.servico().consultar(self.op)
        numeros = [l["numero_operacao"] for l in dados["route"]]
        self.assertEqual(numeros.index("G01"), numeros.index("20") + 1)
        etapa = dados["route"][numeros.index("G01")]
        self.assertEqual(etapa["origem"], "gestor")
        self.assertEqual(etapa["recurso_codigo"], "CNC-01")
        self.assertEqual(etapa["adicionada_por"], "PCP TESTE")
        self.assertEqual(etapa["motivo_adicao"], MOTIVO)
        self.assertEqual(etapa["situacao"], "Não iniciada")
        self.assertFalse(etapa["tempo_padrao"]["disponivel"])
        # Quem altera recebe as opções para o formulário (só recursos apontáveis).
        self.assertTrue(dados["permissions"]["can_add_step"])
        codigos = {r["codigo"] for r in dados["add_options"]["resources"]}
        self.assertIn("CNC-01", codigos)
        self.assertNotIn("PLASMA", codigos)

    def test_etapa_no_inicio_do_roteiro(self):
        self._adicionar(depois_de=None)
        numeros = [l["numero_operacao"] for l in self.servico().consultar(self.op)["route"]]
        self.assertEqual(numeros[0], "G01")

    def test_validacoes(self):
        servico = self.servico()
        ancora = self._id("20")
        casos = (
            ({"descricao": "ab"}, "route_step_invalid_text"),
            ({"motivo": " "}, "route_step_invalid_text"),
            ({"recurso": "PLASMA"}, "route_step_resource_not_pointable"),  # Corte tem fluxo próprio
            ({"recurso": "INEXISTENTE"}, "route_step_resource_not_pointable"),
            ({"apos_operacao_id": 10**9}, "route_step_anchor_not_found"),
        )
        for mudanca, codigo in casos:
            with self.subTest(codigo=codigo, mudanca=mudanca):
                dados = {
                    "apos_operacao_id": ancora, "descricao": "Rebarbar furo",
                    "recurso": "CNC-01", "motivo": MOTIVO, **mudanca,
                }
                with self.assertRaises(RouteStepError) as erro:
                    servico.adicionar_etapa(self.op, **dados)
                self.assertEqual(erro.exception.code, codigo)
                self.assertEqual(erro.exception.status_code, 422)
        self.assertEqual(self._etapas_do_gestor(), [])
        with self.assertRaises(RouteStepError) as erro:
            servico.adicionar_etapa(
                "NAO-EXISTE-1", apos_operacao_id=None, descricao="Rebarbar",
                recurso="CNC-01", motivo=MOTIVO,
            )
        self.assertEqual(erro.exception.status_code, 404)

    def test_auditoria_grava_quem_quando_motivo_e_dados(self):
        etapa = self._adicionar()
        registros = self.db.listar_auditoria(entidade="roteiro_etapa", chave=self.op)
        self.assertEqual(len(registros), 1)
        criacao = registros[0]
        self.assertEqual(criacao["acao"], "criar")
        self.assertEqual(criacao["usuario_nome"], "PCP TESTE")
        self.assertEqual(criacao["usuario_id"], 7)
        self.assertIsNotNone(criacao["quando"])
        self.assertEqual(criacao["depois"]["motivo"], MOTIVO)
        self.assertEqual(criacao["depois"]["recurso"], "CNC-01")
        self.assertEqual(criacao["depois"]["apos_operacao"], "20")
        self.assertEqual(criacao["depois"]["numero_operacao"], "G01")

        self.servico(ADMIN).desativar_etapa(self.op, etapa["id"], motivo="Não é mais necessária")
        registros = self.db.listar_auditoria(entidade="roteiro_etapa", chave=self.op)
        self.assertEqual(len(registros), 2)
        desativacao = registros[0]
        self.assertEqual(desativacao["acao"], "alterar")
        self.assertEqual(desativacao["usuario_nome"], "ADMIN TESTE")
        self.assertTrue(desativacao["antes"]["ativo"])
        self.assertFalse(desativacao["depois"]["ativo"])
        self.assertEqual(desativacao["depois"]["motivo"], "Não é mais necessária")
        # O histórico aparece na consulta da OP.
        self.assertEqual(len(self.servico().consultar(self.op)["history"]), 2)

    def test_desativar_nao_apaga_e_so_vale_para_etapa_do_gestor(self):
        etapa = self._adicionar()
        servico = self.servico()
        with self.assertRaises(RouteStepError) as erro:  # etapa do Protheus
            servico.desativar_etapa(self.op, self._id("20"), motivo=MOTIVO)
        self.assertEqual((erro.exception.code, erro.exception.status_code), ("route_step_not_found", 404))
        with self.assertRaises(RouteStepError) as erro:  # sem permissão
            self.servico(LIDER).desativar_etapa(self.op, etapa["id"], motivo=MOTIVO)
        self.assertEqual(erro.exception.status_code, 403)

        servico.desativar_etapa(self.op, etapa["id"], motivo=MOTIVO)
        linha = self._etapas_do_gestor()[0]
        self.assertIs(linha["ativo"], False)
        self.assertEqual(linha["desativada_por_nome"], "PCP TESTE")
        self.assertEqual(linha["motivo_desativacao"], MOTIVO)
        situacoes = {
            l["numero_operacao"]: l["situacao"] for l in servico.consultar(self.op)["route"]
        }
        self.assertEqual(situacoes["G01"], "Desativada")
        with self.assertRaises(RouteStepError) as erro:  # já desativada
            servico.desativar_etapa(self.op, etapa["id"], motivo=MOTIVO)
        self.assertEqual(erro.exception.status_code, 404)

    def test_etapa_ja_apontada_nao_pode_ser_desativada(self):
        etapa = self._adicionar()
        self._queue("G01")
        with self.assertRaises(RouteStepError) as erro:
            self.servico().desativar_etapa(self.op, etapa["id"], motivo=MOTIVO)
        self.assertEqual((erro.exception.code, erro.exception.status_code), ("route_step_already_pointed", 409))
        self.assertIs(self._etapas_do_gestor()[0]["ativo"], True)

    def test_etapa_aparece_como_proxima_operacao_e_sai_ao_desativar(self):
        etapa = self._adicionar(depois_de=None)
        proximas = self.db.listar_proximas_operacoes_roteiro(codigo_op=self.op)
        self.assertEqual([o["numero_operacao"] for o in proximas], ["G01"])
        self.assertEqual(proximas[0]["tipo_setor"], "Usinagem")
        self.assertEqual(proximas[0]["codigo_recurso"], "CNC-01")
        self.servico().desativar_etapa(self.op, etapa["id"], motivo=MOTIVO)
        proximas = self.db.listar_proximas_operacoes_roteiro(codigo_op=self.op)
        self.assertNotIn("G01", [o["numero_operacao"] for o in proximas])

    def test_resincronizar_o_protheus_nao_apaga_nem_renumera_a_etapa(self):
        etapa = self._adicionar()
        id_op20 = self._id("20")
        protheus = self._rows(
            "SELECT * FROM catalogo_operacoes_op WHERE codigo_op = %s"
            " AND totvs_activity_id IS NOT NULL ORDER BY ordem",
            (self.op,),
        )
        # O Protheus manda o roteiro de novo, desta vez com ``ordem`` deslocada.
        operacoes = [
            SimpleNamespace(**{**linha, "ordem": int(linha["ordem"]) + 10})
            for linha in protheus
        ]
        with self.db.connection() as connection, connection.cursor() as cursor:
            Database._replace_totvs_operations_cursor(
                cursor,
                order=SimpleNamespace(codigo_op=self.op),
                operations=operacoes,
                synchronized_at=datetime.now(),
            )

        etapas = self._etapas_do_gestor()
        self.assertEqual(len(etapas), 1)
        depois = etapas[0]
        self.assertEqual(int(depois["id"]), etapa["id"])
        self.assertIs(depois["ativo"], True)
        self.assertEqual(depois["numero_operacao"], "G01")
        self.assertEqual(depois["fonte"], "gestor_etapa_adicional")
        self.assertEqual(self._id("20"), id_op20)  # a âncora mantém o id
        nova_ordem = self._operation("20")["ordem"]
        self.assertEqual(nova_ordem, int(protheus[1]["ordem"]) + 10 if len(protheus) > 1 else nova_ordem)
        self.assertEqual(depois["ordem"], nova_ordem)  # seguiu a âncora, sem renumerar sozinha
        numeros = [l["numero_operacao"] for l in self.servico().consultar(self.op)["route"]]
        self.assertEqual(numeros.index("G01"), numeros.index("20") + 1)
        # A mesma mensagem reenviada (mesmo hash) também não mexe na etapa.
        self.ingestion.ingest(outbox_tests.REAL_OP.read_text(encoding="utf-8"))
        self.assertEqual(len(self._etapas_do_gestor()), 1)
        self.assertIs(self._etapas_do_gestor()[0]["ativo"], True)


class EtapaNoOutboundTests(_OpRealCase):
    def _terminais(self):
        return [
            item for item in self._outbox()
            if item["event_type"] == outbox_tests.EVENT_PRODUCTION_APPOINTMENT_TERMINAL
        ]

    def test_etapa_do_gestor_nao_vai_ao_protheus_e_nao_trava_o_encerramento(self):
        self._adicionar()
        # A etapa do Gestor ainda nem começou e a OP encerra normalmente.
        self._produce_and_finish("20", boas=8, quantidade=8)
        self.assertEqual(len(self._terminais()), 1)
        reais = len(self._outbox())
        self.assertGreaterEqual(reais, 2)  # a etapa real continua enviando

        # Executar a etapa do Gestor grava o evento, mas não enfileira nada.
        self._produce_and_finish("G01", boas=8, quantidade=8)
        self.assertEqual(len(self._outbox()), reais)
        self.assertEqual(len(self._terminais()), 1)
        evento_id = self._scalar(
            "SELECT MAX(e.id) FROM eventos_apontamento_operador e"
            " JOIN apontamentos_operacionais a ON a.id = e.apontamento_id"
            " WHERE a.op = %s AND a.numero_operacao = 'G01'",
            (self.op,),
        )
        self.assertIsNotNone(evento_id)
        canonico = self.db.buscar_evento_canonico_outbound_totvs(evento_id)
        self.assertTrue(canonico.gestor_added_step)

    def test_marco_terminal_nao_conta_a_etapa_do_gestor(self):
        self._adicionar()
        marco = self.db.buscar_marco_terminal_outbound_totvs(self.op)
        self.assertIsNotNone(marco)
        self._produce_and_finish("20", boas=8, quantidade=8)
        self.assertEqual(len(self._terminais()), 1)


class Migration72Tests(_OpRealCase):
    def test_migration_e_idempotente(self):
        _, comandos = MIGRATIONS[72]
        with self.db.connection() as connection:
            for _ in range(2):
                for comando in comandos:
                    connection.execute(comando)

    def test_banco_recusa_etapa_do_gestor_com_id_do_protheus(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO catalogo_operacoes_op (
                        codigo_op, produto_codigo, produto_descricao, numero_operacao,
                        codigo_recurso, descricao_operacao, tipo_setor, ordem, fonte, ativo,
                        sincronizado_em, etapa_gestor, totvs_activity_id,
                        adicionada_por_nome, adicionada_em, motivo_adicao
                    ) VALUES (
                        %s, 'P', 'P', 'G99', 'CNC-01', 'X', 'Usinagem', 1, 'teste', TRUE,
                        CURRENT_TIMESTAMP, TRUE, '123', 'ALGUEM', CURRENT_TIMESTAMP, 'motivo ok'
                    )
                    """,
                    (self.op,),
                )


class EtapaNaFilaDoRecursoTests(_PostgresCase):
    def setUp(self):
        super().setUp()
        self.servico = OrderRouteService(self.db, **PCP)

    def _ops_de(self, recurso):
        return [item["op"] for item in ManualQueueService(self.db, "LIDER TESTE").listar(recurso)["items"]]

    def test_etapa_aparece_na_fila_do_recurso_escolhido(self):
        # OP_A só tem a etapa 10 no CNC-01 (Romi). Sem a etapa nova ela não está no CNC-02.
        self.assertNotIn(OP_A, self._ops_de(self.eurostec))
        self.assertIn(OP_A, self._ops_de(self.romi))

        etapa = self.servico.adicionar_etapa(
            OP_A, apos_operacao_id=None, descricao="Preparar peça",
            recurso="CNC-02", motivo=MOTIVO,
        )
        # A etapa vem antes: entra na fila do Eurostec e a etapa 10 espera por ela.
        self.assertIn(OP_A, self._ops_de(self.eurostec))
        self.assertNotIn(OP_A, self._ops_de(self.romi))
        cartao = next(
            i for i in ManualQueueService(self.db, "LIDER TESTE").listar(self.eurostec)["items"]
            if i["op"] == OP_A
        )
        self.assertTrue(cartao["operation"].startswith("G01"))

        self.servico.desativar_etapa(OP_A, etapa["id"], motivo="Desistiram")
        self.assertNotIn(OP_A, self._ops_de(self.eurostec))
        self.assertIn(OP_A, self._ops_de(self.romi))

    def test_recurso_de_outro_setor_tambem_serve_desde_que_apontavel(self):
        codigos = {r["codigo"] for r in self.servico.recursos_para_etapa()}
        self.assertTrue({"CNC-01", "CNC-02"} <= codigos)
        self.assertNotIn("PLASMA", codigos)
        self.assertTrue(recursos_da_area("usinagem"))
