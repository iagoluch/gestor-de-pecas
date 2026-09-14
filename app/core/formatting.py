"""Shared formatting helpers for date/time strings."""

from datetime import datetime

from app.core.constants import FMT_DATA, FMT_DB

KNOWN_DATETIME_FORMATS = (
    FMT_DB,
    "%Y-%m-%d %H:%M",
    FMT_DATA,
    "%d/%m/%Y %H:%M:%S",
)


def parse_datetime_text(valor):
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    texto = str(valor).strip()
    for fmt in KNOWN_DATETIME_FORMATS:
        try:
            return datetime.strptime(texto, fmt)
        except ValueError:
            continue
    return None


def format_datetime_text(valor, output_format=FMT_DATA):
    if not valor:
        return ""
    dt = parse_datetime_text(valor)
    if not dt:
        return str(valor)
    return dt.strftime(output_format)
