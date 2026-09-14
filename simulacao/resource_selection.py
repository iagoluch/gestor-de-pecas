"""Seleção explícita de postos com vínculo operacional comprovado.

Os postos em ``config/simulacao_industrial.json`` são candidatos de cobertura,
não uma ordem para criar apontamentos. A decisão de ativá-los acontece depois
da ingestão canônica das OPs e usa as filas que o próprio Gestor já filtrou:

* Workbench: uma linha em ``queue`` ou ``production`` já passou por
  ``station_matches_route``; logo o posto é elegível para uma operação real.
* Corte: uma tarefa na fila foi filtrada pelo recurso informado no endpoint.
* Destaque: só entra quando a fila de Corte publicada pelo backend informa que
  algum plano realmente libera o Destaque. Não se replica a regra Laser aqui.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _items(payload: Mapping[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = (payload or {}).get(key)
    return [dict(item) for item in value] if isinstance(value, list) else []


def avaliar_workbench(payload: Mapping[str, Any] | None, recurso: str) -> dict[str, Any]:
    """Retorna evidência de vínculo que o Workbench já considera apontável."""

    payload = payload or {}
    if str(payload.get("resource") or "").strip() != str(recurso or "").strip():
        return {"selecionado": False, "motivo": "resposta_recurso_divergente"}
    fila = _items(payload, "queue")
    producao = _items(payload, "production")
    total = len(fila) + len(producao)
    return {
        "selecionado": total > 0,
        "motivo": "workbench_com_operacao_elegivel" if total else "sem_operacao_elegivel",
        "fila": len(fila),
        "producao": len(producao),
    }


def avaliar_corte(payload: Mapping[str, Any] | None, recurso: str) -> dict[str, Any]:
    """Retorna vínculo da fila especializada de Corte para o recurso consultado."""

    payload = payload or {}
    if str(payload.get("resource") or "").strip() != str(recurso or "").strip():
        return {"selecionado": False, "motivo": "resposta_recurso_divergente", "libera_destaque": False}
    tarefas = _items(payload, "items")
    planos = [plano for tarefa in tarefas for plano in _items(tarefa, "planos")]
    return {
        "selecionado": bool(tarefas),
        "motivo": "fila_corte_com_vinculo" if tarefas else "sem_plano_elegivel",
        "tarefas": len(tarefas),
        # O token vem do CutService; esta camada só o consome.
        "libera_destaque": any(bool(plano.get("libera_destaque")) for plano in planos),
    }


def avaliar_destaque(*, corte_libera_destaque: bool) -> dict[str, Any]:
    """Destaque depende da liberação canônica publicada pela fila de Corte."""

    return {
        "selecionado": bool(corte_libera_destaque),
        "motivo": (
            "corte_com_plano_que_libera_destaque"
            if corte_libera_destaque
            else "nenhum_plano_de_corte_libera_destaque"
        ),
    }
