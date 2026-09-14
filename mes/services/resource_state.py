"""Estado físico canônico do recurso, sem dependência de apresentação.

A timeline física pertence ao recurso. OPs e operadores são vínculos de
rastreabilidade/atribuição e não devem multiplicar tempo de máquina.
"""

from __future__ import annotations

from collections import defaultdict

from mes.domain import EventCategory, ManufacturingRules


class ResourceStateService:
    def __init__(self, db, operador):
        self.db = db
        self.operador = str(operador or "SISTEMA").strip() or "SISTEMA"

    def registrar_atividade_sem_op(
        self, recurso, *, tipo_setor=None, codigo_status_recurso=None,
        motivo=None, causa_raiz=None, comentario=None, data_hora=None,
    ):
        return self.db.transicionar_estado_recurso(
            recurso,
            EventCategory.ACTIVITY_WITHOUT_OP.value,
            tipo_setor=tipo_setor,
            operador=self.operador,
            codigo_status_recurso=codigo_status_recurso,
            motivo=motivo,
            causa_raiz=causa_raiz,
            comentario=comentario,
            data_hora=data_hora,
            origem="resource_state_service",
            planejado=None,
            automatico=False,
        )

    def registrar_fora_turno(
        self, recurso, *, tipo_setor=None, data_hora=None,
        motivo="Fim de turno — interrupção programada automática",
        automatico=True, tipo_interrupcao="fim_turno",
    ):
        return self.db.transicionar_estado_recurso(
            recurso,
            EventCategory.OUT_OF_SHIFT.value,
            tipo_setor=tipo_setor,
            operador=self.operador,
            motivo=motivo,
            data_hora=data_hora,
            origem="resource_state_service",
            planejado=True,
            automatico=automatico,
            tipo_interrupcao=tipo_interrupcao,
        )

    def registrar_estado(
        self, recurso, categoria, *, tipo_setor=None, op=None,
        numero_operacao=None, produto_codigo=None, codigo_status_recurso=None,
        motivo=None, causa_raiz=None, comentario=None, data_hora=None,
        planejado=None, automatico=False, tipo_interrupcao=None,
        apontamento_id=None, evento_apontamento_id=None,
    ):
        category = EventCategory(categoria)
        if category == EventCategory.DOWNTIME and planejado is None:
            planejado = ManufacturingRules.manual_stop_is_planned()
        return self.db.transicionar_estado_recurso(
            recurso,
            category.value,
            tipo_setor=tipo_setor,
            operador=self.operador,
            codigo_status_recurso=codigo_status_recurso,
            op=op,
            numero_operacao=numero_operacao,
            produto_codigo=produto_codigo,
            motivo=motivo,
            causa_raiz=causa_raiz,
            comentario=comentario,
            data_hora=data_hora,
            origem="resource_state_service",
            planejado=planejado,
            automatico=automatico,
            tipo_interrupcao=tipo_interrupcao,
            apontamento_id=apontamento_id,
            evento_apontamento_id=evento_apontamento_id,
        )

    def encerrar(self, recurso, *, data_hora=None):
        closer = getattr(self.db, "encerrar_estado_recurso", None)
        if not callable(closer):
            return None
        return closer(recurso, data_hora=data_hora)

    def atual(self, recurso):
        loader = getattr(self.db, "buscar_estado_recurso_atual", None)
        return loader(recurso) if callable(loader) else None

    def listar_periodo(
        self, inicio, fim, *, setor=None, recurso=None, categoria=None,
        op=None, operacao=None,
    ):
        loader = getattr(self.db, "listar_estados_recurso_periodo", None)
        if not callable(loader):
            return []
        return list(loader(
            inicio,
            fim,
            setor=setor,
            recurso=recurso,
            categoria=(EventCategory(categoria).value if categoria else None),
            op=op,
            operacao=operacao,
        ) or [])

    def resumo_periodo(self, inicio, fim, *, setor=None, recurso=None):
        rows = self.listar_periodo(inicio, fim, setor=setor, recurso=recurso)
        totals = defaultdict(float)
        by_resource = defaultdict(lambda: defaultdict(float))
        by_sector = defaultdict(lambda: defaultdict(float))
        unknown_seconds = 0.0
        for row in rows:
            try:
                category = EventCategory(str(row.get("categoria") or ""))
            except ValueError:
                category = EventCategory.UNKNOWN
            seconds = float(row.get("segundos_periodo") or 0.0)
            totals[category] += seconds
            resource_key = str(row.get("recurso") or "Não informado")
            sector_key = str(row.get("tipo_setor") or "Não informado")
            by_resource[resource_key][category] += seconds
            by_sector[sector_key][category] += seconds
            if category == EventCategory.UNKNOWN:
                unknown_seconds += seconds

        return {
            "inicio": inicio,
            "fim": fim,
            "fonte": "eventos_estado_recurso",
            "totals": {category.value: float(totals[category]) for category in EventCategory},
            "productive_seconds": sum(
                totals[category]
                for category in EventCategory
                if ManufacturingRules.is_productive(category)
            ),
            "unknown_seconds": unknown_seconds,
            "by_resource": [
                {
                    "recurso": key,
                    **{category.value: float(values[category]) for category in EventCategory},
                }
                for key, values in sorted(by_resource.items(), key=lambda item: item[0].casefold())
            ],
            "by_sector": [
                {
                    "setor": key,
                    **{category.value: float(values[category]) for category in EventCategory},
                }
                for key, values in sorted(by_sector.items(), key=lambda item: item[0].casefold())
            ],
            "items": rows,
        }
