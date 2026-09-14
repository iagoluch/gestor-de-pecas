"""Resolução conservadora e explícita de setor/recurso TOTVS para o Gestor."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.core.operator_sectors import OPERATOR_SECTORS
from app.core.resource_mapping import (
    OFFICIAL_RESOURCE_ALIASES as _CORE_RESOURCE_ALIASES,
    OFFICIAL_RESOURCE_SECTORS,
    RESOURCE_FRIENDLY_NAMES,
    SECTOR_OWNED_RESOURCE_SECTORS,
    normalize_resource_code,
)
from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.models import TotvsActivityOrder


SUPPORTED_SECTORS = {
    sector.route.casefold(): sector.route
    for sector in OPERATOR_SECTORS
}

# Identidades canônicas de recurso vivem em ``app.core.resource_mapping`` desde
# a Etapa 4C. Antes o alias LASER→LASER1 existia só aqui, e a Tela do Operador
# não o enxergava: a mesma OP era aceita na ingestão e recusada no posto. O
# adaptador apenas normaliza a chave para o formato que já usava.
OFFICIAL_RESOURCE_ALIASES = {
    str(source).strip().casefold(): str(target).strip()
    for source, target in _CORE_RESOURCE_ALIASES.items()
}

# A associação oficial de recurso a setor e a lista de setores donos dos
# próprios recursos são regras canônicas da Manufatura e vivem em
# ``app.core.resource_mapping``. O adaptador TOTVS apenas as consome, para que
# ingestão e fluxo do operador nunca divirjam. O nome antigo permanece como
# alias de compatibilidade.
RESOURCE_OWNED_POINTABLE_SECTORS = SECTOR_OWNED_RESOURCE_SECTORS


def _normalized_aliases(values: Mapping[str, str] | None) -> dict[str, str]:
    return {
        str(source).strip().casefold(): str(target).strip()
        for source, target in dict(values or {}).items()
        if str(source).strip() and str(target).strip()
    }


def _resource_sector_items(
    values: Mapping[str, str] | Iterable[tuple[str, str]] | None,
):
    if isinstance(values, Mapping):
        return values.items()
    return values or ()


class TotvsResourceResolver:
    """Aplica apenas igualdade exata ou aliases declarados por configuração."""

    def __init__(
        self,
        *,
        resource_aliases: Mapping[str, str] | None = None,
        sector_aliases: Mapping[str, str] | None = None,
        known_resource_codes: tuple[str, ...] | set[str] = (),
        known_resource_sectors: (
            Mapping[str, str] | Iterable[tuple[str, str]] | None
        ) = None,
    ):
        configured_resource_aliases = _normalized_aliases(resource_aliases)
        conflicting_official_aliases = {
            source
            for source, target in OFFICIAL_RESOURCE_ALIASES.items()
            if source in configured_resource_aliases
            and normalize_resource_code(configured_resource_aliases[source])
            != normalize_resource_code(target)
        }
        if conflicting_official_aliases:
            raise TotvsContractError(
                "GESTOR_TOTVS_RESOURCE_MAP_JSON conflita com alias oficial: "
                + ", ".join(sorted(conflicting_official_aliases))
            )
        self.resource_aliases = {
            **configured_resource_aliases,
            **OFFICIAL_RESOURCE_ALIASES,
        }
        self.sector_aliases = _normalized_aliases(sector_aliases)
        invalid_sectors = {
            target
            for target in self.sector_aliases.values()
            if target.casefold() not in SUPPORTED_SECTORS
        }
        if invalid_sectors:
            raise TotvsContractError(
                "GESTOR_TOTVS_SECTOR_MAP_JSON contém setor não suportado: "
                + ", ".join(sorted(invalid_sectors))
            )
        self.known_resource_codes = {
            normalize_resource_code(value)
            for value in (*RESOURCE_FRIENDLY_NAMES.keys(), *known_resource_codes)
            if normalize_resource_code(value)
        }
        self.known_resource_sectors: dict[str, str] = dict(
            OFFICIAL_RESOURCE_SECTORS
        )
        self.known_resource_codes.update(self.known_resource_sectors)
        for resource_code, sector_name in _resource_sector_items(
            known_resource_sectors
        ):
            normalized_code = normalize_resource_code(resource_code)
            canonical_sector = SUPPORTED_SECTORS.get(
                str(sector_name or "").strip().casefold()
            )
            if not normalized_code or not canonical_sector:
                continue
            existing = self.known_resource_sectors.get(normalized_code)
            if existing and existing.casefold() != canonical_sector.casefold():
                raise TotvsContractError(
                    "Recurso canônico associado a setores divergentes: "
                    f"{normalized_code}."
                )
            self.known_resource_sectors[normalized_code] = canonical_sector
            self.known_resource_codes.add(normalized_code)

    @staticmethod
    def _resource_candidates(activity: TotvsActivityOrder) -> tuple[str, ...]:
        """MachineCode prevalece; WorkCenterCode só supre máquina ausente."""

        machine = str(activity.machine_code or "").strip()
        if machine:
            return (machine,)
        work_center = str(activity.work_center_code or "").strip()
        return (work_center,) if work_center else ()

    def _canonical_resource_sector(
        self, activity: TotvsActivityOrder
    ) -> str | None:
        for candidate in self._resource_candidates(activity):
            normalized = normalize_resource_code(candidate)
            sector = self.known_resource_sectors.get(normalized)
            if (
                sector
                and sector.casefold() in RESOURCE_OWNED_POINTABLE_SECTORS
            ):
                return sector
        return None

    def resolve_sector(self, activity: TotvsActivityOrder) -> str | None:
        candidates = (
            activity.activity_description,
            activity.work_center_code,
            activity.work_center_description,
        )
        for candidate in candidates:
            key = str(candidate or "").strip().casefold()
            if key and key in self.sector_aliases:
                return SUPPORTED_SECTORS[self.sector_aliases[key].casefold()]

        # Sem alias, somente a descrição da própria atividade pode declarar um
        # setor canônico. WorkCenterDescription=PINTURA não transforma
        # PREPARACAO/JATEAMENTO em etapas executáveis por inferência.
        exact_activity = str(activity.activity_description or "").strip().casefold()
        exact_sector = SUPPORTED_SECTORS.get(exact_activity)
        if exact_sector:
            return exact_sector

        # Pintura e Solda possuem regra funcional aprovada por pertencimento
        # cadastral. O nome/descrição do recurso não participa da decisão.
        return self._canonical_resource_sector(activity)

    def resolve_resource(
        self,
        activity: TotvsActivityOrder,
        *,
        sector: str | None = None,
    ) -> str | None:
        for candidate in self._resource_candidates(activity):
            raw = str(candidate or "").strip()
            if not raw:
                continue
            alias = self.resource_aliases.get(raw.casefold())
            if alias:
                normalized_alias = normalize_resource_code(alias)
                catalog_sector = self.known_resource_sectors.get(normalized_alias)
                # O alias é a decisão explícita; o catálogo apenas comprova
                # que o código de destino existe. Existência isolada nunca
                # transforma um recurso em operação apontável.
                if (
                    normalized_alias in self.known_resource_codes
                    and (
                        not sector
                        or not catalog_sector
                        or catalog_sector.casefold() == sector.casefold()
                    )
                ):
                    return normalized_alias
                continue
            normalized = normalize_resource_code(raw)
            catalog_sector = self.known_resource_sectors.get(normalized)
            if (
                sector
                and catalog_sector
                and catalog_sector.casefold() != sector.casefold()
            ):
                continue
            # Projeção direta é restrita à matriz canônica já consolidada no
            # Gestor ou à regra cadastral aprovada de Pintura/Solda. Códigos
            # de outros setores presentes apenas no catálogo continuam
            # auditáveis, mas exigem decisão/alias aprovado antes do uso.
            if normalized in RESOURCE_FRIENDLY_NAMES:
                return normalized
            if (
                catalog_sector
                and catalog_sector.casefold() in RESOURCE_OWNED_POINTABLE_SECTORS
                and (
                    not sector
                    or catalog_sector.casefold() == sector.casefold()
                )
            ):
                return normalized
        return None
