"""Aplicação FastAPI que adapta o backend existente sem duplicar domínio."""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import datetime
from datetime import time as day_time
from pathlib import Path
from zoneinfo import ZoneInfo
import asyncio
import logging
import os
import time
import uuid

import anyio.to_thread
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.api.config import WebSettings
from backend.api.clock import ApplicationClock
from backend.ai import GroqProvider
from backend.ai.rate_limit_state import AIRateLimitState
from backend.api.database import DatabaseManager
from backend.api.errors import register_error_handlers
from backend.api.routers import (
    ai,
    andon,
    analytics,
    audit,
    auth,
    chamadas,
    cutting,
    dev_observatory,
    highlight,
    management,
    operations,
    operator,
    orders,
    quality,
    reports,
    system,
    traceability,
    welding,
)
from backend.observability import DevObservatoryRecorder
from backend.observability.capture import record_exception, record_response
from backend.observability.metrics import collect_postgres_metrics
from backend.observability.readonly_db import ReadOnlyDatabaseManager
from backend.observability.shift_report import closed_windows, report_exists
from backend.api.security import SessionSigner
from backend.api.static import SpaStaticFiles
from backend.api.realtime import RealtimeBroker
from backend.api.report_workbook import build_report_workbook
from backend.messaging import TelegramProvider
from backend.integrations import totvs_soap
from backend.integrations.sigmanest_sqlserver import SigmaNestSqlServerGateway
from backend.integrations.totvs_wspcp import TotvsWspcpClient
from mes.integrations.notifications.telegram import (
    answer_telegram_callback_query,
    build_outbox_error_notifier,
    deliver_telegram_message,
    fetch_telegram_updates,
)
from mes.integrations.totvs.on_demand_gateway import build_order_provisioning_service
from mes.integrations.totvs.service import build_totvs_ingestion_service
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.industrial_reports import IndustrialReportService
from mes.services.report_messaging import ReportMessagingService
from mes.services.report_scheduler import ReportScheduler
from mes.services.shift_boundary import ShiftBoundaryService
from mes.services.shift_parameters import load_manufacturing_rules
from mes.services.sigmanest_refresh import SigmaNestRefreshCoordinator
from mes.services.telegram_bot import TelegramFactoryBotService
from mes.services.telegram_digest import (
    TelegramFactoryDigestScheduler,
    build_digest_destinations,
)
from mes.services.totvs_outbox_worker import TotvsOutboxWorker


def _default_database_factory(*, now_func=None, environment="development"):
    from app.database import Database
    from app.database.config import load_postgres_config

    # ``Database()`` sem argumentos é travado para bancos de teste (guarda de
    # segurança em app/database/database.py). O piloto/produção real só é
    # alcançado explicitamente aqui, e só quando o ambiente Web declarado por
    # GESTOR_WEB_ENV é produção — nunca por padrão silencioso.
    if str(environment).strip().casefold() in {"production", "producao", "produção"}:
        config = load_postgres_config(testing=False)
        return Database(config=config, now_func=now_func)
    return Database(now_func=now_func)


def _simulation_target_is_explicit(database) -> bool:
    database_name = str((getattr(database, "safe_target", {}) or {}).get("dbname") or "")
    safe_name = database_name.casefold()
    expected = str(os.getenv("GESTOR_EXPECTED_DATABASE") or "").strip().casefold()
    legacy_explicit = bool({"homolog", "simulacao"} & set(safe_name.split("_")))
    return bool(
        "test" in safe_name
        and (legacy_explicit or (expected and expected == safe_name))
    )


def _build_background_scheduler(application: FastAPI) -> ReportScheduler:
    settings = application.state.settings
    database = application.state.database_manager.get()
    if settings.simulation_mode and not _simulation_target_is_explicit(database):
        raise RuntimeError(
            "Automação recusada: o banco da simulação não é um alvo explícito de teste/homologação."
        )
    clock = getattr(application.state, "clock", None)
    now_func = clock.now if settings.simulation_mode and clock is not None else None
    facade = FrontendBackendFacade(
        database,
        now_func=now_func,
        simulation_mode=settings.simulation_mode,
    )
    report_service = IndustrialReportService(
        facade,
        database,
        artifact_dir=settings.report_artifact_dir,
        workbook_builder=build_report_workbook,
        now_func=getattr(facade, "_now", None),
        expiration_hours=settings.report_expiration_hours,
        max_bytes=settings.report_max_bytes,
        messaging_available=settings.telegram_configured,
    )
    provider = None
    if settings.telegram_configured:
        provider = TelegramProvider(
            bot_token=settings.telegram_bot_token,
            timeout_seconds=settings.telegram_timeout_seconds,
        )
    messaging_service = ReportMessagingService(
        database,
        report_service,
        provider=provider,
        enabled=settings.telegram_enabled,
        configured=settings.telegram_configured,
        now_func=getattr(facade, "_now", None),
    )
    return ReportScheduler(
        database,
        report_service,
        messaging_service=messaging_service,
    )


async def _report_scheduler_loop(application: FastAPI) -> None:
    interval = application.state.settings.report_scheduler_interval_seconds
    while True:
        try:
            scheduler = _build_background_scheduler(application)
            await scheduler.run_due()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Falha controlada no ciclo do agendador de relatórios.")
        await asyncio.sleep(interval)


def _build_totvs_outbox_worker(application: FastAPI) -> TotvsOutboxWorker:
    settings = application.state.settings
    database = application.state.database_manager.get()
    return TotvsOutboxWorker(
        database,
        gateway=TotvsWspcpClient.from_env(),
        batch_size=settings.totvs_outbox_batch_size,
        lease_seconds=settings.totvs_outbox_lease_seconds,
        max_attempts=settings.totvs_outbox_max_attempts,
        error_notifier=build_outbox_error_notifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.totvs_outbox_telegram_chat_id,
        ),
    )


async def _totvs_outbox_worker_loop(application: FastAPI) -> None:
    """Entrega da outbox TOTVS, fora do caminho crítico do operador.

    A recuperação de fila acontece no primeiro ciclo, logo após o start: itens
    ``PENDING`` antigos, ``RETRY`` vencidos e ``SENDING`` abandonados por um
    processo morto voltam a ser processados sem intervenção manual. No
    shutdown a task é cancelada e para de reservar; o item que estiver em
    ``SENDING`` volta sozinho por expiração de lease, com a MESMA
    ``idempotency_key``.
    """

    interval = application.state.settings.totvs_outbox_worker_interval_seconds
    while True:
        try:
            worker = _build_totvs_outbox_worker(application)
            cycle = await asyncio.to_thread(worker.run_once)
            if cycle.reserved or cycle.recovered:
                logging.info("Ciclo da outbox TOTVS: %s", cycle.as_dict())
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Falha controlada no ciclo do worker da outbox TOTVS.")
        await asyncio.sleep(interval)


async def _telegram_bot_loop(application: FastAPI) -> None:
    """Long polling do bot de fábrica: comandos privados, nunca o grupo.

    ``getUpdates`` com ``offset`` é suficiente aqui — não há volume que
    justifique webhook, e este ambiente não tem URL pública fixa. O
    ``offset`` avança a cada ciclo, então uma mensagem nunca é processada
    duas vezes mesmo se o processo reiniciar no meio.
    """

    settings = application.state.settings
    interval = settings.telegram_bot_poll_interval_seconds
    token = settings.telegram_bot_token
    offset = None
    while True:
        try:
            database = application.state.database_manager.get()
            service = TelegramFactoryBotService(database)
            updates = await asyncio.to_thread(
                fetch_telegram_updates, bot_token=token, offset=offset
            )
            for update in updates:
                offset = int(update.get("update_id", 0)) + 1
                reply = service.handle_update(update)
                if reply is not None:
                    if reply.callback_query_id:
                        await asyncio.to_thread(
                            answer_telegram_callback_query,
                            bot_token=token,
                            callback_query_id=reply.callback_query_id,
                        )
                    await asyncio.to_thread(
                        deliver_telegram_message,
                        bot_token=token,
                        chat_id=reply.chat_id,
                        text=reply.text,
                        message_id=reply.message_id,
                        parse_mode=reply.parse_mode,
                        reply_markup=reply.reply_markup,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Falha controlada no ciclo do bot de fábrica no Telegram.")
        await asyncio.sleep(interval)


async def _telegram_digest_loop(application: FastAPI) -> None:
    """Resumo diário/quinzenal/mensal por destino, um por período fechado."""

    settings = application.state.settings
    try:
        fuso = ZoneInfo(settings.telegram_digest_timezone)
    except Exception:
        logging.exception(
            "Fuso horário inválido para o resumo do Telegram (%s); usando UTC.",
            settings.telegram_digest_timezone,
        )
        fuso = ZoneInfo("UTC")
    try:
        hora, minuto = (int(part) for part in settings.telegram_digest_daily_time.split(":"))
        horario_execucao = day_time(hour=hora, minute=minuto)
    except Exception:
        logging.exception(
            "Horário inválido para o resumo do Telegram (%s); usando 18:00.",
            settings.telegram_digest_daily_time,
        )
        horario_execucao = day_time(hour=18, minute=0)
    interval = 300
    destinations = build_digest_destinations(
        factory_chat_id=settings.telegram_factory_chat_id,
        sector_chat_ids=settings.telegram_sector_chat_ids,
    )
    while True:
        try:
            database = application.state.database_manager.get()
            scheduler = TelegramFactoryDigestScheduler(
                database,
                bot_token=settings.telegram_bot_token,
                destinations=destinations,
                run_time=horario_execucao,
                timezone=fuso,
            )
            outcomes = await asyncio.to_thread(scheduler.run_due)
            enviados = [item for item in outcomes if item.sent]
            if enviados:
                logging.info(
                    "Resumo(s) de fábrica enviado(s) ao Telegram: %s",
                    [f"{item.frequency}:{item.destination}" for item in enviados],
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Falha controlada no ciclo do resumo de fábrica no Telegram.")
        await asyncio.sleep(interval)


def build_sigmanest_refresh(application: FastAPI) -> SigmaNestRefreshCoordinator:
    """Coordenador único da sincronização de Corte (ciclo + botão Atualizar).

    Ciclo automático e atualização manual dividem o mesmo lock e o mesmo
    ``SigmaNestSyncService``. Não existe segundo pipeline nem consulta ao
    SigmaNEST fora deste caminho.
    """

    settings = application.state.settings
    factory = getattr(
        application.state, "sigmanest_gateway_factory", SigmaNestSqlServerGateway
    )
    return SigmaNestRefreshCoordinator(
        database_provider=application.state.database_manager.get,
        gateway_factory=factory,
        overlap_days=settings.sigmanest_sync_overlap_days,
    )


async def _sigmanest_sync_loop(application: FastAPI) -> None:
    """Materializa o planejamento de Corte sem ação manual do operador.

    Reaproveita exatamente o ``SigmaNestSyncService`` do script de linha de
    comando: leitura somente-leitura no SigmaNEST, projeção idempotente nas
    tabelas ``catalogo_sigmanest_*`` que a fila de Corte já consome. Nenhuma OP
    é criada aqui e nenhum apontamento é gerado. A tela do operador não é
    bloqueada: o ciclo roda fora do laço de eventos e só publica invalidação
    quando o conjunto projetado realmente mudou.
    """

    interval = application.state.settings.sigmanest_sync_interval_seconds
    coordinator = application.state.sigmanest_refresh
    assinatura_anterior = None
    while True:
        try:
            resultado = await coordinator.sincronizar(origem="automatico")
            assinatura = resultado.get("assinatura")
            if resultado.get("ok") and assinatura != assinatura_anterior:
                assinatura_anterior = assinatura
                application.state.realtime.publish("cutting_queue")
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception(
                "Falha controlada no ciclo de sincronização do SigmaNEST."
            )
        await asyncio.sleep(interval)


async def _shift_boundary_loop(application: FastAPI) -> None:
    """Aplica pausas e limites canônicos no relógio ativo da aplicação."""

    clock = application.state.clock
    service = None
    while True:
        try:
            if service is None:
                database = application.state.database_manager.get()
                if clock.simulation_mode and not _simulation_target_is_explicit(database):
                    raise RuntimeError(
                        "Relógio virtual recusado: o banco ativo não é o alvo "
                        "TESTE explicitamente esperado."
                    )
                service = ShiftBoundaryService(database, now_func=clock.now)
            # Os horários (H1/expediente/H2...) são configuráveis pela tela
            # IagoDev (`parametros_turno`); recarregar a cada ciclo é o que
            # torna uma edição efetiva sem reiniciar o processo.
            service.rules = await asyncio.to_thread(
                load_manufacturing_rules, service.db
            )
            result = await asyncio.to_thread(service.apply_due)
            if int(result.get("count") or 0):
                application.state.realtime.publish("shift_boundary")
        except asyncio.CancelledError:
            raise
        except Exception:
            # Se a aquisição inicial do banco falhou, o próximo ciclo tenta
            # novamente. Uma pausa não pode ficar sem scheduler até o restart.
            service = None
            logging.exception("Falha controlada ao aplicar pausas e limites de turno.")
        await asyncio.sleep(1.0)


async def _dev_observatory_loop(application: FastAPI) -> None:
    """Ciclo único do Dev Observatory: amostra, fecha minutos e fecha turnos.

    Três responsabilidades pequenas em um só ciclo porque todas têm o mesmo
    período natural e nenhuma delas escreve no banco:

    * amostra ``pg_stat_*`` do banco da API, para que o relatório de turno tenha
      delta real de deadlock/rollback/crescimento em vez de um retrato pontual;
    * fecha os agregados de latência do minuto anterior;
    * grava o relatório das janelas de turno que acabaram de encerrar. A
      gravação é idempotente: existindo ``report.md``, o ciclo não regrava.
    """

    settings = application.state.settings
    interval = settings.dev_observatory_interval_seconds
    recorder = application.state.dev_observatory
    clock = getattr(application.state, "clock", None)
    while True:
        try:
            try:
                database = application.state.database_manager.get()
                sample = await asyncio.to_thread(collect_postgres_metrics, database)
                recorder.record_database_sample("test", sample)
            except Exception:
                logging.debug("Dev Observatory: amostra de banco indisponível", exc_info=True)
            recorder.flush_metrics()
            now = clock.now() if clock is not None else datetime.now()
            for window in closed_windows(now):
                if report_exists(settings.dev_observatory_report_dir, window):
                    continue
                await asyncio.to_thread(
                    dev_observatory.write_shift_report,
                    application,
                    recorder,
                    window,
                    now,
                )
                logging.info(
                    "Dev Observatory: relatório de turno gravado (%s).",
                    window.directory_name,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Falha controlada no ciclo do Dev Observatory.")
        await asyncio.sleep(interval)


def create_app(*, settings: WebSettings | None = None, database_factory=None) -> FastAPI:
    resolved_settings = settings or WebSettings.from_env()
    clock = ApplicationClock(
        simulation_mode=resolved_settings.simulation_mode,
        reference_time=resolved_settings.simulation_reference_time,
        scale=resolved_settings.simulation_time_scale,
    )
    manager = DatabaseManager(
        database_factory or (
            lambda: _default_database_factory(now_func=clock.now, environment=resolved_settings.environment)
        ),
        retry_seconds=resolved_settings.database_retry_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Rotas síncronas (login, posto do operador, ações) rodam na
        # threadpool padrão do anyio — 40 slots por padrão, bem abaixo do
        # chão de fábrica real. Acima disso, requisições concorrentes ficam
        # na fila do servidor antes mesmo de chegar ao pool do Postgres
        # (medido no teste de carga com 45 operadores simultâneos).
        anyio.to_thread.current_default_thread_limiter().total_tokens = (
            resolved_settings.sync_thread_pool_size
        )
        scheduler_task = None
        shift_boundary_task = None
        outbox_task = None
        sigmanest_task = None
        observatory_task = None
        telegram_bot_task = None
        telegram_digest_task = None
        if resolved_settings.dev_observatory_enabled:
            observatory_task = asyncio.create_task(
                _dev_observatory_loop(_app),
                name="gestor-dev-observatory",
            )
        if resolved_settings.totvs_outbox_worker_enabled:
            outbox_task = asyncio.create_task(
                _totvs_outbox_worker_loop(_app),
                name="gestor-totvs-outbox-worker",
            )
        _app.state.sigmanest_refresh = build_sigmanest_refresh(_app)
        if resolved_settings.sigmanest_sync_enabled:
            sigmanest_task = asyncio.create_task(
                _sigmanest_sync_loop(_app),
                name="gestor-sigmanest-sync",
            )
        if resolved_settings.report_automation_enabled:
            scheduler_task = asyncio.create_task(
                _report_scheduler_loop(_app),
                name="gestor-report-scheduler",
            )
        shift_boundary_task = asyncio.create_task(
            _shift_boundary_loop(_app),
            name="gestor-shift-boundary",
        )
        if resolved_settings.telegram_configured and resolved_settings.telegram_bot_polling_enabled:
            telegram_bot_task = asyncio.create_task(
                _telegram_bot_loop(_app),
                name="gestor-telegram-bot",
            )
        if (
            resolved_settings.telegram_configured
            and resolved_settings.telegram_digest_enabled
            and (
                resolved_settings.telegram_factory_chat_id
                or resolved_settings.telegram_sector_chat_ids
            )
        ):
            telegram_digest_task = asyncio.create_task(
                _telegram_digest_loop(_app),
                name="gestor-telegram-digest",
            )
        try:
            yield
        finally:
            if outbox_task is not None:
                # Para de reservar novos itens. O que estiver em SENDING volta
                # para RETRY por expiração de lease, sem perder mensagem.
                outbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await outbox_task
            if sigmanest_task is not None:
                # Leitura pura: cancelar não deixa estado pendente no Gestor
                # nem no SigmaNEST. O próximo start relê a janela sobreposta.
                sigmanest_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sigmanest_task
            if shift_boundary_task is not None:
                shift_boundary_task.cancel()
                with suppress(asyncio.CancelledError):
                    await shift_boundary_task
            if telegram_bot_task is not None:
                telegram_bot_task.cancel()
                with suppress(asyncio.CancelledError):
                    await telegram_bot_task
            if telegram_digest_task is not None:
                telegram_digest_task.cancel()
                with suppress(asyncio.CancelledError):
                    await telegram_digest_task
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task
            if observatory_task is not None:
                # Observação passiva: cancelar não deixa estado pendente. O que
                # ainda estava em memória é descarregado para disco antes de sair.
                observatory_task.cancel()
                with suppress(asyncio.CancelledError):
                    await observatory_task
                with suppress(Exception):
                    _app.state.dev_observatory.flush_metrics(force=True)
            real_observer = getattr(_app.state, "dev_observatory_real", None)
            if real_observer is not None:
                real_observer.close()
            manager.close()

    application = FastAPI(
        title="Gestor de Peças API",
        version="1.0.0",
        description=(
            "Adaptador HTTP do backend Python do Gestor de Peças. "
            "Indicadores e regras industriais permanecem nos serviços de domínio."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    application.state.settings = resolved_settings
    application.state.clock = clock
    application.state.database_manager = manager
    application.state.session_signer = SessionSigner(
        resolved_settings.session_secret,
        ttl_seconds=resolved_settings.session_ttl_seconds,
    )
    # Capacity limiter dedicado ao hash de senha do login — CPU-bound e
    # isolado da threadpool geral (ver backend/api/routers/auth.py).
    application.state.auth_thread_limiter = anyio.CapacityLimiter(
        resolved_settings.auth_thread_pool_size
    )
    # Segredo e cookie próprios: a sessão do Dev Observatory nunca compartilha
    # nada com a sessão principal (ver backend/api/config.py).
    application.state.dev_observatory_session_signer = SessionSigner(
        resolved_settings.dev_observatory_session_secret,
        ttl_seconds=resolved_settings.dev_observatory_session_ttl_seconds,
    )
    application.state.realtime = RealtimeBroker()
    # Dev Observatory: captura sempre montada quando habilitada, para que um
    # erro ocorrido antes de alguém abrir a tela já esteja registrado.
    application.state.dev_observatory = (
        DevObservatoryRecorder(
            resolved_settings.dev_observatory_report_dir,
            latency_warning_ms=resolved_settings.dev_observatory_latency_warning_ms,
            latency_error_ms=resolved_settings.dev_observatory_latency_error_ms,
        )
        if resolved_settings.dev_observatory_enabled
        else None
    )
    application.state.dev_observatory_real = ReadOnlyDatabaseManager(
        resolved_settings.dev_observatory_real_dsn
        if resolved_settings.dev_observatory_enabled
        else ""
    )
    application.state.ai_provider = GroqProvider(
        api_key=resolved_settings.ai_api_key,
        model=resolved_settings.ai_model,
        reasoning_effort=resolved_settings.ai_reasoning_effort,
        temperature=resolved_settings.ai_temperature,
        max_completion_tokens=resolved_settings.ai_max_completion_tokens,
        request_token_budget=resolved_settings.ai_request_token_budget,
        timeout_seconds=resolved_settings.ai_timeout_seconds,
    )
    application.state.ai_rate_limit = AIRateLimitState()
    application.state.totvs_service_factory = (
        lambda database: build_totvs_ingestion_service(database, resolved_settings)
    )
    # Busca sob demanda: reaproveita o MESMO serviço de ingestão. Não existe um
    # segundo caminho de importação de OP no Gestor. A execução recebe a
    # fronteira neutra e continua sem conhecer a origem do planejamento.
    application.state.order_provisioning_factory = (
        lambda database: build_order_provisioning_service(database, resolved_settings)
    )
    # Planejamento de Corte: um único gateway somente leitura, o mesmo do
    # script manual. Não existe segundo pipeline SigmaNEST no Gestor.
    application.state.sigmanest_gateway_factory = SigmaNestSqlServerGateway
    # Um coordenador por aplicação: é ele que impede dois ciclos concorrentes
    # entre o timer de fundo e o botão Atualizar da tela de Corte.
    application.state.sigmanest_refresh = None

    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(resolved_settings.allowed_hosts),
    )
    # Reduz respostas JSON/XLSX auxiliares grandes sem remover dados do contrato.
    # O middleware preserva Content-Type e não comprime payloads pequenos.
    application.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # O handler genérico de Exception vive acima deste middleware; sem
            # registrar aqui, o 500 não previsto não apareceria no observatório.
            # A exceção segue o caminho normal logo em seguida.
            record_exception(request, exc, (time.perf_counter() - started) * 1000.0)
            raise
        # A latência é medida aqui, no mesmo lugar onde o X-Request-ID nasce, e
        # não em uma camada ASGI extra: o funil de erros já anotou no request o
        # código de negócio, se houve recusa.
        record_response(request, response, (time.perf_counter() - started) * 1000.0)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
            )
        return response

    register_error_handlers(application)
    prefix = "/api/v1"
    application.include_router(system.router, prefix=prefix)
    application.include_router(auth.router, prefix=prefix)
    application.include_router(chamadas.router, prefix=prefix)
    application.include_router(ai.router, prefix=prefix)
    application.include_router(operator.router, prefix=prefix)
    application.include_router(quality.router, prefix=prefix)
    application.include_router(cutting.router, prefix=prefix)
    application.include_router(highlight.router, prefix=prefix)
    application.include_router(andon.router, prefix=prefix)
    application.include_router(welding.router, prefix=prefix)
    application.include_router(management.router, prefix=prefix)
    application.include_router(operations.router, prefix=prefix)
    application.include_router(orders.router, prefix=prefix)
    application.include_router(analytics.router, prefix=prefix)
    application.include_router(audit.router, prefix=prefix)
    application.include_router(traceability.router, prefix=prefix)
    application.include_router(reports.router, prefix=prefix)
    if resolved_settings.dev_observatory_enabled:
        application.include_router(dev_observatory.router, prefix=prefix)
        # A página do observatório vive fora do SPA dos operadores e precisa ser
        # registrada antes do mount estático de "/".
        application.include_router(dev_observatory.page_router)
    # O endpoint legado do ERP não pertence a /api/v1 e precisa preceder o SPA.
    application.include_router(totvs_soap.router)
    static_directory = Path(__file__).resolve().parents[2] / "web" / "dist"
    if resolved_settings.serve_static and (static_directory / "index.html").is_file():
        application.mount("/", SpaStaticFiles(static_directory), name="web")
    return application


app = create_app()
