"""Contratos de persistência para desacoplar domínio da implementação PostgreSQL."""

from .analytics import AnalyticsRepository, KpiTargetRepository

__all__ = ["AnalyticsRepository", "KpiTargetRepository"]
