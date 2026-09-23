"""Acesso somente leitura ao banco REAL, garantido pelo próprio PostgreSQL.

A regra do projeto é dura: o Dev Observatory **nunca** escreve em
``gestor_pecas``. Cumprir isso por disciplina de código não basta — bastaria um
método errado da facade para violar a regra. Por isso a garantia é de
configuração e é verificada em tempo de abertura:

1. a conexão nasce com ``options=-c default_transaction_read_only=on``, que é
   parâmetro de sessão do servidor, não convenção do cliente;
2. logo após abrir, o pool é submetido a uma **prova de gravação**: um
   ``CREATE TEMP TABLE`` dentro de uma transação que será descartada. Em sessão
   somente leitura o PostgreSQL recusa qualquer ``CREATE``. Se a recusa não
   acontecer, o pool é fechado e o ambiente REAL fica indisponível no
   observatório — falhar fechado, nunca aberto;
3. antes da prova, o PostgreSQL confirma que o papel efetivo não tem
   privilégio de escrita/DDL em bancos, schemas, relações ou sequências, nem
   uma associação a papel elevado; e
4. ``auto_migrate=False``: nenhuma migração é aplicada ao abrir o REAL.

Recomendação operacional (opcional, e melhor ainda): aponte
``GESTOR_DEVOBS_REAL_DATABASE_URL`` para um papel dedicado sem privilégio de
escrita::

    CREATE ROLE gestor_devobs LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB;
    GRANT CONNECT ON DATABASE gestor_pecas TO gestor_devobs;
    GRANT USAGE ON SCHEMA public TO gestor_devobs;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO gestor_devobs;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT TO gestor_devobs;
    ALTER ROLE gestor_devobs SET default_transaction_read_only = on;

Sem essa separação de privilégios, o observatório falha fechado mesmo que a
sessão tenha sido aberta com ``default_transaction_read_only=on``.
"""

from __future__ import annotations

import logging
import threading
import time

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.database.config import DEFAULT_SESSION_TIMEZONE, PostgresConfig
from app.database.connection import PostgresPoolManager


READ_ONLY_OPTION = "-c default_transaction_read_only=on"
APPLICATION_NAME = "gestor_dev_observatory"


_WRITE_PRIVILEGE_SQL = """
    SELECT
        EXISTS (
            SELECT 1
            FROM pg_roles AS candidate
            WHERE (
                candidate.rolsuper
                OR candidate.rolcreaterole
                OR candidate.rolcreatedb
                OR candidate.rolreplication
                OR candidate.rolbypassrls
            )
              AND pg_has_role(current_user, candidate.oid, 'USAGE')
        ) AS elevated_role,
        has_database_privilege(current_user, current_database(), 'CREATE')
            AS database_create,
        EXISTS (
            SELECT 1
            FROM pg_namespace AS namespace
            WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
              AND namespace.nspname NOT LIKE 'pg_toast%'
              AND has_schema_privilege(current_user, namespace.oid, 'CREATE')
        ) AS schema_create,
        EXISTS (
            SELECT 1
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
              AND namespace.nspname NOT LIKE 'pg_toast%'
              AND (
                  (
                      relation.relkind = 'S'
                      AND has_sequence_privilege(current_user, relation.oid, 'USAGE, UPDATE')
                  )
                  OR (
                      relation.relkind IN ('r', 'p', 'v', 'm', 'f')
                      AND (
                          has_table_privilege(current_user, relation.oid, 'INSERT')
                          OR has_table_privilege(current_user, relation.oid, 'UPDATE')
                          OR has_table_privilege(current_user, relation.oid, 'DELETE')
                          OR has_table_privilege(current_user, relation.oid, 'TRUNCATE')
                          OR has_table_privilege(current_user, relation.oid, 'REFERENCES')
                          OR has_table_privilege(current_user, relation.oid, 'TRIGGER')
                      )
                  )
              )
        ) AS relation_write
"""


class ReadOnlyVerificationError(RuntimeError):
    """A sessão aberta não é comprovadamente somente leitura."""


def _write_privilege_evidence(cursor) -> dict[str, bool]:
    cursor.execute(_WRITE_PRIVILEGE_SQL)
    row = dict(cursor.fetchone())
    return {
        "elevated_role": bool(row.get("elevated_role")),
        "database_create": bool(row.get("database_create")),
        "schema_create": bool(row.get("schema_create")),
        "relation_write": bool(row.get("relation_write")),
    }


def _require_no_write_privileges(evidence: dict[str, bool]) -> None:
    enabled = [name for name, value in evidence.items() if value]
    if enabled:
        raise ReadOnlyVerificationError(
            "A credencial do Dev Observatory ainda possui privilégios incompatíveis "
            f"com leitura exclusiva: {', '.join(enabled)}."
        )


def read_only_config(dsn: str, *, pool_size: int = 2) -> PostgresConfig:
    """Reescreve o DSN forçando sessão somente leitura e identidade própria."""

    parsed = conninfo_to_dict(dsn)
    existing = str(parsed.get("options") or "").strip()
    options = f"{existing} {READ_ONLY_OPTION}".strip() if existing else READ_ONLY_OPTION
    hardened = make_conninfo(
        dsn,
        options=options,
        application_name=APPLICATION_NAME,
        connect_timeout=parsed.get("connect_timeout") or "5",
    )
    return PostgresConfig(
        dsn=hardened,
        min_pool_size=1,
        max_pool_size=max(1, int(pool_size)),
        pool_timeout=5.0,
        session_timezone=DEFAULT_SESSION_TIMEZONE,
    )


def verify_read_only(pool: PostgresPoolManager) -> dict:
    """Prova, contra o servidor, que a sessão recusa gravação.

    Retorna a evidência para exibição no observatório. Levanta
    ``ReadOnlyVerificationError`` quando a prova falha.
    """

    with pool.connection() as connection, connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        transaction_read_only = str(next(iter(cursor.fetchone().values())))
        cursor.execute("SHOW default_transaction_read_only")
        default_read_only = str(next(iter(cursor.fetchone().values())))
        cursor.execute("SELECT current_database() AS db, current_user AS usuario")
        identity = dict(cursor.fetchone())
        write_privileges = _write_privilege_evidence(cursor)

        write_refused_with = None
        try:
            cursor.execute("CREATE TEMP TABLE _devobs_write_probe (x integer)")
        except Exception as exc:  # a recusa é exatamente o resultado esperado
            write_refused_with = str(exc).strip().splitlines()[0]
        finally:
            connection.rollback()

    if transaction_read_only.casefold() != "on" or not write_refused_with:
        raise ReadOnlyVerificationError(
            "A conexão de observação do banco REAL não é comprovadamente somente leitura "
            f"(transaction_read_only={transaction_read_only!r}, gravação recusada={bool(write_refused_with)})."
        )
    _require_no_write_privileges(write_privileges)
    return {
        "transaction_read_only": transaction_read_only,
        "default_transaction_read_only": default_read_only,
        "database": identity.get("db"),
        "user": identity.get("usuario"),
        "write_probe": "recusada pelo PostgreSQL",
        "write_probe_error": write_refused_with,
        "write_privileges": write_privileges,
        "application_name": APPLICATION_NAME,
    }


def build_read_only_database(dsn: str):
    """``Database`` somente leitura, sem migração, apontado ao banco informado.

    Reutiliza a facade de persistência inteira — e portanto toda a leitura
    canônica já existente — sem duplicar uma única consulta. O pool explícito é
    o que permite observar um banco cujo nome não contém ``test``; a trava do
    ``Database`` existe para impedir que a *aplicação* rode fora do TESTE, não
    para impedir observação passiva.
    """

    from app.database.database import Database

    config = read_only_config(dsn)
    pool = PostgresPoolManager(config)
    try:
        evidence = verify_read_only(pool)
    except Exception:
        pool.close()
        raise
    database = Database(pool_manager=pool, auto_migrate=False)
    database.read_only_evidence = evidence
    return database


class ReadOnlyDatabaseManager:
    """Abre o banco REAL sob demanda e não insiste em loop quando ele cai."""

    def __init__(self, dsn: str | None, *, retry_seconds: int = 30):
        self.dsn = str(dsn or "").strip()
        self._retry_seconds = retry_seconds
        self._database = None
        self._lock = threading.Lock()
        self._last_attempt = 0.0
        self._last_error: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.dsn)

    @property
    def target(self) -> dict:
        if not self.dsn:
            return {}
        parsed = conninfo_to_dict(self.dsn)
        return {
            "host": parsed.get("host") or "local socket",
            "port": parsed.get("port") or "5432",
            "dbname": parsed.get("dbname") or "",
            "user": parsed.get("user") or "",
        }

    def get(self):
        if not self.dsn:
            raise RuntimeError(
                "Observação do banco REAL não configurada. Defina "
                "GESTOR_DEVOBS_REAL_DATABASE_URL (ou DATABASE_URL) para habilitá-la."
            )
        if self._database is not None:
            return self._database
        now = time.monotonic()
        with self._lock:
            if self._database is not None:
                return self._database
            if self._last_error and now - self._last_attempt < self._retry_seconds:
                raise RuntimeError(self._last_error)
            self._last_attempt = now
            try:
                self._database = build_read_only_database(self.dsn)
                self._last_error = None
            except Exception as exc:
                self._last_error = f"Banco REAL indisponível para observação: {exc}"
                logging.warning("Dev Observatory: %s", self._last_error)
                raise RuntimeError(self._last_error) from exc
            return self._database

    def status(self) -> dict:
        if not self.dsn:
            return {
                "configured": False,
                "available": False,
                "reason": (
                    "Defina GESTOR_DEVOBS_REAL_DATABASE_URL para observar o banco REAL "
                    "em modo somente leitura."
                ),
                "target": {},
                "read_only": None,
            }
        try:
            database = self.get()
        except Exception as exc:
            return {
                "configured": True,
                "available": False,
                "reason": str(exc),
                "target": self.target,
                "read_only": None,
            }
        return {
            "configured": True,
            "available": True,
            "reason": None,
            "target": self.target,
            "read_only": getattr(database, "read_only_evidence", None),
        }

    def close(self) -> None:
        with self._lock:
            if self._database is not None:
                self._database.close()
                self._database = None
