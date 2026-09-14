"""Camada oficial de persistência PostgreSQL do Gestor de Peças.

O ``Database`` é carregado sob demanda. Assim, módulos neutros como
``app.database.config`` podem ser usados sem importar o driver PostgreSQL antes
da hora, reduzindo acoplamento entre domínio/serviços e infraestrutura.
"""

from app.database.errors import (
    DatabaseConfigurationError,
    DatabaseError,
    DatabaseMigrationError,
    DatabaseUnavailableError,
    DuplicateActiveAppointmentError,
)

__all__ = [
    "Database",
    "DatabaseConfigurationError",
    "DatabaseError",
    "DatabaseMigrationError",
    "DatabaseUnavailableError",
    "DuplicateActiveAppointmentError",
]


def __getattr__(name):
    if name == "Database":
        from app.database.database import Database
        return Database
    raise AttributeError(name)
