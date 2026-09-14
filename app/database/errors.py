"""Controlled persistence errors exposed by the PostgreSQL layer."""


class DatabaseError(RuntimeError):
    """Base error for persistence failures."""


class DatabaseConfigurationError(DatabaseError):
    """Raised when PostgreSQL configuration is missing or unsafe."""


class DatabaseUnavailableError(DatabaseError):
    """Raised when the PostgreSQL service or connection pool is unavailable."""


class DatabaseMigrationError(DatabaseError):
    """Raised when the PostgreSQL schema cannot be created or upgraded."""


class DuplicateActiveAppointmentError(DatabaseError):
    """Raised when an OP already has an active appointment in the sector."""



class DatabaseIntegrityError(DatabaseError):
    """Raised when a fact cannot be persisted together with its obligations.

    Usada quando o Gestor não consegue registrar duravelmente, na mesma
    transação do fato canônico, uma obrigação que depende dele — hoje, o item
    da outbox TOTVS. Commitar o fato sem a obrigação criaria uma perda que
    nenhum worker ou reprocessamento consegue recuperar, então a transação
    inteira é revertida.
    """
