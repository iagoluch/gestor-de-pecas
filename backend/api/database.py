"""Ciclo de vida e recuperação controlada do pool PostgreSQL."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from fastapi import Request

from app.database.errors import DatabaseUnavailableError


class DatabaseManager:
    def __init__(self, factory: Callable[[], object], *, retry_seconds: int = 5):
        self._factory = factory
        self._retry_seconds = retry_seconds
        self._database = None
        self._last_attempt = 0.0
        self._last_error: Exception | None = None
        self._lock = threading.Lock()

    def get(self):
        if self._database is not None:
            return self._database
        now = time.monotonic()
        with self._lock:
            if self._database is not None:
                return self._database
            if self._last_error is not None and now - self._last_attempt < self._retry_seconds:
                raise DatabaseUnavailableError(
                    "O PostgreSQL ainda está indisponível; uma nova tentativa ocorrerá em instantes."
                ) from self._last_error
            self._last_attempt = now
            try:
                self._database = self._factory()
                self._last_error = None
            except Exception as exc:
                self._last_error = exc
                logging.warning("Não foi possível inicializar o PostgreSQL para a API: %s", exc)
                raise DatabaseUnavailableError(
                    "Não foi possível inicializar a conexão com o PostgreSQL."
                ) from exc
            return self._database

    def health(self) -> dict:
        try:
            database = self.get()
            with database.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS ok")
                row = cursor.fetchone()
            schema_version = database.obter_schema_version()
            return {
                "status": "ok" if row and int(row.get("ok", 0)) == 1 else "degraded",
                "database": "available",
                "schema_version": schema_version,
            }
        except Exception as exc:
            self._last_error = exc
            return {
                "status": "unavailable",
                "database": "unavailable",
                "schema_version": None,
            }

    def close(self) -> None:
        with self._lock:
            if self._database is not None:
                self._database.close()
                self._database = None


def get_database(request: Request):
    return request.app.state.database_manager.get()

