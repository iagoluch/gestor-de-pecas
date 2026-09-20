"""Thread-safe synchronous PostgreSQL connection pool."""

from contextlib import contextmanager
import logging
import threading

from psycopg import OperationalError
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

from app.database.errors import DatabaseUnavailableError


class _ConnectionLease:
    """Compatibility handle whose close() returns the connection to the pool."""

    def __init__(self, manager, connection):
        self._manager = manager
        self._connection = connection
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        if self._closed:
            return
        try:
            if self._connection.info.transaction_status != TransactionStatus.IDLE:
                self._connection.rollback()
        finally:
            self._manager.put_connection(self._connection)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self.close()
        return False


class PostgresPoolManager:
    def __init__(self, config, *, open_immediately=True):
        self.config = config
        self._lock = threading.Lock()
        self._closed = False
        self.pool = ConnectionPool(
            conninfo=config.dsn,
            min_size=config.min_pool_size,
            max_size=config.max_pool_size,
            timeout=config.pool_timeout,
            kwargs={"autocommit": False, "row_factory": dict_row},
            configure=self._configure_session,
            open=False,
            name="gestor-de-pecas",
        )
        if open_immediately:
            self.open()

    def _configure_session(self, connection):
        """Alinha o fuso da sessão ao fuso em que a aplicação grava.

        Os timestamps produtivos são ``TIMESTAMP WITHOUT TIME ZONE`` gravados
        por ``agora_db()`` em hora local. Sem este alinhamento, toda duração
        calculada em SQL contra ``CURRENT_TIMESTAMP`` — fila de Corte, tempos
        de nesting e janelas de analytics — fica deslocada pelo offset do
        servidor, inflando tempo produtivo de execuções ainda abertas.
        """

        timezone = str(getattr(self.config, "session_timezone", "") or "").strip()
        if timezone:
            try:
                # ``set_config`` aceita parâmetro; ``SET`` não. O ``false`` mantém o
                # ajuste por toda a sessão, não apenas pela transação corrente.
                connection.execute("SELECT set_config('TimeZone', %s, false)", (timezone,))
                connection.commit()
            except Exception:
                logging.warning(
                    "Não foi possível fixar o fuso da sessão PostgreSQL em %s", timezone
                )
                try:
                    connection.rollback()
                except Exception:  # nosec B110 -- best-effort: a falha original já foi logada acima; nada mais a fazer se o rollback também falhar
                    pass

        statement_timeout_ms = int(getattr(self.config, "statement_timeout_ms", 0) or 0)
        if statement_timeout_ms > 0:
            try:
                # Limita quanto tempo uma única query pode reter uma das poucas
                # conexões do pool. Sem isso, uma query travada por lock ou por
                # falta de índice no banco real derruba a vazão de toda a API.
                connection.execute(
                    "SELECT set_config('statement_timeout', %s, false)",
                    (str(statement_timeout_ms),),
                )
                connection.commit()
            except Exception:
                logging.warning(
                    "Não foi possível fixar statement_timeout da sessão PostgreSQL em %sms",
                    statement_timeout_ms,
                )
                try:
                    connection.rollback()
                except Exception:  # nosec B110 -- best-effort: a falha original já foi logada acima; nada mais a fazer se o rollback também falhar
                    pass

    def open(self):
        with self._lock:
            if self._closed:
                raise DatabaseUnavailableError("O pool PostgreSQL já foi encerrado.")
            try:
                self.pool.open(wait=True, timeout=self.config.pool_timeout)
            except (OperationalError, PoolTimeout, OSError) as exc:
                logging.exception("Falha ao conectar ao PostgreSQL em %s", self.config.safe_target)
                raise DatabaseUnavailableError(
                    "Não foi possível conectar ao PostgreSQL. Verifique o servidor e as credenciais."
                ) from exc

    @contextmanager
    def connection(self):
        if self._closed:
            raise DatabaseUnavailableError("O pool PostgreSQL está encerrado.")
        try:
            with self.pool.connection(timeout=self.config.pool_timeout) as connection:
                yield connection
        except PoolTimeout as exc:
            raise DatabaseUnavailableError("Tempo esgotado aguardando conexão PostgreSQL.") from exc
        except OperationalError as exc:
            logging.exception("Conexão PostgreSQL perdida")
            raise DatabaseUnavailableError("A conexão com o PostgreSQL foi perdida.") from exc

    def get_connection(self):
        if self._closed:
            raise DatabaseUnavailableError("O pool PostgreSQL está encerrado.")
        try:
            return _ConnectionLease(
                self,
                self.pool.getconn(timeout=self.config.pool_timeout),
            )
        except PoolTimeout as exc:
            raise DatabaseUnavailableError("Tempo esgotado aguardando conexão PostgreSQL.") from exc
        except OperationalError as exc:
            raise DatabaseUnavailableError("Não foi possível obter conexão PostgreSQL.") from exc

    def put_connection(self, connection):
        if self._closed:
            connection.close()
            return
        self.pool.putconn(connection)

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.pool.close()

