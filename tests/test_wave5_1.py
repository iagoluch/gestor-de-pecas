"""Wave 5.1 — correções da Simulação 2 e as quatro melhorias.

Cada teste aqui existe por causa de um item concreto:

* BUG-01 — a confirmação de etapa anterior pendente bloqueia, inclusive sob
  concorrência, e o reenvio confirmado com crachá autorizado sucede;
* BUG-02 — reentrada, ação repetida, etapa finalizada, retomada e retorno
  incompatíveis deixam de compartilhar um único código genérico;
* BUG-06 — a produção do Corte aparece no rollup gerencial de setor;
* BUG-07 — `report_type` inválido é recusa do cliente, não falha do servidor;
* Melhoria 1 — a conformidade da cota é calculada pelo backend;
* Melhoria 2 — tempo-pessoa com mais de uma pessoa na mesma OP;
* Melhoria 3 — apontamento em setor incorreto continua rastreável;
* Melhoria 4 — as cinco estações de Pintura.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
import unittest

from app.core.operator_sectors import (
    OPERATOR_SECTOR_BY_LEVEL,
    PAINTING_STATIONS,
    sector_display_label,
)
from app.core.resource_mapping import station_matches_route, station_resource_code
from mes.contracts import AnalyticsFilter, ReportError
from mes.domain.quality_measures import evaluate_measure, parse_tolerance
from mes.services.frontend_facade import FACADE_REPORT_TYPES, FrontendBackendFacade
from mes.services.management import ManagementService
from mes.services.operator_flow import OperatorFlowService
from mes.services.operator_participation import OperatorParticipationService
from mes.services.traceability import TraceabilityService
from tests.fakes import FakeDatabase
from tests.wave5_helpers import liberar_primeira_peca


def _servico_com_roteiro(*, primeira_peca_liberada=True):
    """OP com duas etapas: Usinagem (10) e Dobra (20), nesta ordem.

    Wave 6B: Usinagem e Dobra passam pelo portão Setup/Qualidade no Iniciar.
    Estes testes tratam de override de etapa, recusas da máquina de estados e
    tempo-pessoa — por isso o roteiro já nasce com a primeira peça aprovada,
    como o posto fica depois do popup. O portão tem testes próprios.
    """

    db = FakeDatabase()
    task_id = db.inserir_tarefa("T-WAVE51")
    db.inserir_op_na_tarefa(task_id, "OP-WAVE51", "PECA", "Dobra", 4)
    usinagem = {
        "id": 9,
        "codigo_op": "OP-WAVE51",
        "numero_operacao": "10",
        "codigo_recurso": "TORNOC",
        "descricao_operacao": "USINAGEM",
        "tipo_setor": "Usinagem",
        "produto_codigo": "PECA",
        "produto_descricao": "PECA TESTE",
        "quantidade": 4,
    }
    dobra = {
        **usinagem,
        "id": 10,
        "numero_operacao": "20",
        "codigo_recurso": "DOBRA3",
        "descricao_operacao": "DOBRA",
        "tipo_setor": "Dobra",
    }
    db.catalog_operations.extend([usinagem, dobra])
    if primeira_peca_liberada:
        for setor, recurso, operacao in (
            ("Usinagem", "Torno Mecânico", usinagem),
            ("Dobra", "1303", dobra),
        ):
            liberar_primeira_peca(
                db,
                "OPERADOR WAVE51",
                op="OP-WAVE51",
                setor=setor,
                recurso=recurso,
                operacao=operacao,
            )
    return db, OperatorFlowService(db, "OPERADOR WAVE51"), usinagem, dobra


# ---------------------------------------------------------------------------
# BUG-01 — override de etapa anterior
# ---------------------------------------------------------------------------
class OverrideEtapaAnteriorTests(unittest.TestCase):
    def test_inicio_com_etapa_anterior_pendente_e_recusado_sem_confirmacao(self):
        db, service, _, dobra = _servico_com_roteiro()

        recusa = service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303", operacao=dobra
        )

        self.assertFalse(recusa.ok)
        self.assertEqual(recusa.code, "confirmacao_etapa_anterior_obrigatoria")
        # Uma recusa não pode deixar rastro de estado.
        self.assertEqual(db.appointments, [])

    def test_reenvio_confirmado_com_cracha_sucede_e_nao_cai_em_transicao_invalida(self):
        _, service, _, dobra = _servico_com_roteiro()

        service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303", operacao=dobra
        )
        confirmado = service.executar(
            "Início",
            op="OP-WAVE51",
            setor="Dobra",
            recurso="1303",
            operacao=dobra,
            confirmar_etapa_anterior_pendente=True,
            operadores_cracha=["1"],
        )

        self.assertTrue(confirmado.ok, confirmado.message)
        self.assertNotEqual(confirmado.code, "transicao_invalida")

    def test_confirmacao_exige_cracha_cadastrado(self):
        _, service, _, dobra = _servico_com_roteiro()

        sem_cracha = service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303",
            operacao=dobra, confirmar_etapa_anterior_pendente=True,
        )
        self.assertFalse(sem_cracha.ok)
        self.assertEqual(sem_cracha.code, "cracha_autorizacao_obrigatorio")

        invalido = service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303",
            operacao=dobra, confirmar_etapa_anterior_pendente=True,
            operadores_cracha=["CRACHA-INEXISTENTE"],
        )
        self.assertFalse(invalido.ok)
        self.assertEqual(invalido.code, "cracha_invalido")

    def test_duas_confirmacoes_simultaneas_produzem_um_unico_apontamento(self):
        """Concorrência: o bloqueio não pode virar dois inícios da mesma etapa."""

        db, service, _, dobra = _servico_com_roteiro()

        def iniciar():
            return service.executar(
                "Início", op="OP-WAVE51", setor="Dobra", recurso="1303",
                operacao=dobra, confirmar_etapa_anterior_pendente=True,
                operadores_cracha=["1"], recurso_exclusivo=True,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            resultados = [item.result() for item in [pool.submit(iniciar) for _ in range(2)]]

        aceitos = [item for item in resultados if item.ok]
        self.assertEqual(len(aceitos), 1, [item.code for item in resultados])
        ativos = [
            row for row in db.appointments
            if row.get("status") in {"Em processo", "Parada", "Setup", "Retrabalho"}
        ]
        self.assertEqual(len(ativos), 1)


# ---------------------------------------------------------------------------
# BUG-02 — códigos específicos de recusa da máquina de estados
# ---------------------------------------------------------------------------
class RecusaDeTransicaoTests(unittest.TestCase):
    def _em_producao(self):
        db, service, usinagem, _ = _servico_com_roteiro()
        inicio = service.executar(
            "Início", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )
        self.assertTrue(inicio.ok, inicio.message)
        return db, service, usinagem

    def test_acao_repetida_recebe_codigo_proprio_com_o_generico_em_details(self):
        _, service, usinagem = self._em_producao()

        repetido = service.executar(
            "Início", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )

        self.assertFalse(repetido.ok)
        self.assertEqual(repetido.code, "acao_ja_registrada")
        # Compatibilidade: quem trata o código antigo continua reconhecendo.
        self.assertEqual(repetido.data["codigo_generico"], "transicao_invalida")
        self.assertEqual(repetido.data["estado_atual"], "producao")

    def test_retomada_fora_de_parada_e_retorno_fora_de_setup_sao_distintos(self):
        _, service, usinagem = self._em_producao()

        retomada = service.executar(
            "Retomar", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )
        retorno = service.executar(
            "Retornar", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )

        self.assertEqual(retomada.code, "retomada_incompativel")
        self.assertEqual(retorno.code, "retorno_incompativel")

    def test_etapa_finalizada_nao_e_confundida_com_acao_repetida(self):
        db, service, usinagem = self._em_producao()
        liberar_primeira_peca(
            db, "OPERADOR WAVE51", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )
        fim = service.executar(
            "Finalizado", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=usinagem, pecas_boas=4, operadores_cracha=["1"],
        )
        self.assertTrue(fim.ok, fim.message)

        reentrada = service.executar(
            "Início", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=usinagem,
        )
        # A etapa já concluída é barrada antes mesmo da máquina de estados.
        self.assertFalse(reentrada.ok)
        self.assertIn(reentrada.code, {"operacao_finalizada", "etapa_ja_finalizada"})


# ---------------------------------------------------------------------------
# BUG-06 — produção do Corte no rollup gerencial
# ---------------------------------------------------------------------------
class RollupDeCorteTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.inicio = datetime(2026, 9, 14, 8, 0, 0)
        self.fim = datetime(2026, 9, 14, 18, 0, 0)
        task_id = self.db.inserir_tarefa("T-CORTE-51")
        self.db.inserir_op_na_tarefa(task_id, "OP-CORTE-A", "PECA-A", "Dobra", 6)
        self.db.inserir_op_na_tarefa(task_id, "OP-CORTE-B", "PECA-B", "Dobra", 4)
        for indice in (1, 2):
            self.db.cut_plans.append({
                "plano_hash": f"hash-51-{indice}",
                "codigo_tarefa": "T-CORTE-51",
                "programa": "P51",
                "nome_chapa": f"S{indice}",
                "sequencia_nesting": indice,
                "material": "AÇO",
                "espessura": 3.0,
                "maquina_sigmanest": "Amada_ensis",
                "quantidade_processo": 1,
                "tempo_previsto_segundos": 600,
                "data_programa": date(2026, 9, 14),
                "area_usada": 1000,
                "fracao_sucata": 0.2,
                "ativo": True,
            })

    def _apontar(self, indice, *, finalizado=True):
        self.db.cut_appointments.append({
            "id": indice,
            "plano_hash": f"hash-51-{indice}",
            "codigo_tarefa": "T-CORTE-51",
            "programa": "P51",
            "sequencia_nesting": indice,
            "maquina": "Laser Ensis 3015",
            "maquina_sigmanest": "Amada_ensis",
            "quantidade_processo": 1,
            "tempo_previsto_segundos": 600,
            "status": "Finalizado" if finalizado else "Em processo",
            "operador_inicio": "OPERADOR CORTE",
            "data_inicio": self.inicio + timedelta(minutes=10 * indice),
            "operador_fim": "OPERADOR CORTE" if finalizado else None,
            "data_fim": self.inicio + timedelta(minutes=10 * indice + 8) if finalizado else None,
        })

    def _setor_corte(self):
        overview = ManagementService(self.db).get_overview(
            AnalyticsFilter(inicio=self.inicio, fim=self.fim)
        )
        return next(
            row for row in overview["sectors"]
            if str(row["setor"]).casefold() == "corte"
        ), overview

    def test_corte_com_tarefa_incompleta_nao_conta_producao(self):
        self._apontar(1)
        self._apontar(2, finalizado=False)

        corte, _ = self._setor_corte()

        self.assertEqual(corte["producao_boa"], 0)
        self.assertEqual(corte["ops"], 0)

    def test_corte_concluido_soma_boa_e_ops_no_rollup(self):
        self._apontar(1)
        self._apontar(2)

        corte, overview = self._setor_corte()

        # 6 + 4 peças das duas OPs ligadas à tarefa — número real do vínculo
        # OP × tarefa, não estimativa.
        self.assertEqual(corte["producao_boa"], 10)
        self.assertEqual(corte["ops"], 2)
        self.assertGreater(corte["tempo_producao_segundos"], 0)
        # O rollup de setor e o total de produção falam a mesma língua.
        self.assertGreaterEqual(overview["production"]["good"], 10)
        self.assertGreaterEqual(overview["production"]["ops"], 2)

    def test_filtro_por_op_nao_mistura_execucao_de_corte(self):
        self._apontar(1)
        self._apontar(2)

        overview = ManagementService(self.db).get_overview(
            AnalyticsFilter(inicio=self.inicio, fim=self.fim, op="OP-CORTE-A")
        )
        setores = {str(row["setor"]).casefold() for row in overview["sectors"]}
        self.assertNotIn("corte", setores)


# ---------------------------------------------------------------------------
# BUG-07 — contrato de erro da fachada de relatórios
# ---------------------------------------------------------------------------
class FachadaDeRelatoriosTests(unittest.TestCase):
    def setUp(self):
        self.facade = FrontendBackendFacade(FakeDatabase())
        self.filtros = AnalyticsFilter(
            inicio=datetime(2026, 9, 14, 0, 0, 0),
            fim=datetime(2026, 9, 14, 23, 59, 59),
        )

    def test_tipos_validos_continuam_respondendo(self):
        for tipo in FACADE_REPORT_TYPES:
            with self.subTest(tipo=tipo):
                payload = self.facade.relatorio(tipo, self.filtros)
                self.assertEqual(payload["type"], tipo)

    def test_tipo_invalido_vira_recusa_do_cliente_e_nao_erro_interno(self):
        with self.assertRaises(ReportError) as capturado:
            self.facade.relatorio("management", self.filtros)

        self.assertEqual(capturado.exception.code, "report_type_invalido")
        self.assertEqual(capturado.exception.status_code, 400)


# ---------------------------------------------------------------------------
# Melhoria 1 — conformidade calculada pelo backend
# ---------------------------------------------------------------------------
class ConformidadeAutomaticaTests(unittest.TestCase):
    PADRAO = "12,0 +/- 0,2"  # faixa 11,8 .. 12,2

    def test_faixa_completa_abaixo_limite_dentro_limite_acima(self):
        casos = (
            ("11,7", "NAO_CONFORME"),
            ("11,8", "CONFORME"),
            ("12,0", "CONFORME"),
            ("12,2", "CONFORME"),
            ("12,3", "NAO_CONFORME"),
        )
        for medida, esperado in casos:
            with self.subTest(medida=medida):
                avaliacao = evaluate_measure(medida, self.PADRAO)
                self.assertTrue(avaliacao.calculado)
                self.assertEqual(avaliacao.status, esperado)
                self.assertEqual(float(avaliacao.limite_inferior), 11.8)
                self.assertEqual(float(avaliacao.limite_superior), 12.2)
                self.assertEqual(avaliacao.unidade, "mm")

    def test_padrao_sem_margem_exige_a_medida_exata(self):
        self.assertEqual(evaluate_measure("453", "453").status, "CONFORME")
        self.assertEqual(evaluate_measure("453,1", "453").status, "NAO_CONFORME")

    def test_padrao_ou_medida_nao_numericos_nao_inventam_status(self):
        self.assertFalse(evaluate_measure("124,9", "conforme gabarito").calculado)
        self.assertFalse(evaluate_measure("ok", self.PADRAO).calculado)
        self.assertIsNone(parse_tolerance("conforme gabarito"))

    def test_ponto_e_virgula_descrevem_o_mesmo_numero(self):
        self.assertEqual(
            evaluate_measure("12.1", "12.0 ± 0.2").status,
            evaluate_measure("12,1", "12,0 +/- 0,2").status,
        )


# ---------------------------------------------------------------------------
# Melhoria 2 — tempo-pessoa
# ---------------------------------------------------------------------------
class TempoPessoaTests(unittest.TestCase):
    def setUp(self):
        self.db, self.service, self.usinagem, _ = _servico_com_roteiro()
        self.db.operator_badges.extend([
            {"id": 91, "cracha": "SIM01", "nome": "Operador A", "ativo": True},
            {"id": 92, "cracha": "SIM02", "nome": "Operador B", "ativo": True},
            {"id": 93, "cracha": "SIM03", "nome": "Operador C", "ativo": True},
        ])
        self.participacoes = OperatorParticipationService(self.db)

    def _iniciar(self, crachas):
        return self.service.executar(
            "Início", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, operadores_cracha=crachas,
        )

    def _apontamento_id(self):
        return self.db.appointments[0]["id"]

    def test_uma_pessoa_abre_uma_participacao_principal(self):
        self.assertTrue(self._iniciar(["SIM01"]).ok)

        resumo = self.participacoes.resumo(self._apontamento_id())
        self.assertEqual(resumo["total_pessoas"], 1)
        self.assertTrue(resumo["pessoas"][0]["principal"])

    def test_tres_pessoas_na_mesma_op_sem_dividir_o_tempo_da_op(self):
        self.assertTrue(self._iniciar(["SIM01", "SIM02", "SIM03"]).ok)

        abertas = self.db.listar_participacoes_apontamento(
            self._apontamento_id(), somente_abertas=True
        )
        self.assertEqual(len(abertas), 3)
        # Só o primeiro é o principal: o operador original é preservado.
        self.assertEqual(sum(1 for row in abertas if row["operador_principal"]), 1)
        self.assertEqual(self.db.appointments[0]["operador_inicio"], "OPERADOR WAVE51")

    def test_mesma_pessoa_repetida_nao_gera_participacao_duplicada(self):
        self.assertTrue(self._iniciar(["SIM01", "SIM01"]).ok)
        # Reentrar com a mesma equipe também não duplica.
        self.service.executar(
            "Setup", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, operadores_cracha=["SIM01"],
        )

        abertas = self.db.listar_participacoes_apontamento(
            self._apontamento_id(), somente_abertas=True
        )
        self.assertEqual(len(abertas), 1)

    def test_troca_de_operador_fecha_quem_saiu_e_preserva_quem_ficou(self):
        self.assertTrue(self._iniciar(["SIM01", "SIM02"]).ok)
        apontamento_id = self._apontamento_id()
        entrada_b = next(
            row for row in self.db.listar_participacoes_apontamento(apontamento_id)
            if row["cracha"] == "SIM02"
        )["data_inicio"]

        self.service.executar(
            "Setup", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, operadores_cracha=["SIM02", "SIM03"],
        )

        linhas = {
            row["cracha"]: row
            for row in self.db.listar_participacoes_apontamento(apontamento_id)
        }
        self.assertIsNotNone(linhas["SIM01"]["data_fim"])
        self.assertIsNone(linhas["SIM02"]["data_fim"])
        # Quem ficou não foi reaberto: o tempo dele é contínuo.
        self.assertEqual(linhas["SIM02"]["data_inicio"], entrada_b)
        self.assertIsNone(linhas["SIM03"]["data_fim"])

    def test_parada_mantem_a_equipe_e_finalizacao_fecha_todo_mundo(self):
        self.assertTrue(self._iniciar(["SIM01", "SIM02"]).ok)
        apontamento_id = self._apontamento_id()

        self.service.executar(
            "Parada", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, motivo_codigo="0029",
        )
        self.assertEqual(
            len(self.db.listar_participacoes_apontamento(apontamento_id, somente_abertas=True)),
            2,
        )

        self.service.executar(
            "Início", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, operadores_cracha=["SIM01", "SIM02"],
        )
        liberar_primeira_peca(
            self.db, "OPERADOR WAVE51", op="OP-WAVE51", setor="Usinagem",
            recurso="Torno Mecânico", operacao=self.usinagem,
        )
        fim = self.service.executar(
            "Finalizado", op="OP-WAVE51", setor="Usinagem", recurso="Torno Mecânico",
            operacao=self.usinagem, pecas_boas=4, operadores_cracha=["SIM01", "SIM02"],
        )
        self.assertTrue(fim.ok, fim.message)
        self.assertEqual(
            self.db.listar_participacoes_apontamento(apontamento_id, somente_abertas=True),
            [],
        )

    def test_tempo_pessoa_soma_as_pessoas_e_nao_divide_o_tempo_da_op(self):
        inicio = datetime(2026, 9, 14, 8, 0, 0)
        for cracha, nome in (("SIM01", "Operador A"), ("SIM02", "Operador B")):
            self.db.iniciar_participacao_operador(
                "Torno Mecânico", cracha=cracha, nome=nome, apontamento_id=1,
                data_inicio=inicio, tipo_setor="Usinagem", op="OP-WAVE51",
            )
        self.db.finalizar_participacoes_apontamento(
            1, data_fim=inicio + timedelta(minutes=60)
        )

        resumo = TraceabilityService(self.db).trace_op("OP-WAVE51")["person_time"]

        self.assertEqual(resumo["total_pessoas"], 2)
        # OP = 60 min; tempo-pessoa = 120 min. Grandezas distintas.
        self.assertEqual(resumo["tempo_pessoa_segundos"], 7200.0)


# ---------------------------------------------------------------------------
# Melhoria 3 — apontamento em setor incorreto
# ---------------------------------------------------------------------------
class ApontamentoEmSetorIncorretoTests(unittest.TestCase):
    def test_rotulo_atual_original(self):
        self.assertEqual(sector_display_label("Dobra", "Usinagem"), "Dobra (Usinagem)")
        self.assertEqual(sector_display_label("Dobra", "Dobra"), "Dobra")
        self.assertEqual(sector_display_label("Dobra", ""), "Dobra")
        self.assertEqual(sector_display_label("Dobra", None), "Dobra")

    def test_apontamento_correto_nao_marca_divergencia(self):
        db, service, usinagem, _ = _servico_com_roteiro()

        self.assertTrue(
            service.executar(
                "Início", op="OP-WAVE51", setor="Usinagem",
                recurso="Torno Mecânico", operacao=usinagem,
            ).ok
        )

        cartoes = service.listar_cartoes("Usinagem", "Torno Mecânico")["production"]
        self.assertEqual(cartoes[0]["setor_exibicao"], "Usinagem")
        self.assertFalse(cartoes[0]["setor_divergente"])

    def test_apontamento_incorreto_confirmado_preserva_a_origem(self):
        db, service, usinagem, _ = _servico_com_roteiro()

        # A Dobra assume a etapa de Usinagem confirmando a exceção com crachá.
        aceito = service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303",
            operacao=usinagem, confirmar_recurso_divergente=True,
            operadores_cracha=["1"],
        )
        self.assertTrue(aceito.ok, aceito.message)

        cartao = service.listar_cartoes("Dobra", "1303")["production"][0]
        self.assertTrue(cartao["setor_divergente"])
        self.assertEqual(cartao["setor_roteiro"], "Usinagem")
        self.assertEqual(cartao["setor_exibicao"], "Dobra (Usinagem)")

        # O evento histórico continua existindo com a mesma origem: nada foi
        # apagado nem reescrito.
        evento = db.operator_events[-1]
        self.assertTrue(evento["setor_divergente"])
        self.assertEqual(evento["setor_roteiro"], "Usinagem")

        historico = service.listar_historico("Dobra", "1303")
        self.assertTrue(
            any(item.get("setor_exibicao") == "Dobra (Usinagem)" for item in historico)
            or cartao["setor_exibicao"] == "Dobra (Usinagem)"
        )

    def test_drill_down_da_op_mostra_o_setor_original(self):
        _, service, usinagem, _ = _servico_com_roteiro()
        service.executar(
            "Início", op="OP-WAVE51", setor="Dobra", recurso="1303",
            operacao=usinagem, confirmar_recurso_divergente=True,
            operadores_cracha=["1"],
        )

        operacoes = TraceabilityService(service.db).trace_op("OP-WAVE51")["operations"]
        self.assertEqual(operacoes[0]["setor_exibicao"], "Dobra (Usinagem)")


# ---------------------------------------------------------------------------
# Melhoria 4 — estações de Pintura
# ---------------------------------------------------------------------------
class EstacoesDePinturaTests(unittest.TestCase):
    ESPERADAS = ("Jato", "Preparação", "Pintura", "Secagem", "Inspeção Final")

    def test_as_cinco_estacoes_existem_no_catalogo_do_setor(self):
        self.assertEqual(PAINTING_STATIONS, self.ESPERADAS)
        self.assertEqual(
            OPERATOR_SECTOR_BY_LEVEL["operador_pintura"].resources, self.ESPERADAS
        )

    def test_um_unico_login_de_pintura_continua_atendendo_as_estacoes(self):
        perfis = [
            level for level in OPERATOR_SECTOR_BY_LEVEL
            if level.startswith("operador_pintura")
        ]
        self.assertEqual(perfis, ["operador_pintura"])

    def test_cada_estacao_e_um_recurso_registrado_e_distinto(self):
        """O PC Factory já registra uma máquina por etapa da Pintura."""

        esperado = {
            "Jato": "JATO",
            "Preparação": "PREP",
            "Pintura": "PINT.L",
            "Secagem": "ESTUFA",
            "Inspeção Final": "INSPE2",
        }
        for estacao, codigo in esperado.items():
            with self.subTest(estacao=estacao):
                self.assertEqual(station_resource_code("Pintura", estacao), codigo)
        # Identidades distintas: nenhuma estação some dentro de outra.
        self.assertEqual(len(set(esperado.values())), len(esperado))

    def test_toda_estacao_aponta_as_operacoes_de_pintura_do_roteiro(self):
        """Pintura é setor dono do recurso: qualquer estação atende o roteiro."""

        for estacao in self.ESPERADAS:
            for codigo in ("PINT.L", "JATO"):
                with self.subTest(estacao=estacao, codigo=codigo):
                    self.assertTrue(
                        station_matches_route(
                            "Pintura", estacao, codigo, resource_sector="Pintura"
                        )
                    )

    def test_estacao_de_pintura_nao_aponta_operacao_de_outro_setor(self):
        self.assertFalse(station_matches_route("Pintura", "Jato", "DOBRA3"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
