"""Sincronização de OP sob demanda (Etapa 6.1), sem segunda importação de OP.

Este módulo **não** interpreta ProductionOrder, não projeta roteiro, não
classifica recurso e não grava OP. Ele apenas decide *quando* pedir a OP ao
TOTVS e entrega o que voltar ao pipeline canônico já homologado
(``TotvsProductionOrderIngestionService``), que continua sendo o único lugar
onde uma OP nasce no Gestor.

Regra central da etapa:

    lookup local  → hit  → devolve, sem tocar no ERP
                  → miss → solicita ao TOTVS → pipeline canônico → lookup local

A busca remota é *fallback*, nunca o caminho normal. Uma OP que já existe
localmente jamais provoca chamada ao ERP (§8 da etapa).

Duas formas de entrega são suportadas pela mesma porta, porque a decisão é do
mecanismo que o Protheus oferecer e não do caso de uso:

* ``inline`` — o mecanismo devolve o próprio ``TOTVSMessage/ProductionOrder``.
  O XML é entregue ao pipeline canônico aqui mesmo.
* ``push``   — o mecanismo apenas pede ao Protheus que envie. A mensagem chega
  pelo inbound normal (``/PcfIntegService``) e este caso de uso aguarda o
  aparecimento da OP no catálogo, com prazo limitado.

Nos dois casos o parser, o mapper, as regras de roteiro, a classificação de
recurso, o marco terminal e a persistência são exatamente os mesmos do push
normal. Não há caminho paralelo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.core.normalization import limpa_codigo
from mes.integrations.totvs.errors import TotvsIntegrationError

logger = logging.getLogger(__name__)


# Estados finais devolvidos ao chamador. São de negócio, nunca técnicos: a Tela
# do Operador traduz cada um em uma frase e nunca exibe SOAP/traceback (§5).
STATUS_LOCAL = "local"
STATUS_SINCRONIZADA = "sincronizada"
STATUS_NAO_ENCONTRADA = "nao_encontrada"
STATUS_SEM_ROTEIRO = "sem_roteiro"
STATUS_INDISPONIVEL = "indisponivel"
STATUS_TIMEOUT = "timeout"

# Modos de entrega suportados pela porta de solicitação.
DELIVERY_INLINE = "inline"
DELIVERY_PUSH = "push"

DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_POLL_INTERVAL_SECONDS = 0.5
# Cache negativo curto: evita martelar o ERP quando o operador redigita uma OP
# inexistente. Nunca é fato definitivo — uma OP pode ser criada depois (§14).
DEFAULT_NEGATIVE_TTL_SECONDS = 60


class OnDemandSyncUnavailable(TotvsIntegrationError):
    """O mecanismo de solicitação não está disponível/configurado."""

    def __init__(self, message: str, *, code: str = "totvs_pull_indisponivel"):
        super().__init__(message, code=code)


@dataclass(frozen=True)
class ProductionOrderRequestResult:
    """Resultado bruto de uma solicitação ao Protheus, sem política embutida.

    ``accepted`` significa apenas que o pedido foi aceito, não que a OP existe.
    ``not_found`` é a negativa explícita do ERP. ``unavailable_reason`` separa
    indisponibilidade (transitória) de inexistência (funcional) — confundir as
    duas faria o Gestor dizer "OP não encontrada" quando o ERP está fora.
    """

    accepted: bool = False
    delivery: str = DELIVERY_PUSH
    message_xml: str | None = None
    not_found: bool = False
    unavailable_reason: str | None = None
    detail: str | None = None


class ProductionOrderRequestGateway(Protocol):
    """Porta que sabe pedir uma OP ao Protheus. Não sabe interpretar a resposta."""

    def request_production_order(
        self, *, company_id: str | None, branch_id: str | None, number: str
    ) -> ProductionOrderRequestResult:
        ...


class OnDemandSyncRepository(Protocol):
    def buscar_op_local_totvs(self, codigo_op: str) -> dict | None:
        ...

    def buscar_cabecalho_op_local_totvs(self, codigo_op: str) -> dict | None:
        ...

    def atualizar_produto_modelo(self, produto_codigo: str, modelo: str) -> int:
        ...

    def abrir_solicitacao_sync_op(
        self,
        *,
        codigo_op: str,
        agora: datetime,
        negative_ttl_seconds: int,
        stale_after_seconds: int,
    ) -> dict:
        ...

    def finalizar_solicitacao_sync_op(
        self,
        *,
        solicitacao_id: int,
        status: str,
        agora: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        ...

    def consultar_solicitacao_sync_op(self, codigo_op: str) -> dict | None:
        ...


@dataclass(frozen=True)
class OnDemandSyncOutcome:
    """Resposta do caso de uso. ``op`` é sempre o código normalizado."""

    op: str
    status: str
    order: dict | None = None
    requested: bool = False
    idempotent: bool = False
    elapsed_seconds: float = 0.0
    detail: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def found(self) -> bool:
        return self.status in {STATUS_LOCAL, STATUS_SINCRONIZADA}


# Mensagens de operador. Curtas, sem código interno, sem SOAP (§5).
OPERATOR_MESSAGES = {
    STATUS_LOCAL: "OP carregada.",
    STATUS_SINCRONIZADA: "OP carregada.",
    STATUS_NAO_ENCONTRADA: "OP não encontrada no TOTVS.",
    STATUS_SEM_ROTEIRO: "OP existente no TOTVS, porém sem roteiro operacional utilizável.",
    STATUS_INDISPONIVEL: "Não foi possível consultar o TOTVS no momento.",
    STATUS_TIMEOUT: "Não foi possível consultar o TOTVS no momento.",
}


def operator_message(status: str) -> str:
    return OPERATOR_MESSAGES.get(status, OPERATOR_MESSAGES[STATUS_INDISPONIVEL])


class ProductionOrderOnDemandSyncService:
    """Caso de uso ``sync_production_order_on_demand(op_number)``.

    Concorrência (§7): a exclusão é do PostgreSQL, não do frontend. O primeiro
    pedido de uma OP ausente vira *líder* e é o único que fala com o ERP; os
    demais viram *seguidores* e apenas aguardam o mesmo resultado. Isso vale
    entre processos e entre réplicas, e garante uma sincronização lógica, uma OP
    canônica e nenhuma operação duplicada.
    """

    def __init__(
        self,
        repository: OnDemandSyncRepository,
        *,
        ingestion_service=None,
        gateway: ProductionOrderRequestGateway | None = None,
        model_gateway=None,
        company_id: str | None = None,
        branch_ids: tuple[str, ...] = (),
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        negative_ttl_seconds: int = DEFAULT_NEGATIVE_TTL_SECONDS,
        now_func=None,
        sleep_func=None,
    ):
        self.repository = repository
        self.ingestion_service = ingestion_service
        self.gateway = gateway
        self.model_gateway = model_gateway
        self.company_id = str(company_id or "").strip() or None
        self.branch_ids = tuple(
            str(branch).strip() for branch in branch_ids if str(branch).strip()
        )
        self.timeout_seconds = max(float(timeout_seconds), 0.0)
        self.poll_interval_seconds = max(float(poll_interval_seconds), 0.05)
        self.negative_ttl_seconds = max(int(negative_ttl_seconds), 0)
        self._now = now_func or datetime.now
        if sleep_func is not None:
            self._sleep = sleep_func
        else:  # pragma: no cover - import local para manter o domínio leve
            import time

            self._sleep = time.sleep

    # ------------------------------------------------------------------ API

    @property
    def available(self) -> bool:
        return self.gateway is not None and self.ingestion_service is not None

    def lookup_local(self, op_number: str) -> dict | None:
        """Consulta local pura: nunca aciona o ERP (§8)."""

        codigo = self.normalize(op_number)
        if not codigo:
            return None
        return self.repository.buscar_op_local_totvs(codigo)

    @staticmethod
    def normalize(op_number: str) -> str:
        """Preserva a identidade real da OP (§10).

        O número pode ser alfanumérico (``A9716901001``). Não se remove zero à
        esquerda, não se converte para inteiro e não se corta o código.
        """

        return limpa_codigo(op_number)

    def sync_production_order_on_demand(self, op_number: str) -> OnDemandSyncOutcome:
        codigo = self.normalize(op_number)
        if not codigo:
            raise TotvsIntegrationError(
                "Informe o código da OP.", code="totvs_op_obrigatoria"
            )

        started = self._now()

        # 1. lookup local — o caminho normal termina aqui, sem tocar no ERP.
        local = self.repository.buscar_op_local_totvs(codigo)
        if local is not None:
            return OnDemandSyncOutcome(op=codigo, status=STATUS_LOCAL, order=local)
        # "Cabeçalho local sem roteiro" só é resposta terminal quando ninguém
        # está sincronizando esta OP agora. A ingestão grava o cabeçalho antes
        # das operações do roteiro; responder aqui durante a janela de outro
        # operador entregaria `sem_roteiro` para uma OP prestes a ficar pronta.
        incomplete = self._lookup_incomplete_header(codigo)
        if incomplete is not None and not self._lider_ainda_trabalhando(codigo):
            self._reconcile_no_route_request(codigo)
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_SEM_ROTEIRO,
                order=incomplete,
                detail="op_existente_sem_roteiro_operacional",
            )

        if not self.available:
            # Nada é registrado como "OP inexistente": a ausência é do
            # mecanismo, não da OP.
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_INDISPONIVEL,
                detail="mecanismo_de_solicitacao_nao_configurado",
            )

        # 2. exclusão por OP: uma sincronização lógica por OP ausente.
        claim = self.repository.abrir_solicitacao_sync_op(
            codigo_op=codigo,
            agora=started,
            negative_ttl_seconds=self.negative_ttl_seconds,
            stale_after_seconds=int(self.timeout_seconds) + 30,
        )
        role = str(claim.get("role") or "")

        if role == "negative_cache":
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_NAO_ENCONTRADA,
                idempotent=True,
                detail="cache_negativo",
                elapsed_seconds=self._elapsed(started),
            )
        if role == "follower":
            return self._await_result(codigo, started, requested=False)

        solicitacao_id = int(claim["id"])
        try:
            return self._lead(codigo, solicitacao_id, started)
        except Exception:
            # Falha inesperada não pode deixar a OP travada para o próximo
            # operador nem criar dado parcial.
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id,
                status="ERROR",
                agora=self._now(),
                error_code="erro_interno",
                error_message="Falha interna ao solicitar a OP ao TOTVS.",
            )
            raise

    # -------------------------------------------------------------- interno

    def _lead(self, codigo: str, solicitacao_id: int, started: datetime) -> OnDemandSyncOutcome:
        # Uma OP existe em uma única filial no Protheus; sem saber qual, tenta
        # cada filial configurada em ordem e para na primeira que não devolver
        # "não encontrada". Erros de transporte/indisponibilidade não avançam
        # a varredura — não faz sentido multiplicar tentativas numa queda real.
        branches = self.branch_ids or (None,)
        resolved_branch_id = branches[0]
        for index, branch_id in enumerate(branches):
            result = self.gateway.request_production_order(
                company_id=self.company_id, branch_id=branch_id, number=codigo
            )
            resolved_branch_id = branch_id
            if not result.not_found or index == len(branches) - 1:
                break

        if result.unavailable_reason:
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id,
                status="UNAVAILABLE",
                agora=self._now(),
                error_code=result.unavailable_reason,
                error_message=result.detail,
            )
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_INDISPONIVEL,
                requested=True,
                detail=result.unavailable_reason,
                elapsed_seconds=self._elapsed(started),
            )

        if result.not_found:
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id,
                status="NOT_FOUND",
                agora=self._now(),
                error_code="op_inexistente_no_totvs",
                error_message=result.detail,
            )
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_NAO_ENCONTRADA,
                requested=True,
                elapsed_seconds=self._elapsed(started),
            )

        if not result.accepted:
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id,
                status="UNAVAILABLE",
                agora=self._now(),
                error_code="solicitacao_recusada",
                error_message=result.detail,
            )
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_INDISPONIVEL,
                requested=True,
                detail="solicitacao_recusada",
                elapsed_seconds=self._elapsed(started),
            )

        warnings: tuple[str, ...] = ()
        if result.delivery == DELIVERY_INLINE:
            if not str(result.message_xml or "").strip():
                self.repository.finalizar_solicitacao_sync_op(
                    solicitacao_id=solicitacao_id,
                    status="UNAVAILABLE",
                    agora=self._now(),
                    error_code="resposta_sem_production_order",
                    error_message=result.detail,
                )
                return OnDemandSyncOutcome(
                    op=codigo,
                    status=STATUS_INDISPONIVEL,
                    requested=True,
                    detail="resposta_sem_production_order",
                    elapsed_seconds=self._elapsed(started),
                )
            # Mesmo pipeline do push: parser, mapper, roteiro, recurso, marco
            # terminal e persistência canônica. Nada é remontado aqui.
            try:
                outcome = self.ingestion_service.handle_message(result.message_xml)
            except TotvsIntegrationError as exc:
                self.repository.finalizar_solicitacao_sync_op(
                    solicitacao_id=solicitacao_id,
                    status="ERROR",
                    agora=self._now(),
                    error_code=getattr(exc, "code", "totvs_integration_error"),
                    error_message=str(exc)[:500],
                )
                return OnDemandSyncOutcome(
                    op=codigo,
                    status=STATUS_INDISPONIVEL,
                    requested=True,
                    detail=getattr(exc, "code", "totvs_integration_error"),
                    elapsed_seconds=self._elapsed(started),
                )
            ingestion = getattr(outcome, "ingestion", None)
            if ingestion is not None:
                warnings = tuple(getattr(ingestion, "warnings", ()) or ())

        found, incomplete = self._poll_local(codigo, started)
        if found is not None:
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id, status="DONE", agora=self._now()
            )
            self._sync_product_model_best_effort(found, branch_id=resolved_branch_id)
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_SINCRONIZADA,
                order=found,
                requested=True,
                elapsed_seconds=self._elapsed(started),
                warnings=warnings,
            )
        if incomplete is not None:
            self.repository.finalizar_solicitacao_sync_op(
                solicitacao_id=solicitacao_id, status="DONE", agora=self._now()
            )
            self._sync_product_model_best_effort(incomplete, branch_id=resolved_branch_id)
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_SEM_ROTEIRO,
                order=incomplete,
                requested=True,
                detail="op_existente_sem_roteiro_operacional",
                elapsed_seconds=self._elapsed(started),
                warnings=warnings,
            )

        # Aceito, sem negativa explícita e sem OP no prazo: é indisponibilidade,
        # não inexistência. Não vira cache negativo.
        self.repository.finalizar_solicitacao_sync_op(
            solicitacao_id=solicitacao_id,
            status="TIMEOUT",
            agora=self._now(),
            error_code="prazo_esgotado",
            error_message=None,
        )
        return OnDemandSyncOutcome(
            op=codigo,
            status=STATUS_TIMEOUT,
            requested=True,
            detail="prazo_esgotado",
            elapsed_seconds=self._elapsed(started),
        )

    def _await_result(self, codigo: str, started: datetime, *, requested: bool) -> OnDemandSyncOutcome:
        """Seguidor: espera o líder, sem abrir uma segunda sincronização."""

        found, incomplete = self._poll_local(codigo, started, aguardando_lider=True)
        if found is not None:
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_SINCRONIZADA,
                order=found,
                requested=requested,
                idempotent=True,
                elapsed_seconds=self._elapsed(started),
            )
        if incomplete is not None:
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_SEM_ROTEIRO,
                order=incomplete,
                requested=requested,
                idempotent=True,
                detail="op_existente_sem_roteiro_operacional",
                elapsed_seconds=self._elapsed(started),
            )
        current = self.repository.consultar_solicitacao_sync_op(codigo) or {}
        status = str(current.get("status") or "")
        if status == "NOT_FOUND":
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_NAO_ENCONTRADA,
                idempotent=True,
                elapsed_seconds=self._elapsed(started),
            )
        if status in {"UNAVAILABLE", "ERROR"}:
            return OnDemandSyncOutcome(
                op=codigo,
                status=STATUS_INDISPONIVEL,
                idempotent=True,
                detail=str(current.get("error_code") or "") or None,
                elapsed_seconds=self._elapsed(started),
            )
        return OnDemandSyncOutcome(
            op=codigo,
            status=STATUS_TIMEOUT,
            idempotent=True,
            detail="prazo_esgotado",
            elapsed_seconds=self._elapsed(started),
        )

    def _sync_product_model_best_effort(self, order: dict, *, branch_id: str | None = None) -> None:
        """Busca o MODELO do produto após uma OP nascer, sem bloquear o operador.

        ``B1_ZMODELO`` só tem sentido para conjunto soldado — é o campo que a
        tela `/welding-management` mostra na coluna MÁQUINA/MODELO. Consultar
        para toda OP seria uma chamada ao TOTVS sem consumidor nenhum, então
        só dispara quando a OP tem operação ativa em algum setor da frente de
        Solda.

        Best-effort de propósito: a OP acabou de ser provisionada com sucesso e
        isso não pode regredir por causa de um campo auxiliar. Sem
        ``model_gateway`` configurado, ou se o modelo já está preenchido, não
        toca no ERP — mesma regra do lookup de OP (§8): nunca consulta o que já
        tem localmente.
        """

        if self.model_gateway is None:
            return
        produto_codigo = str((order or {}).get("produto_codigo") or "").strip()
        if not produto_codigo:
            return
        if str((order or {}).get("produto_modelo") or "").strip():
            return
        codigo_op = str((order or {}).get("codigo_op") or "").strip()
        verificar_solda = getattr(self.repository, "op_possui_operacao_solda", None)
        if callable(verificar_solda):
            try:
                if not verificar_solda(codigo_op):
                    return
            except Exception:  # noqa: BLE001 - checagem auxiliar nunca propaga, mas fica logada
                logger.exception(
                    "Falha ao checar operação de Solda da OP %s ao sincronizar modelo do produto %s (best-effort)",
                    codigo_op,
                    produto_codigo,
                )
                return
        try:
            result = self.model_gateway.request_product_model(
                company_id=self.company_id, branch_id=branch_id, product_code=produto_codigo
            )
        except Exception:  # noqa: BLE001 - falha de transporte nunca propaga, mas fica logada
            logger.exception(
                "Falha ao consultar modelo do produto %s no TOTVS (best-effort, OP %s)",
                produto_codigo,
                codigo_op,
            )
            return
        if not result.accepted:
            return
        atualizar = getattr(self.repository, "atualizar_produto_modelo", None)
        if not callable(atualizar):
            return
        try:
            atualizar(produto_codigo, result.modelo or "")
        except Exception:  # noqa: BLE001 - gravação auxiliar nunca propaga, mas fica logada
            logger.exception(
                "Falha ao gravar modelo do produto %s obtido do TOTVS (best-effort, OP %s)",
                produto_codigo,
                codigo_op,
            )
            return

    def _lookup_incomplete_header(self, codigo: str) -> dict | None:
        loader = getattr(self.repository, "buscar_cabecalho_op_local_totvs", None)
        if not callable(loader):
            return None
        return loader(codigo)

    def _reconcile_no_route_request(self, codigo: str) -> None:
        current = self.repository.consultar_solicitacao_sync_op(codigo) or {}
        request_id = current.get("id")
        status = str(current.get("status") or "")
        if request_id is None or status in {"PENDING", "DONE"}:
            return
        self.repository.finalizar_solicitacao_sync_op(
            solicitacao_id=int(request_id),
            status="DONE",
            agora=self._now(),
        )

    def _lider_ainda_trabalhando(self, codigo: str) -> bool:
        """A solicitação de outro operador ainda está em curso para esta OP."""

        leitor = getattr(self.repository, "consultar_solicitacao_sync_op", None)
        if not callable(leitor):
            return False
        return str((leitor(codigo) or {}).get("status") or "") == "PENDING"

    def _poll_local(
        self,
        codigo: str,
        started: datetime,
        *,
        aguardando_lider: bool = False,
    ) -> tuple[dict | None, dict | None]:
        """Espera limitada: nunca laço infinito, nunca worker global (§6).

        ``aguardando_lider`` distingue o seguidor do líder. A ingestão do líder
        grava o cabeçalho da OP antes das operações de roteiro, então existe uma
        janela em que a OP já está local mas ainda sem roteiro utilizável. Para o
        líder essa leitura é conclusiva — ele acabou de processar a resposta do
        TOTVS. Para o seguidor não é: enquanto a solicitação do líder está
        ``PENDING``, "cabeçalho sem roteiro" significa *ainda não terminou*, e
        não "o TOTVS não tem roteiro para esta OP". Responder ``sem_roteiro``
        nessa janela dava ao segundo operador uma resposta terminal errada sobre
        uma OP que estava prestes a ficar pronta.
        """

        while True:
            found = self.repository.buscar_op_local_totvs(codigo)
            if found is not None:
                return found, None
            incomplete = self._lookup_incomplete_header(codigo)
            esgotou = self._elapsed(started) >= self.timeout_seconds
            if incomplete is not None:
                if not aguardando_lider or not self._lider_ainda_trabalhando(codigo):
                    return None, incomplete
                # Passado o prazo, a resposta parcial vale como antes: o
                # seguidor nunca fica esperando além do próprio timeout.
                if esgotou:
                    return None, incomplete
            elif esgotou:
                return None, None
            self._sleep(self.poll_interval_seconds)

    def _elapsed(self, started: datetime) -> float:
        return max((self._now() - started).total_seconds(), 0.0)


__all__ = [
    "DELIVERY_INLINE",
    "DELIVERY_PUSH",
    "OnDemandSyncOutcome",
    "OnDemandSyncRepository",
    "OnDemandSyncUnavailable",
    "ProductionOrderOnDemandSyncService",
    "ProductionOrderRequestGateway",
    "ProductionOrderRequestResult",
    "STATUS_INDISPONIVEL",
    "STATUS_LOCAL",
    "STATUS_NAO_ENCONTRADA",
    "STATUS_SEM_ROTEIRO",
    "STATUS_SINCRONIZADA",
    "STATUS_TIMEOUT",
    "operator_message",
]
