"""Rótulos humanos compartilhados por Andon, digest e mensagens do Telegram.

Fonte única para três traduções que antes viviam duplicadas ou nem existiam no
backend: o nível de acesso de uma conta (a UI faz o mesmo em
``web/src/utils/systemState.ts``), o prefixo de código do motivo de parada
(``"12 - Falta de material"``) e o rótulo do conflito de classificação.
"""

from __future__ import annotations

import re

from app.core.operator_sectors import operator_sector_for_level


#: Motivo sintético que a análise de paradas usa quando dois estados
#: simultâneos têm motivos diferentes. Não é uma causa de parada.
CLASSIFICATION_CONFLICT_REASON = "Conflito de classificação"

ROLE_LABELS = {
    "admin": "Administrador",
    "lider": "Líder",
    "supervisor": "Supervisor",
    "manufatura": "Manufatura",
    "gestor": "Gestor",
    "diretoria": "Diretoria",
    "andon": "Painel Andon",
    "almoxarifado": "Almoxarifado",
    "comum": "Operador de Destaque",
}

# "12 - Falta de material": código do status do recurso + hífen + motivo.
_STATUS_CODE_PREFIX = re.compile(r"^\s*\d{1,4}\s+-\s+")


def role_label(role) -> str | None:
    """Nome humano do nível de acesso da conta; ``None`` quando não há tradução.

    Quem monta texto para pessoas omite o papel em vez de mostrar o
    identificador técnico (``operador_solda_estacao_3``).
    """

    key = str(role or "").strip().casefold()
    if not key:
        return None
    if key in ROLE_LABELS:
        return ROLE_LABELS[key]
    profile = operator_sector_for_level(key)
    if profile is not None:
        if profile.name.startswith("Solda") and len(profile.resources) == 1:
            return f"Operador {profile.name} — {profile.resources[0]}"
        return f"Operador de {profile.name}"
    legacy = re.fullmatch(r"operador_solda_estacao_(\d+)", key)
    if legacy:
        return f"Operador Solda — Estação {legacy.group(1)}"
    return None


def strip_status_code_prefix(label, status_code=None) -> str:
    """Remove o prefixo de código do status do recurso do rótulo de parada.

    Com ``status_code`` conhecido remove exatamente ``"<código> - "``; sem ele,
    remove um código numérico no início. Rótulo sem prefixo volta intacto.
    """

    text = str(label or "").strip()
    code = str(status_code or "").strip()
    if code:
        prefix = f"{code} - "
        if text.casefold().startswith(prefix.casefold()):
            return text[len(prefix):].strip()
        return text
    stripped = _STATUS_CODE_PREFIX.sub("", text, count=1).strip()
    return stripped or text


__all__ = [
    "CLASSIFICATION_CONFLICT_REASON",
    "ROLE_LABELS",
    "role_label",
    "strip_status_code_prefix",
]
