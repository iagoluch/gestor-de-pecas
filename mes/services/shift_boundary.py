"""Interrupção automática de apontamentos nos limites oficiais de turno.

A camada é independente do adaptador HTTP. O backend pode chamá-la periodicamente e
uma futura API Web pode executar a mesma regra por scheduler/backend.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mes.domain.manufacturing_rules import (
    AUTOMATIC_BREAK_INTERRUPTION_TYPE,
    ManufacturingRules,
    SHIFT_END_INTERRUPTION_TYPE,
    SHIFT_END_REASON,
    SYSTEM_OPERATOR,
)


class ShiftBoundaryService:
    """Aplica interrupções de fim de turno de forma idempotente."""

    def __init__(self, db, *, now_func=None, rules=None):
        self.db = db
        self._now = now_func or datetime.now
        self.rules = rules or ManufacturingRules()

    def due_boundaries(self, now=None, *, lookback_hours=24):
        """Limites já ocorridos dentro da janela de recuperação.

        A janela cobre o dia atual e o anterior para recuperar uma aplicação
        que ficou fechada durante um fim de turno, sem reprocessar histórico
        antigo indefinidamente.
        """

        now = now or self._now()
        floor = now - timedelta(hours=max(1, int(lookback_hours)))
        candidates = []
        for day_offset in (-1, 0):
            day = now.date() + timedelta(days=day_offset)
            for boundary_time in self.rules.shift_end_boundaries:
                boundary = datetime.combine(day, boundary_time)
                if floor <= boundary <= now:
                    candidates.append(boundary)
        return tuple(sorted(set(candidates)))

    def latest_due_boundary(self, now=None):
        boundaries = self.due_boundaries(now)
        return boundaries[-1] if boundaries else None

    def configured_breaks(self):
        """Pausas automáticas vigentes, por setor.

        A configuração gerencial (``pausas_automaticas_setor``) é a autoridade:
        o documento oficial de fluxo define horários diferentes por setor e
        prevê mudança futura, com mais de uma pausa por dia. A lista fixa do
        domínio permanece apenas como fallback para bancos que ainda não
        possuem a tabela — nesse caso a pausa vale para toda a fábrica.
        """

        loader = getattr(self.db, "listar_pausas_automaticas", None)
        if callable(loader):
            try:
                rows = list(loader(somente_ativas=True) or [])
            except Exception:  # pragma: no cover - configuração indisponível
                rows = []
            if rows:
                return tuple(
                    (
                        row["hora_inicio"],
                        row["hora_fim"],
                        str(row.get("nome") or "Intervalo").strip(),
                        str(row.get("tipo_setor") or "").strip() or None,
                    )
                    for row in rows
                    if row.get("hora_inicio") is not None
                    and row.get("hora_fim") is not None
                )
        return tuple(
            (start, end, name, None) for start, end, name in self.rules.automatic_breaks
        )

    def due_break_events(self, now=None, *, lookback_hours=24):
        """Inícios e fins de intervalos automáticos já alcançados.

        Cada evento carrega o setor da configuração; ``None`` significa fábrica
        inteira. Dois setores com o mesmo horário geram eventos distintos, e é
        isso que permite pausas escalonadas sem inventar regra no código.
        """

        now = now or self._now()
        floor = now - timedelta(hours=max(1, int(lookback_hours)))
        events = []
        for day_offset in (-1, 0):
            day = now.date() + timedelta(days=day_offset)
            for start_time, end_time, name, sector in self.configured_breaks():
                start = datetime.combine(day, start_time)
                end = datetime.combine(day, end_time)
                if end <= start:
                    end += timedelta(days=1)
                if floor <= start <= now:
                    events.append((start, "inicio", name, sector))
                if floor <= end <= now:
                    events.append((end, "fim", name, sector))
        return tuple(
            sorted(
                set(events),
                key=lambda item: (item[0], item[1], item[2], item[3] or ""),
            )
        )

    def apply_due(self, now=None):
        """Aplica todos os limites recentes ainda pendentes às OPs abertas.

        A interrupção é persistida no horário oficial (17:30/21:30), e não no
        instante em que o timer a detecta. O repositório garante idempotência.
        """

        now = now or self._now()
        boundaries = self.due_boundaries(now)
        loader = getattr(self.db, "listar_apontamentos_abertos_no_limite_turno", None)
        interrupter = getattr(self.db, "interromper_apontamento_fim_turno", None)
        if boundaries and (not callable(loader) or not callable(interrupter)):
            return {
                "boundary": boundaries[-1],
                "boundaries": list(boundaries),
                "checked_at": now,
                "interrupted": [],
                "count": 0,
                "availability": "nao_configurado",
            }

        interrupted = []
        if callable(loader) and callable(interrupter):
            for boundary in boundaries:
                rows = list(loader(boundary) or [])
                for row in rows:
                    result = interrupter(
                        row["id"],
                        data_hora=boundary,
                        operador=SYSTEM_OPERATOR,
                        motivo=SHIFT_END_REASON,
                        tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                    )
                    if result is not None and result.get("interrupcao_registrada"):
                        interrupted.append(result)

        cut_loader = getattr(self.db, "listar_cortes_abertos_no_limite_turno", None)
        cut_interrupter = getattr(self.db, "interromper_corte_fim_turno", None)
        cut_interrupted = []
        if callable(cut_loader) and callable(cut_interrupter):
            for boundary in boundaries:
                for row in list(cut_loader(boundary) or []):
                    result = cut_interrupter(
                        row["id"],
                        data_hora=boundary,
                        operador=SYSTEM_OPERATOR,
                        motivo=SHIFT_END_REASON,
                        tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                    )
                    if result is not None and result.get("interrupcao_registrada"):
                        cut_interrupted.append(result)

        break_events = self.due_break_events(now)
        break_changes = []
        break_starter = getattr(self.db, "iniciar_intervalo_automatico", None)
        break_finisher = getattr(self.db, "finalizar_intervalo_automatico", None)
        for moment, event_kind, name, sector in break_events:
            handler = break_starter if event_kind == "inicio" else break_finisher
            if not callable(handler):
                continue
            rows = list(
                handler(
                    moment, name, operador=SYSTEM_OPERATOR, tipo_setor=sector
                ) or []
            )
            if rows:
                break_changes.append({
                    "data_hora": moment,
                    "evento": event_kind,
                    "nome": name,
                    "tipo_setor": sector,
                    "tipo_interrupcao": AUTOMATIC_BREAK_INTERRUPTION_TYPE,
                    "recursos": rows,
                })

        return {
            "boundary": boundaries[-1] if boundaries else None,
            "boundaries": list(boundaries),
            "checked_at": now,
            "interrupted": interrupted,
            "cut_interrupted": cut_interrupted,
            "break_changes": break_changes,
            "count": len(interrupted) + len(cut_interrupted) + sum(
                len(item["recursos"]) for item in break_changes
            ),
        }
