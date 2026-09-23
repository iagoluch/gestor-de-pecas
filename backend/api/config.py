"""Configuração server-side da camada Web."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import secrets

from dotenv import load_dotenv

from mes.integrations.totvs.response import DEFAULT_GESTOR_IDENTITY


load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "sim", "on"}


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    values = tuple(item.strip() for item in str(value or "").split(",") if item.strip())
    return values or default


def _json_string_map(value: str | None, *, name: str) -> dict[str, str]:
    raw = str(value or "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} deve ser um objeto JSON válido.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} deve ser um objeto JSON.")
    result = {}
    for key, item in parsed.items():
        source = str(key).strip()
        target = str(item).strip() if isinstance(item, str) else ""
        if not source or not target:
            raise RuntimeError(f"{name} aceita somente chaves e valores de texto não vazios.")
        result[source] = target
    return result


def _text_option(value: str | None, *, default: str) -> str:
    return str(value or "").strip() or default


def _bounded_int(value: str | None, *, default: int, minimum: int, maximum: int, name: str) -> int:
    try:
        parsed = int(str(value if value is not None else default).strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} deve ser um número inteiro.") from exc
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{name} deve estar entre {minimum} e {maximum}.")
    return parsed


def _bounded_float(
    value: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
    name: str,
) -> float:
    try:
        parsed = float(str(value if value is not None else default).strip())
    except ValueError as exc:
        raise RuntimeError(f"{name} deve ser numérica.") from exc
    if not minimum <= parsed <= maximum:
        raise RuntimeError(f"{name} deve estar entre {minimum:g} e {maximum:g}.")
    return parsed


@dataclass(frozen=True)
class WebSettings:
    environment: str
    session_secret: str
    session_ttl_seconds: int = 28_800
    cookie_secure: bool = False
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver", "gestor-peca")
    public_host: str = "gestor-peca"
    serve_static: bool = True
    stream_interval_seconds: int = 15
    database_retry_seconds: int = 5
    # Rotas síncronas (login, posto do operador, ações) rodam na threadpool
    # padrão do anyio, travada em 40 slots por padrão — bem abaixo do chão de
    # fábrica real. Sem isso, operadores concorrentes ficam na fila do
    # servidor antes mesmo de chegar ao banco (medido no teste de carga).
    sync_thread_pool_size: int = 100
    # Fila própria e pequena para o hash de senha (PBKDF2, CPU-bound): mais
    # threads não aceleram trabalho de CPU, só disputam os mesmos núcleos.
    # Isolada da threadpool geral para que um pico de logins não atrase quem
    # já está com o posto aberto.
    auth_thread_pool_size: int = 8
    session_cookie_name: str = "gestor_session"
    csrf_cookie_name: str = "gestor_csrf"
    simulation_mode: bool = False
    simulation_reference_time: datetime | None = None
    simulation_time_scale: float = 0.0
    ai_enabled: bool = False
    ai_api_key: str = field(default="", repr=False)
    ai_model: str = "openai/gpt-oss-120b"
    ai_reasoning_effort: str = "medium"
    ai_temperature: float = 0.2
    ai_max_completion_tokens: int = 640
    ai_max_tool_rounds: int = 6
    ai_max_history_messages: int = 20
    ai_request_token_budget: int = 6_000
    ai_tool_result_max_chars: int = 10_000
    ai_timeout_seconds: float = 60.0
    report_artifact_dir: str = str(Path(__file__).resolve().parents[2] / "dados" / "relatorios_gerados")
    # Desenhos/PDF de produto usados pela inspeção da Qualidade. Mesmo padrão
    # de armazenamento dos relatórios: arquivo em disco, metadado no banco.
    quality_drawing_dir: str = str(
        Path(__file__).resolve().parents[2] / "dados" / "desenhos_produto"
    )
    # Wave 5 — desenhos da peça na rede da engenharia. Caminhos separados por
    # ``;`` porque UNC usa ``\\`` e unidade mapeada usa ``:``. Vazio significa
    # "não configurado": o card do operador mostra estado vazio, nunca erro.
    operator_drawing_roots: str = ""
    report_expiration_hours: int = 168
    report_max_bytes: int = 50 * 1024 * 1024
    report_automation_enabled: bool = False
    report_scheduler_interval_seconds: int = 60
    telegram_enabled: bool = False
    telegram_bot_token: str = field(default="", repr=False)
    telegram_timeout_seconds: float = 30.0
    totvs_enabled: bool = False
    totvs_soap_enabled: bool = False
    totvs_soap_success_result: str = field(default="", repr=False)
    totvs_max_xml_bytes: int = 1_048_576
    totvs_resource_map: dict[str, str] = field(default_factory=dict)
    totvs_sector_map: dict[str, str] = field(default_factory=dict)
    # Identidade própria do Gestor nas respostas ao TOTVS. O Gestor não se
    # apresenta como PCFactory, PPI ou WSPCP.
    totvs_identity_source_application: str = DEFAULT_GESTOR_IDENTITY.source_application
    totvs_identity_product_name: str = DEFAULT_GESTOR_IDENTITY.product_name
    totvs_identity_product_version: str = DEFAULT_GESTOR_IDENTITY.product_version
    totvs_identity_context_name: str = DEFAULT_GESTOR_IDENTITY.context_name
    # Worker da outbox outbound (Etapa 6). Desligado por padrão: habilitar o
    # envio automático ao WSPCP é sempre decisão explícita de ambiente.
    totvs_outbox_worker_enabled: bool = False
    totvs_outbox_worker_interval_seconds: int = 15
    totvs_outbox_batch_size: int = 10
    totvs_outbox_lease_seconds: int = 120
    totvs_outbox_max_attempts: int = 12
    # Busca de OP sob demanda (Etapa 6.1). Desligada enquanto o Protheus não
    # publicar a rotina de solicitação: sem endpoint o Gestor apenas informa
    # indisponibilidade, nunca improvisa uma OP.
    totvs_op_pull_enabled: bool = False
    totvs_op_pull_timeout_seconds: int = 25
    totvs_op_pull_poll_interval_ms: int = 500
    totvs_op_pull_negative_ttl_seconds: int = 60
    totvs_op_pull_company_id: str = ""
    totvs_op_pull_branch_id: str = ""
    # Pendência 2 do piloto (14/09/2026): avisa o supervisor quando a outbox
    # TOTVS para em ERROR (ex.: OP já totalizada). Reaproveita o mesmo bot já
    # configurado em ``telegram_bot_token``; só falta o chat do supervisor. Sem
    # chat_id configurado, o worker segue exatamente como antes — sem aviso.
    totvs_outbox_telegram_chat_id: str = ""
    # Chat mestre de alerta: botão de chamada (operador e gestão) e parada de
    # recurso registrada no posto (decisão do usuário, 21/09/2026). Mesmo bot de
    # ``telegram_bot_token``; sem este chat configurado, a chamada continua
    # sendo registrada no banco e a parada continua sendo apontada — só não sai
    # o aviso, nunca falha silenciosamente sem deixar rastro.
    chamada_telegram_chat_id: str = ""
    # Bot de fábrica no Telegram: comandos privados (crachá -> chat) e
    # resumos automáticos pro grupo. Mesmo bot/token de ``telegram_bot_token``;
    # dois interruptores porque um funcionário pode querer só os resumos, sem
    # ninguém digitando comando nenhum, ou vice-versa.
    telegram_bot_polling_enabled: bool = False
    telegram_bot_poll_interval_seconds: int = 3
    telegram_factory_chat_id: str = ""
    telegram_sector_chat_ids: dict[str, str] = field(default_factory=dict)
    telegram_digest_enabled: bool = False
    telegram_digest_daily_time: str = "18:00"
    telegram_digest_timezone: str = "America/Sao_Paulo"
    # Sincronização automática do planejamento de Corte (Wave 2). O operador do
    # Corte não deve pesquisar para descobrir que existe tarefa nova: o mesmo
    # SigmaNestSyncService do script manual roda em ciclo, somente leitura no
    # SigmaNEST e idempotente no Gestor. Liga sozinha quando o SigmaNEST está
    # configurado no ambiente; GESTOR_SIGMANEST_SYNC_ENABLED sobrepõe.
    sigmanest_sync_enabled: bool = False
    sigmanest_sync_interval_seconds: int = 120
    sigmanest_sync_overlap_days: int = 7
    # Dev Observatory — observabilidade permanente do desenvolvedor. Não é
    # navegação de operador: a rota é separada e o perfil exigido é o de
    # administração. Ligado por padrão em ``from_env`` (custo baixo, valor
    # diagnóstico alto) e desligado na construção direta do dataclass, para que
    # testes e ferramentas internas não escrevam artefatos no projeto sem pedir.
    dev_observatory_enabled: bool = False
    dev_observatory_report_dir: str = str(
        Path(__file__).resolve().parents[2] / "dev_reports"
    )
    dev_observatory_interval_seconds: int = 60
    dev_observatory_latency_warning_ms: float = 1_000.0
    dev_observatory_latency_error_ms: float = 3_000.0
    #: DSN somente leitura do ambiente REAL. Vazio desliga a observação do REAL.
    dev_observatory_real_dsn: str = field(default="", repr=False)
    # Login próprio do Dev Observatory: credencial e sessão vivem fora da
    # tabela `usuarios` e da sessão principal do Gestor, de propósito — uma
    # falha ou mudança no login operacional nunca deve afetar esta ferramenta,
    # nem o contrário. Vazio desliga a ferramenta inteira (falha fechada).
    dev_observatory_login_username: str = field(default="", repr=False)
    dev_observatory_login_password: str = field(default="", repr=False)
    dev_observatory_session_secret: str = field(default="", repr=False)
    dev_observatory_cookie_name: str = "gestor_devobs_session"
    dev_observatory_csrf_cookie_name: str = "gestor_devobs_csrf"
    dev_observatory_session_ttl_seconds: int = 43_200

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key.strip())

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_enabled and self.telegram_bot_token.strip())

    @classmethod
    def from_env(cls, environ=None) -> "WebSettings":
        env = environ if environ is not None else os.environ
        environment = str(env.get("GESTOR_WEB_ENV") or "development").strip().casefold()
        secret = str(env.get("GESTOR_WEB_SESSION_SECRET") or "").strip()
        if not secret:
            if environment in {"production", "producao", "produção"}:
                raise RuntimeError(
                    "GESTOR_WEB_SESSION_SECRET é obrigatória no ambiente de produção."
                )
            secret = secrets.token_urlsafe(48)
            logging.warning(
                "GESTOR_WEB_SESSION_SECRET ausente; usando segredo efêmero apenas para desenvolvimento."
            )
        if len(secret.encode("utf-8")) < 32:
            raise RuntimeError("GESTOR_WEB_SESSION_SECRET deve possuir ao menos 32 bytes.")

        # Segredo de sessão só do Dev Observatory — nunca o mesmo do login
        # principal, para que revogar/girar um não force o outro a girar junto.
        dev_observatory_secret = str(env.get("GESTOR_DEVOBS_SESSION_SECRET") or "").strip()
        if not dev_observatory_secret:
            dev_observatory_secret = secrets.token_urlsafe(48)
            logging.warning(
                "GESTOR_DEVOBS_SESSION_SECRET ausente; usando segredo efêmero "
                "(sessões do Dev Observatory caem a cada reinício do processo)."
            )
        # Mesmo piso do segredo principal: um segredo curto torna a assinatura
        # HMAC do cookie do observatório forjável fora do servidor.
        elif len(dev_observatory_secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "GESTOR_DEVOBS_SESSION_SECRET deve possuir ao menos 32 bytes."
            )

        simulation_mode = _as_bool(env.get("GESTOR_SIMULATION_MODE"), default=False)
        simulation_reference_time = None
        if simulation_mode:
            raw_reference = str(env.get("GESTOR_SIMULATION_NOW") or "").strip()
            if not raw_reference:
                raise RuntimeError(
                    "GESTOR_SIMULATION_NOW é obrigatória quando GESTOR_SIMULATION_MODE está ativo."
                )
            try:
                simulation_reference_time = datetime.fromisoformat(raw_reference)
            except ValueError as exc:
                raise RuntimeError("GESTOR_SIMULATION_NOW deve estar no formato ISO 8601.") from exc
        simulation_time_scale = _bounded_float(
            env.get("GESTOR_SIMULATION_TIME_SCALE"),
            default=0.0,
            minimum=0.0,
            maximum=3_600.0,
            name="GESTOR_SIMULATION_TIME_SCALE",
        )
        if not simulation_mode and simulation_time_scale:
            raise RuntimeError(
                "GESTOR_SIMULATION_TIME_SCALE exige GESTOR_SIMULATION_MODE ativo."
            )

        ai_reasoning_effort = str(
            env.get("GESTOR_AI_REASONING_EFFORT") or "medium"
        ).strip().casefold()
        if ai_reasoning_effort not in {"low", "medium", "high"}:
            raise RuntimeError(
                "GESTOR_AI_REASONING_EFFORT deve ser low, medium ou high."
            )
        ai_model = str(env.get("GESTOR_AI_MODEL") or "openai/gpt-oss-120b").strip()
        if not ai_model:
            raise RuntimeError("GESTOR_AI_MODEL não pode ficar vazio.")

        totvs_enabled = _as_bool(env.get("GESTOR_TOTVS_ENABLED"), default=False)
        totvs_soap_enabled = _as_bool(
            env.get("GESTOR_TOTVS_SOAP_ENABLED"), default=False
        )
        totvs_soap_success_result = str(
            env.get("GESTOR_TOTVS_SOAP_SUCCESS_RESULT") or ""
        ).strip()
        if totvs_soap_enabled and not totvs_enabled:
            raise RuntimeError(
                "GESTOR_TOTVS_SOAP_ENABLED exige GESTOR_TOTVS_ENABLED=true."
            )
        if totvs_soap_enabled and not totvs_soap_success_result:
            raise RuntimeError(
                "GESTOR_TOTVS_SOAP_SUCCESS_RESULT é obrigatória quando o receptor SOAP está ativo."
            )

        sigmanest_configured = bool(
            str(env.get("SIGMANEST_ODBC_DSN") or "").strip()
            or (
                str(env.get("SIGMANEST_SERVER") or "").strip()
                and str(env.get("SIGMANEST_DATABASE") or "").strip()
            )
        )

        return cls(
            environment=environment,
            session_secret=secret,
            session_ttl_seconds=max(300, int(env.get("GESTOR_WEB_SESSION_TTL_SECONDS", "28800"))),
            cookie_secure=_as_bool(
                env.get("GESTOR_WEB_COOKIE_SECURE"),
                default=environment in {"production", "producao", "produção"},
            ),
            allowed_origins=_csv(env.get("GESTOR_WEB_ALLOWED_ORIGINS"), cls.allowed_origins),
            allowed_hosts=_csv(env.get("GESTOR_WEB_ALLOWED_HOSTS"), cls.allowed_hosts),
            public_host=str(env.get("GESTOR_WEB_PUBLIC_HOST") or "gestor-peca").strip(),
            serve_static=_as_bool(env.get("GESTOR_WEB_SERVE_STATIC"), default=True),
            stream_interval_seconds=max(
                5, min(60, int(env.get("GESTOR_WEB_STREAM_INTERVAL_SECONDS", "15")))
            ),
            database_retry_seconds=max(
                1, min(60, int(env.get("GESTOR_WEB_DATABASE_RETRY_SECONDS", "5")))
            ),
            sync_thread_pool_size=_bounded_int(
                env.get("GESTOR_WEB_THREAD_POOL_SIZE"),
                default=100,
                minimum=10,
                maximum=1000,
                name="GESTOR_WEB_THREAD_POOL_SIZE",
            ),
            auth_thread_pool_size=_bounded_int(
                env.get("GESTOR_WEB_AUTH_THREAD_POOL_SIZE"),
                default=8,
                minimum=1,
                maximum=64,
                name="GESTOR_WEB_AUTH_THREAD_POOL_SIZE",
            ),
            simulation_mode=simulation_mode,
            simulation_reference_time=simulation_reference_time,
            simulation_time_scale=simulation_time_scale,
            ai_enabled=_as_bool(env.get("GESTOR_AI_ENABLED"), default=False),
            ai_api_key=str(env.get("GROQ_API_KEY") or "").strip(),
            ai_model=ai_model,
            ai_reasoning_effort=ai_reasoning_effort,
            ai_temperature=_bounded_float(
                env.get("GESTOR_AI_TEMPERATURE"),
                default=0.2,
                minimum=0.0,
                maximum=2.0,
                name="GESTOR_AI_TEMPERATURE",
            ),
            ai_max_completion_tokens=_bounded_int(
                env.get("GESTOR_AI_MAX_COMPLETION_TOKENS"),
                default=640,
                minimum=128,
                maximum=65_536,
                name="GESTOR_AI_MAX_COMPLETION_TOKENS",
            ),
            ai_max_tool_rounds=_bounded_int(
                env.get("GESTOR_AI_MAX_TOOL_ROUNDS"),
                default=6,
                minimum=1,
                maximum=12,
                name="GESTOR_AI_MAX_TOOL_ROUNDS",
            ),
            ai_max_history_messages=_bounded_int(
                env.get("GESTOR_AI_MAX_HISTORY_MESSAGES"),
                default=20,
                minimum=1,
                maximum=50,
                name="GESTOR_AI_MAX_HISTORY_MESSAGES",
            ),
            ai_request_token_budget=_bounded_int(
                env.get("GESTOR_AI_REQUEST_TOKEN_BUDGET"),
                default=6_000,
                minimum=1_000,
                maximum=100_000,
                name="GESTOR_AI_REQUEST_TOKEN_BUDGET",
            ),
            ai_tool_result_max_chars=_bounded_int(
                env.get("GESTOR_AI_TOOL_RESULT_MAX_CHARS"),
                default=10_000,
                minimum=1_000,
                maximum=100_000,
                name="GESTOR_AI_TOOL_RESULT_MAX_CHARS",
            ),
            ai_timeout_seconds=_bounded_float(
                env.get("GESTOR_AI_TIMEOUT_SECONDS"),
                default=60.0,
                minimum=1.0,
                maximum=300.0,
                name="GESTOR_AI_TIMEOUT_SECONDS",
            ),
            report_artifact_dir=str(
                env.get("GESTOR_REPORT_ARTIFACT_DIR")
                or (Path(__file__).resolve().parents[2] / "dados" / "relatorios_gerados")
            ).strip(),
            quality_drawing_dir=str(
                env.get("GESTOR_QUALITY_DRAWING_DIR")
                or (Path(__file__).resolve().parents[2] / "dados" / "desenhos_produto")
            ).strip(),
            operator_drawing_roots=str(
                env.get("GESTOR_OPERATOR_DRAWING_ROOTS") or ""
            ).strip(),
            report_expiration_hours=_bounded_int(
                env.get("GESTOR_REPORT_EXPIRATION_HOURS"),
                default=168,
                minimum=1,
                maximum=8_760,
                name="GESTOR_REPORT_EXPIRATION_HOURS",
            ),
            report_max_bytes=_bounded_int(
                env.get("GESTOR_REPORT_MAX_BYTES"),
                default=50 * 1024 * 1024,
                minimum=1024,
                maximum=500 * 1024 * 1024,
                name="GESTOR_REPORT_MAX_BYTES",
            ),
            report_automation_enabled=_as_bool(
                env.get("GESTOR_REPORT_AUTOMATION_ENABLED"), default=False
            ),
            report_scheduler_interval_seconds=_bounded_int(
                env.get("GESTOR_REPORT_SCHEDULER_INTERVAL_SECONDS"),
                default=60,
                minimum=10,
                maximum=3600,
                name="GESTOR_REPORT_SCHEDULER_INTERVAL_SECONDS",
            ),
            telegram_enabled=_as_bool(env.get("TELEGRAM_ENABLED"), default=False),
            telegram_bot_token=str(env.get("TELEGRAM_BOT_TOKEN") or "").strip(),
            telegram_timeout_seconds=_bounded_float(
                env.get("GESTOR_TELEGRAM_TIMEOUT_SECONDS"),
                default=30.0,
                minimum=1.0,
                maximum=120.0,
                name="GESTOR_TELEGRAM_TIMEOUT_SECONDS",
            ),
            totvs_enabled=totvs_enabled,
            totvs_soap_enabled=totvs_soap_enabled,
            totvs_soap_success_result=totvs_soap_success_result,
            totvs_max_xml_bytes=_bounded_int(
                env.get("GESTOR_TOTVS_MAX_XML_BYTES"),
                default=1_048_576,
                minimum=1_024,
                maximum=10 * 1024 * 1024,
                name="GESTOR_TOTVS_MAX_XML_BYTES",
            ),
            totvs_resource_map=_json_string_map(
                env.get("GESTOR_TOTVS_RESOURCE_MAP_JSON"),
                name="GESTOR_TOTVS_RESOURCE_MAP_JSON",
            ),
            totvs_sector_map=_json_string_map(
                env.get("GESTOR_TOTVS_SECTOR_MAP_JSON"),
                name="GESTOR_TOTVS_SECTOR_MAP_JSON",
            ),
            totvs_identity_source_application=_text_option(
                env.get("GESTOR_TOTVS_IDENTITY_SOURCE_APPLICATION"),
                default=DEFAULT_GESTOR_IDENTITY.source_application,
            ),
            totvs_identity_product_name=_text_option(
                env.get("GESTOR_TOTVS_IDENTITY_PRODUCT_NAME"),
                default=DEFAULT_GESTOR_IDENTITY.product_name,
            ),
            totvs_identity_product_version=_text_option(
                env.get("GESTOR_TOTVS_IDENTITY_PRODUCT_VERSION"),
                default=DEFAULT_GESTOR_IDENTITY.product_version,
            ),
            totvs_identity_context_name=_text_option(
                env.get("GESTOR_TOTVS_IDENTITY_CONTEXT_NAME"),
                default=DEFAULT_GESTOR_IDENTITY.context_name,
            ),
            totvs_outbox_worker_enabled=_as_bool(
                env.get("GESTOR_TOTVS_OUTBOX_WORKER_ENABLED"), default=False
            ),
            totvs_outbox_worker_interval_seconds=_bounded_int(
                env.get("GESTOR_TOTVS_OUTBOX_WORKER_INTERVAL_SECONDS"),
                default=15,
                minimum=1,
                maximum=3600,
                name="GESTOR_TOTVS_OUTBOX_WORKER_INTERVAL_SECONDS",
            ),
            totvs_outbox_batch_size=_bounded_int(
                env.get("GESTOR_TOTVS_OUTBOX_BATCH_SIZE"),
                default=10,
                minimum=1,
                maximum=200,
                name="GESTOR_TOTVS_OUTBOX_BATCH_SIZE",
            ),
            totvs_outbox_lease_seconds=_bounded_int(
                env.get("GESTOR_TOTVS_OUTBOX_LEASE_SECONDS"),
                default=120,
                minimum=10,
                maximum=3600,
                name="GESTOR_TOTVS_OUTBOX_LEASE_SECONDS",
            ),
            totvs_outbox_max_attempts=_bounded_int(
                env.get("GESTOR_TOTVS_OUTBOX_MAX_ATTEMPTS"),
                default=12,
                minimum=1,
                maximum=100,
                name="GESTOR_TOTVS_OUTBOX_MAX_ATTEMPTS",
            ),
            totvs_op_pull_enabled=bool(
                str(env.get("GESTOR_TOTVS_OP_PULL_ENDPOINT") or "").strip()
            ),
            totvs_op_pull_timeout_seconds=_bounded_int(
                env.get("GESTOR_TOTVS_OP_PULL_WAIT_SECONDS"),
                default=25,
                minimum=1,
                maximum=180,
                name="GESTOR_TOTVS_OP_PULL_WAIT_SECONDS",
            ),
            totvs_op_pull_poll_interval_ms=_bounded_int(
                env.get("GESTOR_TOTVS_OP_PULL_POLL_INTERVAL_MS"),
                default=500,
                minimum=50,
                maximum=10_000,
                name="GESTOR_TOTVS_OP_PULL_POLL_INTERVAL_MS",
            ),
            totvs_op_pull_negative_ttl_seconds=_bounded_int(
                env.get("GESTOR_TOTVS_OP_PULL_NEGATIVE_TTL_SECONDS"),
                default=60,
                minimum=0,
                maximum=3600,
                name="GESTOR_TOTVS_OP_PULL_NEGATIVE_TTL_SECONDS",
            ),
            totvs_op_pull_company_id=_text_option(
                env.get("GESTOR_TOTVS_OP_PULL_COMPANY_ID"), default=""
            ),
            totvs_op_pull_branch_id=_text_option(
                env.get("GESTOR_TOTVS_OP_PULL_BRANCH_ID"), default=""
            ),
            totvs_outbox_telegram_chat_id=_text_option(
                env.get("GESTOR_TOTVS_OUTBOX_TELEGRAM_CHAT_ID"), default=""
            ),
            chamada_telegram_chat_id=_text_option(
                env.get("GESTOR_CHAMADA_TELEGRAM_CHAT_ID"), default=""
            ),
            telegram_bot_polling_enabled=_as_bool(
                env.get("GESTOR_TELEGRAM_BOT_POLLING_ENABLED"), default=False
            ),
            telegram_bot_poll_interval_seconds=_bounded_int(
                env.get("GESTOR_TELEGRAM_BOT_POLL_INTERVAL_SECONDS"),
                default=3,
                minimum=1,
                maximum=60,
                name="GESTOR_TELEGRAM_BOT_POLL_INTERVAL_SECONDS",
            ),
            telegram_factory_chat_id=_text_option(
                env.get("GESTOR_TELEGRAM_FACTORY_CHAT_ID"), default=""
            ),
            telegram_sector_chat_ids=_json_string_map(
                env.get("GESTOR_TELEGRAM_SECTOR_CHAT_IDS"),
                name="GESTOR_TELEGRAM_SECTOR_CHAT_IDS",
            ),
            telegram_digest_enabled=_as_bool(
                env.get("GESTOR_TELEGRAM_DIGEST_ENABLED"), default=False
            ),
            telegram_digest_daily_time=_text_option(
                env.get("GESTOR_TELEGRAM_DIGEST_DAILY_TIME"), default="18:00"
            ),
            telegram_digest_timezone=_text_option(
                env.get("GESTOR_TELEGRAM_DIGEST_TIMEZONE"), default="America/Sao_Paulo"
            ),
            sigmanest_sync_enabled=_as_bool(
                env.get("GESTOR_SIGMANEST_SYNC_ENABLED"), default=sigmanest_configured
            ),
            sigmanest_sync_interval_seconds=_bounded_int(
                env.get("GESTOR_SIGMANEST_SYNC_INTERVAL_SECONDS"),
                default=120,
                minimum=15,
                maximum=3_600,
                name="GESTOR_SIGMANEST_SYNC_INTERVAL_SECONDS",
            ),
            sigmanest_sync_overlap_days=_bounded_int(
                env.get("GESTOR_SIGMANEST_SYNC_OVERLAP_DAYS"),
                default=7,
                minimum=0,
                maximum=90,
                name="GESTOR_SIGMANEST_SYNC_OVERLAP_DAYS",
            ),
            dev_observatory_enabled=_as_bool(
                env.get("GESTOR_DEV_OBSERVATORY_ENABLED"), default=True
            ),
            dev_observatory_report_dir=_text_option(
                env.get("GESTOR_DEV_OBSERVATORY_REPORT_DIR"),
                default=cls.dev_observatory_report_dir,
            ),
            dev_observatory_interval_seconds=_bounded_int(
                env.get("GESTOR_DEV_OBSERVATORY_INTERVAL_SECONDS"),
                default=60,
                minimum=15,
                maximum=900,
                name="GESTOR_DEV_OBSERVATORY_INTERVAL_SECONDS",
            ),
            dev_observatory_latency_warning_ms=_bounded_float(
                env.get("GESTOR_DEV_OBSERVATORY_LATENCY_WARNING_MS"),
                default=1_000.0,
                minimum=1.0,
                maximum=600_000.0,
                name="GESTOR_DEV_OBSERVATORY_LATENCY_WARNING_MS",
            ),
            dev_observatory_latency_error_ms=_bounded_float(
                env.get("GESTOR_DEV_OBSERVATORY_LATENCY_ERROR_MS"),
                default=3_000.0,
                minimum=1.0,
                maximum=600_000.0,
                name="GESTOR_DEV_OBSERVATORY_LATENCY_ERROR_MS",
            ),
            # A observação do REAL é explícita: o padrão cai para ``DATABASE_URL``
            # apenas porque ela já é o alvo REAL declarado no ambiente, e a
            # conexão é aberta em sessão somente leitura verificada contra o
            # servidor (ver backend/observability/readonly_db.py).
            dev_observatory_real_dsn=_text_option(
                env.get("GESTOR_DEVOBS_REAL_DATABASE_URL") or env.get("DATABASE_URL"),
                default="",
            ),
            dev_observatory_login_username=_text_option(
                env.get("GESTOR_DEVOBS_LOGIN_USERNAME"), default=""
            ),
            dev_observatory_login_password=_text_option(
                env.get("GESTOR_DEVOBS_LOGIN_PASSWORD"), default=""
            ),
            dev_observatory_session_secret=dev_observatory_secret,
        )
