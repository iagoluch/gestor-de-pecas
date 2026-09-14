"""Coordenação de uma única sincronização SigmaNEST por vez.

O Gestor tem duas origens para a mesma sincronização: o ciclo automático do
processo Web e o botão **Atualizar** da tela de Corte. Ambas chamam o MESMO
``SigmaNestSyncService`` — não existe um segundo pipeline. O que este módulo
acrescenta é a disciplina entre elas:

* um ciclo por vez (``asyncio.Lock``); quem chegar durante um ciclo em
  andamento **espera e recebe o resultado dele**, em vez de disparar outro;
* o último resultado bem-sucedido fica guardado, para a tela mostrar
  "última sincronização" mesmo quando o ciclo não alterou nada;
* falha de leitura nunca apaga a fila local: o erro é registrado e a
  projeção anterior continua valendo.

Nada aqui escreve no SigmaNEST.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging

from mes.services.sigmanest_sync import DEFAULT_OVERLAP_DAYS, SigmaNestSyncService


@dataclass
class SigmaNestRefreshState:
    """Situação observável da sincronização, sem detalhe técnico na tela."""

    ultima_sincronizacao: datetime | None = None
    ultimo_erro_em: datetime | None = None
    ultimo_erro: str | None = None
    executando: bool = False
    ciclos: int = 0
    ultimo_resultado: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ultima_sincronizacao": self.ultima_sincronizacao,
            "ultimo_erro_em": self.ultimo_erro_em,
            "ultimo_erro": self.ultimo_erro,
            "executando": self.executando,
            "ciclos": self.ciclos,
            "ultimo_resultado": dict(self.ultimo_resultado),
        }


class SigmaNestRefreshCoordinator:
    """Serializa ciclo automático e atualização manual do Corte."""

    #: Frases de operador. Nenhuma delas expõe stack trace ou nome de tabela.
    MENSAGEM_ERRO = (
        "Não foi possível atualizar as tarefas. "
        "Exibindo a última fila sincronizada."
    )

    def __init__(
        self,
        *,
        database_provider,
        gateway_factory,
        overlap_days: int = DEFAULT_OVERLAP_DAYS,
        now_func=None,
        service_factory=None,
    ):
        self._database_provider = database_provider
        self._gateway_factory = gateway_factory
        self._overlap_days = int(overlap_days)
        self._now = now_func or datetime.now
        self._service_factory = service_factory or SigmaNestSyncService
        self._lock = asyncio.Lock()
        self._gateway = None
        self.state = SigmaNestRefreshState()

    # ------------------------------------------------------------------
    def _resolver_gateway(self):
        if self._gateway is None:
            self._gateway = self._gateway_factory()
        return self._gateway

    def _executar(self):
        """Ciclo síncrono; roda fora do laço de eventos via ``to_thread``."""

        service = self._service_factory(
            self._database_provider(), self._resolver_gateway()
        )
        return service.sincronizar(overlap_days=self._overlap_days)

    async def sincronizar(self, *, origem="automatico"):
        """Executa um ciclo, ou adere ao ciclo que já estiver em andamento.

        Retorna sempre um dicionário com ``ok``, ``mensagem`` e o diagnóstico
        do último ciclo conhecido. Nunca levanta: a fila local sobrevive à
        indisponibilidade do SigmaNEST.
        """

        if self._lock.locked():
            # Já existe ciclo em curso. Aguardar e devolver o resultado dele
            # evita duas leituras concorrentes e duas invalidações de tela.
            async with self._lock:
                return {
                    "ok": self.state.ultimo_erro is None,
                    "origem": origem,
                    "aderiu_a_ciclo_em_andamento": True,
                    "mensagem": (
                        self.MENSAGEM_ERRO if self.state.ultimo_erro
                        else "Sincronização já estava em andamento."
                    ),
                    **self.state.as_dict(),
                }

        async with self._lock:
            self.state.executando = True
            try:
                resultado = await asyncio.to_thread(self._executar)
            except Exception as erro:  # pragma: no cover - caminho de falha
                self.state.ultimo_erro = str(erro)[:300]
                self.state.ultimo_erro_em = self._now()
                logging.exception("Falha ao sincronizar o planejamento do SigmaNEST.")
                return {
                    "ok": False,
                    "origem": origem,
                    "aderiu_a_ciclo_em_andamento": False,
                    "mensagem": self.MENSAGEM_ERRO,
                    **self.state.as_dict(),
                }
            finally:
                self.state.executando = False

            self.state.ultima_sincronizacao = resultado.concluido_em or self._now()
            self.state.ultimo_erro = None
            self.state.ultimo_erro_em = None
            self.state.ciclos += 1
            self.state.ultimo_resultado = resultado.as_dict()
            logging.info("Sincronização SigmaNEST concluída: %s", resultado.resumo())
            return {
                "ok": True,
                "origem": origem,
                "aderiu_a_ciclo_em_andamento": False,
                "mensagem": _mensagem_de_sucesso(resultado),
                "mudou": resultado.houve_novidade,
                "assinatura": resultado.assinatura,
                **self.state.as_dict(),
            }


def _mensagem_de_sucesso(resultado) -> str:
    """Frase curta de operador, no formato pedido pela tela de Corte."""

    if not resultado.houve_novidade:
        return "nenhuma tarefa nova"
    partes = []
    if resultado.tarefas_novas:
        partes.append(f"{resultado.tarefas_novas} nova(s)")
    if resultado.nestings_novos:
        partes.append(f"{resultado.nestings_novos} chapa(s) nova(s)")
    if resultado.tarefas_atualizadas:
        partes.append(f"{resultado.tarefas_atualizadas} atualizada(s)")
    return ", ".join(partes)
