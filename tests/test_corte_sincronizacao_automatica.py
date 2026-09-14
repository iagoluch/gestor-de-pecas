"""Wave 2/3 — a fila do Corte não depende de pesquisa manual, e agora é observável.

O que estes testes protegem:

- o Gestor materializa o planejamento sozinho, com o MESMO
  ``SigmaNestSyncService`` do script de linha de comando (não existe um segundo
  pipeline SigmaNEST);
- o botão **Atualizar** usa exatamente o mesmo caminho do ciclo automático;
- ciclo automático e botão nunca rodam em paralelo: quem chega durante um
  ciclo adere a ele em vez de abrir outro;
- falha de leitura na origem **não** apaga a fila local nem vaza detalhe
  técnico para o operador;
- a invalidação para a tela só é publicada quando o conjunto projetado muda;
- a tarefa de fundo só existe quando o ambiente habilita a sincronização.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import unittest

from backend.api.config import WebSettings
from backend.api.main import _sigmanest_sync_loop
from mes.services.sigmanest_refresh import SigmaNestRefreshCoordinator
from mes.services.sigmanest_sync import SigmaNestSyncResult

from tests.fakes import FakeDatabase


def _settings(**extra) -> WebSettings:
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
        serve_static=False,
        **extra,
    )


def _resultado(assinatura="a", **extra) -> SigmaNestSyncResult:
    base = {
        "assinatura": assinatura,
        "nestings": 2,
        "concluido_em": datetime(2026, 9, 4, 15, 2),
        "iniciado_em": datetime(2026, 9, 4, 15, 1, 58),
    }
    base.update(extra)
    return SigmaNestSyncResult(**base)


class _GatewayFake:
    """Só precisa existir: quem lê o SigmaNEST é o serviço canônico."""


class _ServicoFake:
    """Substitui o SigmaNestSyncService para controlar o roteiro do ciclo."""

    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.chamadas = []

    def __call__(self, db, gateway):
        self.db = db
        self.gateway = gateway
        return self

    def sincronizar(self, **kwargs):
        self.chamadas.append(kwargs)
        proximo = self.resultados.pop(0) if self.resultados else _resultado()
        if isinstance(proximo, Exception):
            raise proximo
        return proximo


class _PublisherFake:
    def __init__(self):
        self.topicos = []

    def publish(self, topic="data"):
        self.topicos.append(topic)


class _EstadoFake:
    """Mínimo do ``app.state`` consumido pelo ciclo de sincronização."""

    def __init__(self, settings, publisher, coordinator):
        self.settings = settings
        self.realtime = publisher
        self.sigmanest_refresh = coordinator


class _AppFake:
    def __init__(self, state):
        self.state = state


def _coordenador(resultados, *, gateway_factory=None, db=None):
    servico = _ServicoFake(resultados)
    coordinator = SigmaNestRefreshCoordinator(
        database_provider=lambda: db or FakeDatabase(),
        gateway_factory=gateway_factory or _GatewayFake,
        service_factory=servico,
    )
    return coordinator, servico


class CoordenadorDeSincronizacaoTests(unittest.IsolatedAsyncioTestCase):
    async def test_ciclo_usa_o_servico_canonico_e_a_janela_incremental(self):
        coordinator, servico = _coordenador([_resultado(nestings_novos=2)])
        resposta = await coordinator.sincronizar(origem="automatico")
        self.assertTrue(resposta["ok"])
        self.assertEqual(servico.chamadas, [{"overlap_days": 7}])
        self.assertEqual(coordinator.state.ciclos, 1)
        self.assertEqual(
            coordinator.state.ultima_sincronizacao, datetime(2026, 9, 4, 15, 2)
        )

    async def test_botao_atualizar_usa_o_mesmo_caminho_do_ciclo(self):
        coordinator, servico = _coordenador([_resultado(), _resultado()])
        await coordinator.sincronizar(origem="automatico")
        manual = await coordinator.sincronizar(origem="manual")
        self.assertEqual(manual["origem"], "manual")
        self.assertEqual(len(servico.chamadas), 2)
        # Mesma chamada, mesmo serviço: não existe segundo pipeline.
        self.assertEqual(servico.chamadas[0], servico.chamadas[1])

    async def test_mensagem_distingue_novidade_de_nenhuma_tarefa_nova(self):
        coordinator, _servico = _coordenador([
            _resultado(assinatura="a", tarefas_novas=3, tarefas_atualizadas=2),
            _resultado(assinatura="a"),
        ])
        com_novidade = await coordinator.sincronizar(origem="manual")
        self.assertIn("3 nova(s)", com_novidade["mensagem"])
        self.assertIn("2 atualizada(s)", com_novidade["mensagem"])
        sem_novidade = await coordinator.sincronizar(origem="manual")
        self.assertEqual(sem_novidade["mensagem"], "nenhuma tarefa nova")

    async def test_clique_durante_ciclo_adere_em_vez_de_abrir_outro(self):
        liberado = asyncio.Event()
        chamadas = {"total": 0}

        class _ServicoLento(_ServicoFake):
            def sincronizar(self, **kwargs):
                chamadas["total"] += 1
                # Simula a leitura demorada da origem sem travar o teste.
                import time

                while not liberado.is_set():
                    time.sleep(0.005)
                return _resultado()

        coordinator, _servico = _coordenador([], gateway_factory=_GatewayFake)
        coordinator._service_factory = _ServicoLento([])

        automatico = asyncio.create_task(coordinator.sincronizar(origem="automatico"))
        await asyncio.sleep(0.05)
        manual = asyncio.create_task(coordinator.sincronizar(origem="manual"))
        await asyncio.sleep(0.05)
        liberado.set()
        primeiro, segundo = await asyncio.gather(automatico, manual)

        # Uma única leitura na origem, mesmo com duas solicitações.
        self.assertEqual(chamadas["total"], 1)
        self.assertTrue(primeiro["ok"])
        self.assertTrue(segundo["aderiu_a_ciclo_em_andamento"])

    async def test_origem_indisponivel_preserva_a_fila_e_nao_vaza_detalhe(self):
        coordinator, _servico = _coordenador([RuntimeError("timeout no ODBC")])
        with self.assertLogs(level="ERROR"):
            resposta = await coordinator.sincronizar(origem="manual")
        self.assertFalse(resposta["ok"])
        self.assertEqual(resposta["mensagem"], coordinator.MENSAGEM_ERRO)
        self.assertNotIn("ODBC", resposta["mensagem"])
        # A tela continua com a última fila: nada foi apagado aqui.
        self.assertIsNone(coordinator.state.ultima_sincronizacao)

    async def test_falha_de_um_ciclo_nao_interrompe_o_seguinte(self):
        coordinator, servico = _coordenador([
            RuntimeError("origem indisponível"),
            _resultado(),
        ])
        with self.assertLogs(level="ERROR"):
            await coordinator.sincronizar(origem="automatico")
        segunda = await coordinator.sincronizar(origem="automatico")
        self.assertTrue(segunda["ok"])
        self.assertEqual(len(servico.chamadas), 2)
        self.assertIsNone(coordinator.state.ultimo_erro)

    async def test_gateway_indisponivel_nao_derruba_a_api(self):
        def _quebrado():
            raise RuntimeError("SigmaNEST não configurado")

        coordinator, _servico = _coordenador([], gateway_factory=_quebrado)
        with self.assertLogs(level="ERROR"):
            resposta = await coordinator.sincronizar(origem="manual")
        self.assertFalse(resposta["ok"])
        self.assertEqual(resposta["mensagem"], coordinator.MENSAGEM_ERRO)

    async def test_diagnostico_expoe_janela_e_watermark(self):
        coordinator, _servico = _coordenador([
            _resultado(
                watermark=datetime(2026, 8, 28),
                janela_inicio=datetime(2026, 8, 28),
                janela_fim=datetime(2026, 9, 4, 15, 2),
                overlap_dias=7,
                tarefas=4,
                nestings_novos=1,
            )
        ])
        await coordinator.sincronizar(origem="automatico")
        diagnostico = coordinator.state.ultimo_resultado
        self.assertEqual(diagnostico["origem"], "sigmanest")
        self.assertEqual(diagnostico["watermark"], datetime(2026, 8, 28))
        self.assertEqual(diagnostico["overlap_dias"], 7)
        self.assertEqual(diagnostico["janela_inicio"], datetime(2026, 8, 28))
        self.assertEqual(diagnostico["janela_fim"], datetime(2026, 9, 4, 15, 2))
        self.assertIn("duracao_segundos", diagnostico)


class CicloAutomaticoTests(unittest.IsolatedAsyncioTestCase):
    async def _rodar_ciclos(self, resultados, *, ciclos):
        coordinator, servico = _coordenador(resultados)
        publisher = _PublisherFake()
        estado = _EstadoFake(
            _settings(sigmanest_sync_enabled=True), publisher, coordinator
        )
        import backend.api.main as main

        original_sleep = asyncio.sleep
        restantes = {"valor": ciclos}

        async def _sleep_controlado(_segundos):
            restantes["valor"] -= 1
            if restantes["valor"] <= 0:
                raise asyncio.CancelledError
            await original_sleep(0)

        main.asyncio.sleep = _sleep_controlado
        try:
            with self.assertRaises(asyncio.CancelledError):
                await _sigmanest_sync_loop(_AppFake(estado))
        finally:
            main.asyncio.sleep = original_sleep
        return servico, publisher

    async def test_repetir_a_mesma_realidade_nao_publica_de_novo(self):
        servico, publisher = await self._rodar_ciclos(
            [
                _resultado(assinatura="a"),
                _resultado(assinatura="a"),
                _resultado(assinatura="b"),
            ],
            ciclos=3,
        )
        self.assertEqual(len(servico.chamadas), 3)
        # Dois ciclos idênticos = uma publicação; a mudança gera a segunda.
        self.assertEqual(publisher.topicos, ["cutting_queue", "cutting_queue"])

    async def test_ciclo_com_falha_nao_publica_invalidacao(self):
        with self.assertLogs(level="ERROR"):
            _servico, publisher = await self._rodar_ciclos(
                [RuntimeError("origem indisponível")], ciclos=1
            )
        self.assertEqual(publisher.topicos, [])


class CorteSincronizacaoLifespanTests(unittest.TestCase):
    def test_tarefa_de_fundo_so_existe_quando_o_ambiente_habilita(self):
        # O objetivo é o contrato de configuração, não o agendamento em si.
        self.assertFalse(_settings().sigmanest_sync_enabled)
        self.assertTrue(
            _settings(sigmanest_sync_enabled=True).sigmanest_sync_enabled
        )

    def test_configuracao_do_sigmanest_liga_a_sincronizacao_por_padrao(self):
        ambiente = {
            "GESTOR_WEB_SESSION_SECRET": "x" * 48,
            "SIGMANEST_SERVER": "servidor,1433",
            "SIGMANEST_DATABASE": "SNDBase2026",
        }
        self.assertTrue(WebSettings.from_env(ambiente).sigmanest_sync_enabled)
        self.assertFalse(
            WebSettings.from_env(
                {**ambiente, "GESTOR_SIGMANEST_SYNC_ENABLED": "false"}
            ).sigmanest_sync_enabled
        )
        # Sem SigmaNEST configurado nada é agendado.
        self.assertFalse(
            WebSettings.from_env(
                {"GESTOR_WEB_SESSION_SECRET": "x" * 48}
            ).sigmanest_sync_enabled
        )


if __name__ == "__main__":
    unittest.main()
