from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mes.contracts.reports import REPORT_PERIOD_KINDS, REPORT_TYPES


class ReportGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    report_type: str
    period_kind: str = "personalizado"
    inicio: datetime | None = None
    fim: datetime | None = None
    setor: str | None = Field(default=None, max_length=120)
    recurso: str | None = Field(default=None, max_length=120)
    op: str | None = Field(default=None, max_length=120)
    indicador: str | None = Field(default=None, max_length=80)
    include_executive_analysis: bool = False

    @field_validator("report_type")
    @classmethod
    def valid_report_type(cls, value):
        normalized = value.casefold().replace("-", "_")
        if normalized not in REPORT_TYPES:
            raise ValueError("Tipo de relatório não permitido.")
        return normalized

    @field_validator("period_kind")
    @classmethod
    def valid_period_kind(cls, value):
        normalized = value.casefold()
        if normalized not in REPORT_PERIOD_KINDS:
            raise ValueError("Período de relatório não permitido.")
        return normalized


class ReportScheduleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    report_type: str
    frequency: str
    run_time: time
    timezone: str = Field(min_length=1, max_length=80)
    setor: str | None = Field(default=None, max_length=120)
    recurso: str | None = Field(default=None, max_length=120)
    op: str | None = Field(default=None, max_length=120)
    destination_id: int | None = Field(default=None, ge=1)
    enabled: bool = True

    @field_validator("report_type")
    @classmethod
    def valid_report_type(cls, value):
        normalized = value.casefold().replace("-", "_")
        if normalized not in REPORT_TYPES:
            raise ValueError("Tipo de relatório não permitido.")
        return normalized

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, value):
        normalized = value.casefold()
        if normalized not in {"diario", "semanal", "mensal"}:
            raise ValueError("Frequência não permitida.")
        return normalized

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Fuso horário inválido.") from exc
        return value


class ReportSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    destination_id: int = Field(ge=1)
