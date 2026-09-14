"""Motor de relatórios que documenta somente dados dos serviços canônicos."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Callable
import uuid

from mes.contracts.reports import ReportError, ReportRequest


LOGGER = logging.getLogger(__name__)
SAFE_FILENAME = re.compile(r"[^a-z0-9_.-]+")


class ReportDataBuilder:
    """Compõe seções sem consultar tabelas ou recalcular indicadores."""

    def __init__(self, facade):
        self.facade = facade

    def build(self, request: ReportRequest) -> dict[str, Any]:
        filters = request.analytics_filter()
        kind = request.report_type
        overview = self.facade.inicio(filters)
        sections: dict[str, Any] = {"Resumo Executivo": overview}

        requested = {
            "completo": {
                "OEE", "Produção", "OPs", "Paradas", "Setup", "Qualidade",
                "Recursos", "Setores", "Nestings", "Exceções", "Auditoria",
            },
            "gerencial": {"Setores", "Exceções"},
            "producao": {"Produção", "Setores"},
            "ops": {"OPs"},
            "paradas": {"Paradas"},
            "setup": {"Setup"},
            "qualidade": {"Qualidade"},
            "indicadores": {"OEE"},
            "recursos": {"Recursos"},
            "setores": {"Setores"},
            "nestings": {"Nestings"},
            "excecoes": {"Exceções"},
            "rastreabilidade": {"Rastreabilidade"},
            "auditoria": {"Auditoria"},
        }[kind]

        loaders = {
            "OEE": lambda: self.facade.analise("oee", filters),
            "Produção": lambda: self.facade.producao_realizada(filters),
            "OPs": lambda: self.facade.ordens_producao(filters),
            "Paradas": lambda: self.facade.analise("paradas", filters),
            "Setup": lambda: self.facade.analise("setup", filters),
            "Qualidade": lambda: self.facade.analise("qualidade", filters),
            "Recursos": lambda: self.facade.consulta_operacional(filters),
            "Setores": lambda: {"items": overview.get("sectors") or []},
            "Nestings": lambda: self.facade.nestings(filters),
            "Exceções": lambda: self.facade.insights(filters),
            "Rastreabilidade": lambda: self.facade.rastreabilidade(str(request.op)),
            "Auditoria": lambda: self.facade.auditoria(filters),
        }
        for name in (
            "OEE", "Produção", "OPs", "Paradas", "Setup", "Qualidade",
            "Recursos", "Setores", "Nestings", "Exceções", "Rastreabilidade", "Auditoria",
        ):
            if name in requested:
                sections[name] = loaders[name]()

        return {
            "type": kind,
            "periodo": filters.to_dict(),
            "filtros": request.filters_dict(),
            "sections": sections,
            "analysis": (
                "Análise automática indisponível nesta geração"
                if request.include_executive_analysis else None
            ),
            "policies": {
                "calculation": "backend_only",
                "kpi_recalculated_in_workbook": False,
                "source": "FrontendBackendFacade",
            },
        }


def _count_rows(value: Any) -> int:
    if isinstance(value, list):
        return len(value) + sum(_count_rows(item) for item in value)
    if isinstance(value, dict):
        return sum(_count_rows(item) for item in value.values())
    return 0


class IndustrialReportService:
    """Gera, registra e recupera artifacts XLSX independentes da IA."""

    def __init__(
        self,
        facade,
        repository,
        *,
        artifact_dir: str | Path,
        workbook_builder: Callable[[str, Any, Any], bytes],
        now_func=None,
        expiration_hours: int = 168,
        max_bytes: int = 50 * 1024 * 1024,
        messaging_available: bool = False,
        wait_seconds: float = 120.0,
        wait_interval_seconds: float = 0.25,
    ):
        self.repository = repository
        self.data_builder = ReportDataBuilder(facade)
        self.workbook_builder = workbook_builder
        self._now = now_func or datetime.now
        self.expiration_hours = max(1, int(expiration_hours))
        self.max_bytes = max(1024, int(max_bytes))
        self.messaging_available = bool(messaging_available)
        self.artifact_dir = Path(artifact_dir).expanduser().resolve()
        # Espera máxima de quem perdeu a corrida pela mesma chave.
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.wait_interval_seconds = max(0.01, float(wait_interval_seconds))

    def generate(
        self,
        request: ReportRequest,
        *,
        created_by: int,
        source: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Gera o artifact garantindo um único arquivo por solicitação equivalente.

        Quando há chave de idempotência, a reserva no banco decide quem gera. A
        constraint ``uq_generated_reports_idempotency`` resolve a corrida, de
        modo que dois pedidos simultâneos idênticos convergem para o mesmo
        artifact em vez de produzirem dois arquivos.
        """

        key = str(idempotency_key).strip() if idempotency_key else None
        if key:
            pronto = self._artifact_pronto(created_by, key)
            if pronto is not None:
                return self.view(pronto, user_id=created_by)

        started = time.monotonic()
        now = self._now().replace(microsecond=0)
        report_id = str(uuid.uuid4())
        safe_type = SAFE_FILENAME.sub("_", request.report_type.casefold()).strip("._") or "relatorio"
        filename = f"gestor_{safe_type}_{request.inicio:%Y-%m-%d}_{report_id[:8]}.xlsx"
        directory = (self.artifact_dir / now.strftime("%Y/%m/%d")).resolve()
        if self.artifact_dir not in directory.parents:
            raise ReportError("report_storage_invalid", "O diretório de relatórios é inválido.", status_code=500)
        directory.mkdir(parents=True, exist_ok=True)
        final_path = (directory / filename).resolve()
        if directory not in final_path.parents:
            raise ReportError("report_storage_invalid", "O arquivo de relatório é inválido.", status_code=500)
        expires_at = now + timedelta(hours=self.expiration_hours)
        metadata = {
            "analysis_requested": request.include_executive_analysis,
            "analysis_available": False,
            "calculation_policy": "backend_only",
        }

        reserva = None
        if key:
            reserva = self.repository.reservar_relatorio_gerado(
                report_id=report_id,
                created_by=int(created_by),
                report_type=request.report_type,
                period_start=request.inicio,
                period_end=request.fim,
                filters=request.filters_dict(),
                filename=filename,
                storage_path=str(final_path),
                source=str(source),
                created_at=now,
                expires_at=expires_at,
                idempotency_key=key,
                generation_metadata=metadata,
            )
            if reserva is None:
                # Outra sessão está gerando esta mesma solicitação.
                return self.view(self._aguardar_artifact(created_by, key), user_id=created_by)

        try:
            payload = self.data_builder.build(request)
            content = self.workbook_builder(request.report_type, payload, request.analytics_filter())
            if not isinstance(content, (bytes, bytearray)) or not content:
                raise ReportError("report_generation_failed", "Não foi possível gerar o relatório.", status_code=500)
            if len(content) > self.max_bytes:
                raise ReportError("report_too_large", "O relatório excedeu o limite de tamanho.", status_code=413)

            temp_path = final_path.with_suffix(".tmp")
            try:
                temp_path.write_bytes(content)
                os.replace(temp_path, final_path)
                elapsed_ms = round((time.monotonic() - started) * 1000)
                medidas = {
                    "size_bytes": len(content),
                    "worksheet_count": len(payload.get("sections") or {}),
                    "row_count": _count_rows(payload.get("sections")),
                    "generation_ms": elapsed_ms,
                    "generation_metadata": metadata,
                }
                if reserva is not None:
                    record = self.repository.concluir_relatorio_gerado(report_id, **medidas)
                else:
                    record = self.repository.registrar_relatorio_gerado(
                        report_id=report_id,
                        created_by=int(created_by),
                        report_type=request.report_type,
                        period_start=request.inicio,
                        period_end=request.fim,
                        filters=request.filters_dict(),
                        filename=filename,
                        storage_path=str(final_path),
                        status="pronto",
                        source=str(source),
                        created_at=now,
                        expires_at=expires_at,
                        idempotency_key=key,
                        **medidas,
                    )
            except Exception:
                temp_path.unlink(missing_ok=True)
                final_path.unlink(missing_ok=True)
                raise
        except Exception:
            # A reserva vira 'falhou' e a chave fica livre para nova tentativa.
            if reserva is not None:
                self.repository.falhar_relatorio_gerado(report_id)
            raise

        LOGGER.info(
            "Industrial report generated report_id=%s user_id=%s type=%s source=%s size_bytes=%s rows=%s sheets=%s elapsed_ms=%s",
            report_id, created_by, request.report_type, source, len(content),
            record.get("row_count"), record.get("worksheet_count"), record.get("generation_ms"),
        )
        return self.view(record, user_id=created_by)

    def _artifact_pronto(self, created_by: int, key: str) -> dict[str, Any] | None:
        """Artifact reutilizável: pronto e ainda dentro da validade."""

        existing = self.repository.obter_relatorio_por_idempotencia(int(created_by), key)
        if not existing or existing.get("status") != "pronto":
            return None
        expires_at = existing.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= self._now():
            return None
        return existing

    def _aguardar_artifact(self, created_by: int, key: str) -> dict[str, Any]:
        """Aguarda a sessão vencedora concluir a geração desta mesma chave."""

        deadline = time.monotonic() + self.wait_seconds
        while True:
            pronto = self._artifact_pronto(created_by, key)
            if pronto is not None:
                return pronto
            atual = self.repository.obter_relatorio_por_idempotencia(int(created_by), key)
            if atual is not None and atual.get("status") == "falhou":
                raise ReportError(
                    "report_generation_failed",
                    "Não foi possível gerar o relatório.",
                    status_code=500,
                )
            if time.monotonic() >= deadline:
                raise ReportError(
                    "report_generation_in_progress",
                    "Este relatório já está sendo gerado. Aguarde a conclusão.",
                    status_code=409,
                )
            time.sleep(self.wait_interval_seconds)

    def view(self, record: dict[str, Any], *, user_id: int) -> dict[str, Any]:
        if int(record.get("created_by") or 0) != int(user_id):
            raise ReportError("report_not_found", "Relatório não encontrado.", status_code=404)
        result = {
            "id": str(record["id"]),
            "name": record["filename"],
            "type": record["report_type"],
            "period_start": record["period_start"],
            "period_end": record["period_end"],
            "filters": dict(record.get("filters") or {}),
            "status": record["status"],
            "size_bytes": int(record.get("size_bytes") or 0),
            "worksheet_count": int(record.get("worksheet_count") or 0),
            "row_count": int(record.get("row_count") or 0),
            "created_at": record["created_at"],
            "expires_at": record.get("expires_at"),
            "source": record.get("source"),
            "download_url": f"/api/v1/reports/artifacts/{record['id']}/download",
        }
        if self.messaging_available:
            destinations = self.repository.listar_destinos_mensagem(
                int(user_id), provider="telegram"
            )
            if destinations:
                result["telegram_available"] = True
                result["telegram_destination_id"] = int(destinations[0]["id"])
        return result

    def get(self, report_id: str, *, user_id: int) -> tuple[dict[str, Any], Path]:
        record = self.repository.obter_relatorio_gerado(str(report_id), int(user_id))
        if not record or record.get("status") != "pronto":
            raise ReportError("report_not_found", "Relatório não encontrado.", status_code=404)
        expires_at = record.get("expires_at")
        if isinstance(expires_at, datetime) and expires_at <= self._now():
            raise ReportError("report_expired", "Este relatório expirou.", status_code=410)
        path = Path(str(record.get("storage_path") or "")).resolve()
        if self.artifact_dir not in path.parents or not path.is_file():
            raise ReportError("report_file_unavailable", "O arquivo do relatório não está disponível.", status_code=404)
        return record, path


__all__ = ["IndustrialReportService", "ReportDataBuilder"]
