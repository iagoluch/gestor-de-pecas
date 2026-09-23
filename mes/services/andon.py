"""Projeção consolidada e somente leitura para o Andon Geral."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

from app.core.resource_mapping import station_resource_code
from mes.domain import DataAvailability, EventCategory, ManufacturingRules


#: Leitura explícita de "fora de turno, sem HE e sem ninguém trabalhando".
#:
#: Não é um estado persistido: o evento gravado continua sendo ``fila`` ou
#: ``fora_turno``. É o nome que o Andon dá a essa combinação, decidida pelo
#: domínio (``ManufacturingRules.resource_has_no_demand``) e entregue pronta
#: pela consulta operacional. Existe para não confundir ausência de demanda com
#: parada (planejada ou não) nem com ociosidade dentro do turno. Usa a mesma
#: identidade da categoria analítica, para que Andon e relatórios nomeiem a
#: ausência de demanda exatamente igual.
NO_DEMAND_STATE = EventCategory.NO_DEMAND.value


STATE_LABELS = {
    NO_DEMAND_STATE: "Recurso sem demanda",
    EventCategory.QUEUE.value: "Fila",
    EventCategory.PRODUCTION.value: "Produção",
    EventCategory.DOWNTIME.value: "Parada",
    EventCategory.SETUP.value: "Setup",
    EventCategory.REWORK.value: "Retrabalho",
    EventCategory.ACTIVITY_WITHOUT_OP.value: "Atividade sem OP",
    EventCategory.OUT_OF_SHIFT.value: "Fora de turno",
    EventCategory.UNKNOWN.value: "Desconhecido",
}


# Organização visual oficial do Andon. O agrupamento usa exclusivamente o
# setor canônico e identidades de Corte já aprovadas; não existe classificação
# por semelhança de texto. Destaque é um posto operacional de Corte, não uma
# máquina inventada nem um quinto setor visual.
ANDON_UNCLASSIFIED_PANEL = "Não classificado"
ANDON_DEFAULT_PANEL_ORDER = ("Corte", "Caldeiraria", "Solda", "Pintura")
ANDON_PANEL_ORDER = (*ANDON_DEFAULT_PANEL_ORDER, "Montagem", ANDON_UNCLASSIFIED_PANEL)
# Wave 6F — os cinco setores que substituíram a antiga "Solda" continuam em um
# único painel "Solda" e viram sub-grupos dele, exatamente como Laser/Plasma/
# Destaque fazem dentro de Corte. O painel é a leitura de chão de fábrica
# ("a frente de solda"); o grupo é o setor real.
ANDON_WELDING_GROUP_BY_SECTOR = {
    "solda aço": "Aço",
    "solda alumínio": "Alumínio",
    "solda robô": "Robô",
    "proj. ferramentaria": "Ferramentaria",
    "protótipo": "Protótipo",
}
ANDON_PANEL_BY_SECTOR = {
    "corte": "Corte",
    "dobra": "Caldeiraria",
    "usinagem": "Caldeiraria",
    "serra": "Caldeiraria",
    "pintura": "Pintura",
    "montagem": "Montagem",
    **{sector: "Solda" for sector in ANDON_WELDING_GROUP_BY_SECTOR},
}
ANDON_GROUP_BY_SECTOR = {
    "dobra": "Dobra",
    "usinagem": "Usinagem",
    "serra": "Serra",
    "pintura": "Pintura",
    "montagem": "Montagem",
    **ANDON_WELDING_GROUP_BY_SECTOR,
}
ANDON_CUT_GROUP_BY_IDENTITY = {
    "laser": "Laser",
    "laser1": "Laser",
    "laser ensis 3015": "Laser",
    "plasma": "Plasma",
    "plasma terrablade 4": "Plasma",
}
ANDON_GROUP_ORDER = {
    "Corte": {"Laser": 0, "Plasma": 1, "Destaque": 2, "Corte": 3},
    "Caldeiraria": {"Dobra": 0, "Usinagem": 1, "Serra": 2},
    "Solda": {name: index for index, name in enumerate(ANDON_WELDING_GROUP_BY_SECTOR.values())},
    "Pintura": {"Pintura": 0},
    "Montagem": {"Montagem": 0},
    ANDON_UNCLASSIFIED_PANEL: {},
}
ACTIVE_ANDON_CATEGORIES = {
    EventCategory.PRODUCTION.value,
    EventCategory.DOWNTIME.value,
    EventCategory.SETUP.value,
    EventCategory.REWORK.value,
    EventCategory.ACTIVITY_WITHOUT_OP.value,
}


def _key(value):
    return str(value or "").strip().casefold()


def _metric_unavailable():
    return {
        "value": None,
        "availability": DataAvailability.INSUFFICIENT_DATA.value,
        "unit": "%",
        "reason": (
            "Não há dados suficientes no período para calcular este indicador "
            "no recurso."
        ),
    }


class AndonService:
    """Monta o snapshot do Andon sem depender de FastAPI ou React."""

    def __init__(self, db, *, simulation_mode=False):
        self.db = db
        self.simulation_mode = bool(simulation_mode)

    def build_snapshot(self, filters, *, operational, overview, catalogo_recursos=None):
        if catalogo_recursos is None:
            catalog_loader = getattr(self.db, "listar_recursos_pcfactory", None)
            catalog = list(catalog_loader() or []) if callable(catalog_loader) else []
        else:
            catalog = list(catalogo_recursos)

        resources = {}
        exact_code_aliases = {}
        code_aliases = {}
        name_aliases = {}
        ambiguous_aliases = set()
        for raw in catalog:
            item = dict(raw or {})
            code = str(item.get("codigo") or "").strip()
            name = str(item.get("nome") or code).strip() or code
            if not code:
                continue
            # O código cadastral é a identidade do recurso. Preserve inclusive
            # registros que diferem apenas por capitalização; nesses casos o
            # alias normalizado fica ambíguo e não recebe estado por inferência.
            resource_key = f"catalog::{code}"
            resources[resource_key] = self._catalog_resource(item, code=code, name=name)
            exact_code_aliases[code] = resource_key
            code_key = _key(code)
            name_key = _key(name)
            if code_key:
                current = code_aliases.get(code_key)
                if current is not None and current != resource_key:
                    ambiguous_aliases.add(code_key)
                    code_aliases.pop(code_key, None)
                elif code_key not in ambiguous_aliases:
                    code_aliases[code_key] = resource_key
            if name_key and name_key != code_key:
                current = name_aliases.get(name_key)
                if current is not None and current != resource_key:
                    ambiguous_aliases.add(name_key)
                    name_aliases.pop(name_key, None)
                elif name_key not in ambiguous_aliases:
                    name_aliases[name_key] = resource_key

        # Identidade vence rótulo: quando o código de um recurso coincide com o
        # nome de outro, o código manda. Sem isso os dois perdiam o alias e a
        # mesma máquina aparecia duas vezes — uma pelo catálogo e outra como
        # recurso sem cadastro.
        aliases = {**name_aliases, **code_aliases}

        active_resource_keys = set()
        for raw in operational.get("resources", []) or []:
            item = dict(raw or {})
            resource_name = str(item.get("recurso") or "").strip()
            if not resource_name:
                continue
            if not self._is_active_resource(item):
                continue
            alias = _key(resource_name)
            station_code = station_resource_code(item.get("setor"), resource_name)
            resource_key = (
                (exact_code_aliases.get(station_code) or f"posto::{station_code}")
                if station_code
                else exact_code_aliases.get(resource_name)
                or aliases.get(alias)
                or f"estado::{resource_name}"
            )
            resource = resources.get(resource_key)
            if resource is None:
                resource = self._uncatalogued_resource(item, resource_name)
                resources[resource_key] = resource
            self._apply_operational_state(resource, item)
            active_resource_keys.add(resource_key)

        cut_loader = getattr(self.db, "listar_cortes_ativos_andon", None)
        cut_rows = list(cut_loader() or []) if callable(cut_loader) else []
        for raw in cut_rows:
            cut = dict(raw or {})
            resource_name = str(cut.get("maquina") or "").strip()
            station_code = station_resource_code("Corte", resource_name)
            resource_key = (
                (exact_code_aliases.get(station_code) or f"posto::{station_code}")
                if station_code
                else exact_code_aliases.get(resource_name)
                or aliases.get(_key(resource_name))
            )
            resource_key = resource_key or f"corte::{resource_name}"
            resource = resources.get(resource_key)
            cut_state = {
                "recurso": resource_name,
                "setor": "Corte",
                "categoria": EventCategory.PRODUCTION.value,
                "inicio": cut.get("data_inicio"),
                "operador_estado": cut.get("operador_inicio"),
                "ops_ativas": [],
                "quantidade_ops_ativas": 0,
                "fonte": "apontamentos_corte",
            }
            if resource is None:
                resource = self._uncatalogued_resource(cut_state, resource_name)
                resources[resource_key] = resource
            self._apply_operational_state(resource, cut_state)
            active_resource_keys.add(resource_key)
            task = str(cut.get("codigo_tarefa") or "").strip()
            program = str(cut.get("programa") or "").strip()
            sheet = str(cut.get("nome_chapa") or "").strip()
            repeat = cut.get("repeticao")
            context = " • ".join(
                part for part in (
                    f"Tarefa {task}" if task else "",
                    f"Programa {program}" if program else "",
                    (
                        f"Chapa {sheet} · repetição {repeat}"
                        if sheet and repeat is not None
                        else f"Chapa {sheet}" if sheet
                        else f"Repetição {repeat}" if repeat is not None
                        else ""
                    ),
                )
                if part
            )
            if context:
                resource["state"]["activity_description"] = context

        # O catálogo resolve identidade/nome/setor, mas nunca cria um card. Um
        # recurso só entra no Andon se houver estado operacional atual elegível.
        resources = {
            key: value
            for key, value in resources.items()
            if key in active_resource_keys
        }

        highlight = self._active_highlight_resource()
        if highlight is not None:
            resources["operational::DESTAQUE"] = highlight

        self._apply_resource_metrics(
            resources,
            overview.get("resource_kpis") or [],
        )

        visible_resources = []
        for resource in resources.values():
            placement = self._andon_placement(resource)
            if placement is None:
                continue
            panel, group = placement
            resource["panel"] = panel
            resource["group"] = group
            visible_resources.append(resource)

        panel_rank = {name: index for index, name in enumerate(ANDON_PANEL_ORDER)}
        ordered = sorted(
            visible_resources,
            key=lambda item: (
                panel_rank[item["panel"]],
                ANDON_GROUP_ORDER[item["panel"]].get(item["group"], 99),
                item.get("order") is None,
                item.get("order") if item.get("order") is not None else 0,
                _key(item.get("name")),
                _key(item.get("code")),
            ),
        )

        selected_panel = ANDON_PANEL_BY_SECTOR.get(_key(filters.setor))
        panel_names = (
            (selected_panel,)
            if filters.setor and selected_panel
            else (
                panel
                for panel in ANDON_PANEL_ORDER
                if panel in ANDON_DEFAULT_PANEL_ORDER
                or any(resource["panel"] == panel for resource in ordered)
            ) if not filters.setor else ()
        )
        sectors = []
        for panel_name in panel_names:
            panel_resources = [
                resource for resource in ordered
                if resource["panel"] == panel_name
            ]
            groups = []
            for resource in panel_resources:
                group_name = resource["group"]
                if not groups or groups[-1]["name"] != group_name:
                    groups.append({"name": group_name, "resources": []})
                groups[-1]["resources"].append(resource)
            sectors.append({
                "name": panel_name,
                "resource_count": len(panel_resources),
                "groups": groups,
                # Mantido para consumidores existentes e para busca do drawer;
                # a hierarquia nova fica explicitamente em ``groups``.
                "resources": panel_resources,
            })

        state_counts = Counter(
            resource["state"]["category"] for resource in ordered
        )
        kpis = dict(overview.get("kpis") or {})
        summary = {
            "resources": len(ordered),
            "production": state_counts[EventCategory.PRODUCTION.value],
            "downtime": state_counts[EventCategory.DOWNTIME.value],
            "setup": state_counts[EventCategory.SETUP.value],
            "rework": state_counts[EventCategory.REWORK.value],
            "queue": state_counts[EventCategory.QUEUE.value],
            "activity_without_op": state_counts[EventCategory.ACTIVITY_WITHOUT_OP.value],
            "out_of_shift": state_counts[EventCategory.OUT_OF_SHIFT.value],
            "no_demand": state_counts[NO_DEMAND_STATE],
            "unknown": state_counts[EventCategory.UNKNOWN.value],
            "oee": deepcopy(kpis.get("oee") or _metric_unavailable()),
            "availability": deepcopy(kpis.get("availability") or _metric_unavailable()),
            "performance": deepcopy(kpis.get("performance") or _metric_unavailable()),
            "ftt": deepcopy(kpis.get("ftt") or _metric_unavailable()),
        }
        generated_at = operational.get("agora")
        return {
            "period": filters.to_dict(),
            "generated_at": generated_at,
            "clock": {
                "now": generated_at,
                "running": not self.simulation_mode,
            },
            "current_shift": {
                "value": None,
                "availability": DataAvailability.NOT_CONFIGURED.value,
                "reason": (
                    "Não existe um turno fabril único confirmado para todos os recursos; "
                    "cada recurso pode possuir calendário próprio."
                ),
            },
            "summary": summary,
            "sectors": sectors,
            "resource_count": len(ordered),
            "simulation_only": self.simulation_mode,
            "availability": (
                DataAvailability.AVAILABLE.value
                if ordered else DataAvailability.NO_RECORDS.value
            ),
            "sources": {
                "resource_catalog": "catalogo_recursos_pcfactory",
                "physical_state": "eventos_estado_recurso",
                "op_execution": "apontamentos_operacionais+eventos_apontamento_operador",
                "quantities": "eventos_quantidade_producao",
                "factory_metrics": "ManagementService.get_overview",
                "resource_metrics": "ManagementService.get_overview.resource_kpis",
                "cut_context": "apontamentos_corte",
            },
        }

    def _active_highlight_resource(self):
        """Consolida eventos canônicos ativos no único posto de Destaque."""

        loader = getattr(self.db, "listar_destaques_ativos_andon", None)
        rows = [
            dict(row or {})
            for row in (loader() or [])
            if str((row or {}).get("estado") or "").strip().casefold()
            in {"inicio", "retomada", "parada"}
        ] if callable(loader) else []
        if not rows:
            return None

        categories = {
            EventCategory.DOWNTIME.value
            if str(row.get("estado") or "").casefold() == "parada"
            else EventCategory.PRODUCTION.value
            for row in rows
        }
        category = (
            next(iter(categories))
            if len(categories) == 1
            else EventCategory.UNKNOWN.value
        )
        current = rows[0]
        operations = []
        seen_ops = set()
        for row in rows:
            for raw_op in row.get("ops") or ():
                op = dict(raw_op or {})
                code = str(op.get("codigo_op") or "").strip()
                if not code or code in seen_ops:
                    continue
                seen_ops.add(code)
                operations.append(op)

        reason = str(current.get("motivo") or "").strip() or None
        if category == EventCategory.DOWNTIME.value:
            display_label = reason or "Motivo não informado"
            status_code = str(current.get("codigo_status_recurso") or "").strip()
            prefix = f"{status_code} - "
            if status_code and display_label.casefold().startswith(prefix.casefold()):
                display_label = display_label[len(prefix):].strip()
        elif category == EventCategory.UNKNOWN.value:
            display_label = "Estados simultâneos"
        else:
            display_label = "Destaque"

        task = str(current.get("codigo_tarefa") or "").strip()
        program = str(current.get("programa") or "").strip()
        sheet = str(current.get("nome_chapa") or "").strip()
        context = " • ".join(
            part for part in (
                f"Tarefa {task}" if task else "",
                f"Programa {program}" if program else "",
                sheet,
            ) if part
        )
        operation = operations[0] if operations else None
        return {
            "code": "DESTAQUE",
            "name": "Destaque",
            "sector": "Corte",
            "order": 3,
            "andon_group": "Destaque",
            "state": {
                "category": category,
                "label": STATE_LABELS[category],
                "display_label": display_label,
                "started_at": current.get("data_hora"),
                "duration_seconds": None,
                "reason": reason,
                "status_code": current.get("codigo_status_recurso"),
                "source": "eventos_destaque_tarefa",
                "activity_description": context or None,
            },
            "operation": ({
                "op": operation.get("codigo_op"),
                "operation": None,
                "operation_description": "Destaque",
                "product": operation.get("produto_codigo"),
                "product_description": operation.get("produto_descricao"),
                "good_quantity": None,
                "planned_quantity": None,
                "scrap_quantity": None,
                "rework_quantity": None,
                "operator": current.get("operador"),
                "started_at": current.get("data_hora"),
            } if operation else None),
            "active_operations": max(len(operations), len(rows)),
            "metrics": {
                "oee": _metric_unavailable(),
                "availability": _metric_unavailable(),
                "performance": _metric_unavailable(),
                "ftt": _metric_unavailable(),
            },
        }

    @staticmethod
    def _is_active_resource(item):
        """Decide visibilidade usando somente o estado operacional canônico.

        ``fila`` e ``fora_turno`` não são apontamentos ativos. Um conflito
        canônico permanece visível apenas quando há OP ativa vinculada, para
        não esconder execução física incompatível nem escolher um vencedor.
        """

        if item.get("sem_demanda"):
            return False
        category = str(item.get("categoria") or "").strip().casefold()
        if category in ACTIVE_ANDON_CATEGORIES:
            return True
        active_operations = int(
            item.get("quantidade_ops_ativas")
            or len(item.get("ops_ativas") or ())
        )
        return category == EventCategory.UNKNOWN.value and active_operations > 0

    @staticmethod
    def _andon_placement(resource):
        sector_key = _key(resource.get("sector"))
        panel = ANDON_PANEL_BY_SECTOR.get(sector_key)
        if panel is None:
            # Recurso ativo sem classificação aprovada não pode sumir do
            # quadro. Ele segue auditável no painel explícito, sem ser
            # promovido a um setor conhecido por semelhança de texto.
            return ANDON_UNCLASSIFIED_PANEL, str(resource.get("sector") or "Setor não informado").strip()
        if panel != "Corte":
            return panel, ANDON_GROUP_BY_SECTOR[sector_key]

        explicit_group = str(resource.get("andon_group") or "").strip()
        if explicit_group in {"Laser", "Plasma", "Destaque"}:
            return panel, explicit_group
        for identity in (resource.get("code"), resource.get("name")):
            group = ANDON_CUT_GROUP_BY_IDENTITY.get(_key(identity))
            if group:
                return panel, group
        # Sem identidade aprovada, o recurso ativo continua visível e
        # auditável em Corte, mas não é promovido a Laser/Plasma por inferência.
        return panel, "Corte"

    @staticmethod
    def _catalog_resource(item, *, code, name):
        return {
            "code": code,
            "name": name,
            "sector": str(item.get("tipo_setor") or "").strip() or "Setor não informado",
            "order": item.get("ordem"),
            "andon_group": item.get("grupo_andon"),
            "state": {
                "category": EventCategory.UNKNOWN.value,
                "physical_category": EventCategory.UNKNOWN.value,
                "label": STATE_LABELS[EventCategory.UNKNOWN.value],
                "stop_classification": None,
                "color": None,
                "started_at": None,
                "duration_seconds": None,
                "reason": "Estado físico canônico não registrado para este recurso.",
                "status_code": None,
                "source": "catalogo_recursos_pcfactory_sem_estado_fisico",
            },
            "operation": None,
            "active_operations": 0,
            "metrics": {
                "oee": _metric_unavailable(),
                "availability": _metric_unavailable(),
                "performance": _metric_unavailable(),
                "ftt": _metric_unavailable(),
            },
        }

    def _uncatalogued_resource(self, item, resource_name):
        resource = self._catalog_resource(
            {"tipo_setor": item.get("setor")},
            code=resource_name,
            name=resource_name,
        )
        resource["state"]["reason"] = (
            "Recurso presente na execução atual, mas ausente do catálogo canônico habilitado."
        )
        return resource

    @staticmethod
    def _apply_operational_state(resource, item):
        raw_category = str(item.get("categoria") or "").strip().casefold()
        category = (
            raw_category
            if raw_category in STATE_LABELS
            else EventCategory.UNKNOWN.value
        )
        physical_category = category
        if item.get("sem_demanda"):
            category = NO_DEMAND_STATE
        reason = item.get("motivo")
        status_code = item.get("codigo_status")
        if category == NO_DEMAND_STATE:
            display_label = STATE_LABELS[NO_DEMAND_STATE]
            reason = "Recurso sem OP e sem trabalho em execução."
        elif category == EventCategory.DOWNTIME.value:
            display_label = str(reason or "Motivo não informado").strip()
            prefix = f"{str(status_code or '').strip()} - "
            if status_code and display_label.casefold().startswith(prefix.casefold()):
                display_label = display_label[len(prefix):].strip()
        elif category == EventCategory.ACTIVITY_WITHOUT_OP.value:
            display_label = ManufacturingRules.activity_display_label(
                item.get("tipo_atividade")
            )
        else:
            display_label = STATE_LABELS[category]
        # A classificação e a cor vêm resolvidas da camada canônica. O Andon não
        # decide cor por motivo nem por grupo de catálogo.
        # Sem demanda nunca carrega classificação nem cor de parada: é
        # exatamente o que ela não é.
        no_demand = category == NO_DEMAND_STATE
        classification = None if no_demand else item.get("classificacao_parada")
        resource["state"] = {
            "category": category,
            # O estado físico persistido continua visível: a leitura "sem
            # demanda" é derivada dele, não o substitui na base.
            "physical_category": physical_category,
            "label": STATE_LABELS[category],
            "display_label": display_label,
            "stop_classification": classification,
            "color": None if no_demand else item.get("cor_parada"),
            "started_at": item.get("inicio"),
            "duration_seconds": item.get("duracao_segundos"),
            "reason": reason,
            "status_code": status_code,
            "source": item.get("fonte"),
            "activity_description": (
                item.get("descricao_atividade")
                or item.get("motivo")
                or item.get("comentario")
            ),
        }
        operational_sector = str(item.get("setor") or "").strip()
        if operational_sector and resource.get("sector") == "Setor não informado":
            resource["sector"] = operational_sector
        operations = list(item.get("ops_ativas") or [])
        resource["active_operations"] = int(item.get("quantidade_ops_ativas") or len(operations))
        current = dict(operations[0]) if operations else None
        if current is None and item.get("op_estado"):
            current = {
                "op": item.get("op_estado"),
                "operacao": item.get("operacao_estado"),
                "produto": item.get("produto_estado"),
                "operador_inicio": item.get("operador_estado"),
            }
            resource["active_operations"] = max(1, resource["active_operations"])
        if current is not None:
            resource["operation"] = {
                "op": current.get("op"),
                "operation": current.get("operacao"),
                "operation_description": current.get("descricao_operacao"),
                "product": current.get("produto"),
                "product_description": current.get("descricao_produto"),
                "good_quantity": current.get("quantidade_boa"),
                "planned_quantity": current.get("quantidade_planejada"),
                "scrap_quantity": current.get("refugo"),
                "rework_quantity": current.get("retrabalho"),
                "operator": current.get("operador_inicio"),
                "started_at": current.get("inicio"),
            }

    @staticmethod
    def _apply_resource_metrics(resources, metric_rows):
        """Associa KPIs já calculados sem inferir identidades ambíguas."""

        exact = {}
        aliases = {}
        ambiguous_aliases = set()
        for raw in metric_rows or ():
            item = dict(raw or {})
            identity = str(item.get("resource") or "").strip()
            if not identity:
                continue
            exact[identity] = item
            alias = _key(identity)
            current = aliases.get(alias)
            if current is not None and current is not item:
                ambiguous_aliases.add(alias)
                aliases.pop(alias, None)
            elif alias not in ambiguous_aliases:
                aliases[alias] = item

        for resource in resources.values():
            candidates = tuple(dict.fromkeys(
                str(resource.get(field) or "").strip()
                for field in ("code", "name")
                if str(resource.get(field) or "").strip()
            ))
            matched = next((exact[value] for value in candidates if value in exact), None)
            if matched is None:
                matched = next(
                    (
                        aliases[_key(value)]
                        for value in candidates
                        if _key(value) not in ambiguous_aliases and _key(value) in aliases
                    ),
                    None,
                )
            if matched is None:
                continue
            metrics = dict(matched.get("metrics") or {})
            resource["metrics"] = {
                key: deepcopy(metrics.get(key) or _metric_unavailable())
                for key in ("oee", "availability", "performance", "ftt")
            }


__all__ = ["AndonService", "STATE_LABELS"]
