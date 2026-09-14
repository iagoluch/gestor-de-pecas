"""Normalização de valores compartilhada por domínio, serviços e persistência.

Este módulo deliberadamente não importa PostgreSQL nem integrações externas. Regras de
normalização usadas pelo backend podem, assim, ser reutilizadas pela futura API
Web sem carregar drivers de infraestrutura.
"""

from __future__ import annotations

from datetime import date, datetime, time

from app.core.constants import FMT_DB


def normalizar_data_db(valor):
    """Converte valores aceitos pelo sistema em ``datetime`` sem microssegundos."""

    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.replace(microsecond=0)
    if isinstance(valor, date):
        return datetime.combine(valor, time.min)
    texto = str(valor).strip()
    for formato in (
        FMT_DB,
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    raise ValueError(f"Data/hora inválida: {valor}")


def limpa_codigo(valor):
    """Normaliza identificadores operacionais sem conhecer a persistência."""

    return str(valor or "").strip().replace("\n", "").replace("\r", "").upper()


__all__ = ["limpa_codigo", "normalizar_data_db"]
