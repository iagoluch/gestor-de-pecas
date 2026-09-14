"""Busca de tarefas exclusivamente nas fontes locais do PostgreSQL de teste."""

from dataclasses import dataclass, field
import logging
from typing import Optional

from app.core.normalization import limpa_codigo


@dataclass
class TaskLookupResult:
    ok: bool
    codigo: str
    source: str
    tarefa: Optional[dict] = None
    registros: list = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None


class TarefaLookupService:
    """Consulta o banco de teste sem fallback ou conexão externa."""

    def __init__(self, db, operador: Optional[str] = None):
        self.db = db
        self.operador = operador

    def buscar_local(self, codigo_tarefa):
        codigo = limpa_codigo(codigo_tarefa)
        if not codigo:
            return TaskLookupResult(False, codigo, "postgresql_test", message="Código de tarefa vazio.")

        tarefa = self.db.buscar_tarefa_por_codigo(codigo)
        if tarefa:
            return TaskLookupResult(
                True,
                codigo,
                "postgresql_test",
                tarefa=tarefa,
                message="Tarefa encontrada no banco de teste.",
            )

        materializar = getattr(self.db, "materializar_tarefa_catalogo", None)
        if callable(materializar):
            try:
                tarefa = materializar(codigo)
            except Exception as exc:
                logging.exception("Falha ao materializar tarefa do catálogo local")
                return TaskLookupResult(
                    False,
                    codigo,
                    "catalogo_local",
                    message=f"Falha ao consultar o catálogo local: {exc}",
                    error=str(exc),
                )
            if tarefa:
                return TaskLookupResult(
                    True,
                    codigo,
                    "catalogo_local",
                    tarefa=tarefa,
                    message="Tarefa encontrada no catálogo local do banco de teste.",
                )

        return TaskLookupResult(
            False,
            codigo,
            "postgresql_test",
            message=f"Tarefa {codigo} não encontrada no banco de teste.",
            error="not_found",
        )
