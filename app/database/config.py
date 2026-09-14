"""Environment-only PostgreSQL configuration."""

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.core.paths import base_dir
from app.database.errors import DatabaseConfigurationError


load_dotenv(Path(base_dir()) / ".env", override=False)


DEFAULT_SESSION_TIMEZONE = "America/Sao_Paulo"


@dataclass(frozen=True)
class PostgresConfig:
    dsn: str
    min_pool_size: int = 1
    max_pool_size: int = 10
    pool_timeout: float = 5.0
    # A aplicação grava timestamps *naive* em hora local (``agora_db()``). A
    # sessão PostgreSQL precisa usar o mesmo fuso, senão qualquer duração
    # calculada em SQL contra CURRENT_TIMESTAMP fica deslocada pelo offset.
    session_timezone: str = DEFAULT_SESSION_TIMEZONE
    # Sem isso uma query lenta/travada prende uma conexão do pool (só 1-4 por
    # padrão) indefinidamente e derruba a vazão do resto da aplicação.
    statement_timeout_ms: int = 30_000

    @property
    def safe_target(self):
        values = conninfo_to_dict(self.dsn)
        return {
            "host": values.get("host") or "local socket",
            "port": values.get("port") or "5432",
            "dbname": values.get("dbname") or "",
            "user": values.get("user") or "",
            "sslmode": values.get("sslmode") or "",
        }


def _positive_int(name, default, minimum=1, environ=None):
    env = environ if environ is not None else os.environ
    raw = env.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(f"{name} deve ser um número inteiro.") from exc
    if value < minimum:
        raise DatabaseConfigurationError(f"{name} deve ser maior ou igual a {minimum}.")
    return value


def _positive_float(name, default, environ=None):
    env = environ if environ is not None else os.environ
    raw = env.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise DatabaseConfigurationError(f"{name} deve ser numérico.") from exc
    if value <= 0:
        raise DatabaseConfigurationError(f"{name} deve ser maior que zero.")
    return value


def _dsn_from_pg_environment(environ=None):
    env = environ if environ is not None else os.environ
    values = {}
    mapping = {
        "host": "PGHOST",
        "port": "PGPORT",
        "dbname": "PGDATABASE",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
    }
    for key, env_name in mapping.items():
        value = env.get(env_name)
        if value:
            values[key] = value
    if not values.get("dbname") or not values.get("user"):
        return None
    values["connect_timeout"] = env.get("PGCONNECT_TIMEOUT", "5")
    values["application_name"] = "gestor_de_pecas"
    return make_conninfo(**values)


def load_postgres_config(*, testing=False, environ=None):
    """Load a production or explicitly isolated test DSN.

    Integration tests never fall back to DATABASE_URL. This prevents an
    accidental destructive test run against the operational database.
    """

    env = environ if environ is not None else os.environ
    variable = "TEST_DATABASE_URL" if testing else "DATABASE_URL"
    dsn = (env.get(variable) or "").strip()
    if testing:
        production_dsn = (env.get("DATABASE_URL") or "").strip()
        if not dsn:
            raise DatabaseConfigurationError("TEST_DATABASE_URL não configurada.")
        if production_dsn and conninfo_to_dict(dsn) == conninfo_to_dict(production_dsn):
            raise DatabaseConfigurationError(
                "TEST_DATABASE_URL não pode apontar para o mesmo banco de DATABASE_URL."
            )
    elif not dsn:
        dsn = _dsn_from_pg_environment(env)
    if not dsn:
        raise DatabaseConfigurationError(
            "PostgreSQL não configurado. Defina DATABASE_URL ou PGHOST/PGDATABASE/PGUSER."
        )
    parsed = conninfo_to_dict(dsn)
    expected_database = str(env.get("GESTOR_EXPECTED_DATABASE") or "").strip()
    actual_database = str(parsed.get("dbname") or "").strip()
    if testing and "test" not in actual_database.casefold():
        raise DatabaseConfigurationError(
            "Execução recusada: TEST_DATABASE_URL deve apontar para um banco cujo nome contenha 'test'."
        )
    if expected_database and actual_database.casefold() != expected_database.casefold():
        raise DatabaseConfigurationError(
            f"Execução isolada recusada: banco ativo '{actual_database or '<vazio>'}', "
            f"esperado '{expected_database}'."
        )
    connection_defaults = {}
    if not parsed.get("connect_timeout"):
        connection_defaults["connect_timeout"] = env.get("PGCONNECT_TIMEOUT", "5")
    if not parsed.get("application_name"):
        connection_defaults["application_name"] = "gestor_de_pecas"
    # Sem keepalive, uma conexão do pool que fica "meio-morta" (rede caiu,
    # NAT/firewall descartou em silêncio, notebook hibernou) nunca recebe
    # RST/FIN — o socket simplesmente não responde. A próxima requisição que
    # pegar essa conexão do pool trava lendo um socket morto, sem erro
    # nenhum, até o timeout do SO (no Windows, isso pode passar de 1h). É
    # exatamente o padrão "carrega para sempre, sem erro" já visto no 8001.
    # Com keepalive, o próprio driver detecta a conexão morta em ~60s
    # (30s ociosa + até 3 sondas de 10s) e a devolve como falha ao pool, que
    # descarta e abre outra — em vez de travar a requisição do usuário.
    if not parsed.get("keepalives"):
        connection_defaults["keepalives"] = env.get("PGKEEPALIVES", "1")
    if not parsed.get("keepalives_idle"):
        connection_defaults["keepalives_idle"] = env.get("PGKEEPALIVES_IDLE", "30")
    if not parsed.get("keepalives_interval"):
        connection_defaults["keepalives_interval"] = env.get("PGKEEPALIVES_INTERVAL", "10")
    if not parsed.get("keepalives_count"):
        connection_defaults["keepalives_count"] = env.get("PGKEEPALIVES_COUNT", "3")
    if connection_defaults:
        dsn = make_conninfo(dsn, **connection_defaults)

    session_timezone = str(
        env.get("GESTOR_DB_TIMEZONE") or DEFAULT_SESSION_TIMEZONE
    ).strip() or DEFAULT_SESSION_TIMEZONE
    min_size = _positive_int("PGPOOL_MIN_SIZE", 1, environ=env)
    max_size = _positive_int("PGPOOL_MAX_SIZE", 10, environ=env)
    if max_size < min_size:
        raise DatabaseConfigurationError("PGPOOL_MAX_SIZE deve ser maior ou igual a PGPOOL_MIN_SIZE.")
    return PostgresConfig(
        dsn=dsn,
        min_pool_size=min_size,
        max_pool_size=max_size,
        pool_timeout=_positive_float("PGPOOL_TIMEOUT", 5, environ=env),
        session_timezone=session_timezone,
        statement_timeout_ms=_positive_int("PGSTATEMENT_TIMEOUT_MS", 30_000, environ=env),
    )
