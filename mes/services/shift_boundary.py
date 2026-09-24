"""Interrupção automática de apontamentos nos limites oficiais de turno.

A camada é independente do adaptador HTTP. O backend pode chamá-la periodicamente e
uma futura API Web pode executar a mesma regra por scheduler/backend.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from mes.domain.manufacturing_rules import (
    AUTOMATIC_BREAK_INTERRUPTION_TYPE,
    ManufacturingRules,
    SHIFT_END_INTERRUPTION_TYPE,
    SHIFT_END_REASON,
    SHIFT_START_NO_DEMAND_REASON,
    SHIFT_START_NO_DEMAND_TYPE,
    SYSTEM_OPERATOR,
)
from mes.domain import ShiftWindowKind
from mes.services.calendar import CalendarService


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

    def due_shift_starts(self, now=None, *, lookback_hours=24):
        """Aberturas do turno oficial alcançadas na janela de recuperação."""

        now = now or self._now()
        floor = now - timedelta(hours=max(1, int(lookback_hours)))
        shift_start = self.rules.official_work_window[0]
        candidates = []
        for day_offset in (-1, 0):
            moment = datetime.combine(
                now.date() + timedelta(days=day_offset), shift_start
            )
            if floor <= moment <= now:
                candidates.append(moment)
        return tuple(sorted(set(candidates)))

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
            except Exception:
                # Erro de leitura (ex.: banco indisponível): usa a lista fixa
                # para a fábrica inteira, para não deixar de aplicar pausa
                # nenhuma por causa de uma falha transitória de infraestrutura.
                logging.exception(
                    "Falha ao ler as pausas automáticas configuradas; usando a lista padrão."
                )
                return tuple(
                    (start, end, name, None)
                    for start, end, name in self.rules.automatic_breaks
                )
            # Configuração lida com sucesso: lista vazia é uma decisão
            # gerencial válida (setor desativou todas as pausas) e deve ser
            # respeitada, não substituída pela lista fixa da fábrica inteira.
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

    def active_resource_profiles(self):
        """Recursos habilitados que devem possuir timeline contínua."""

        loader = getattr(self.db, "listar_recursos_ativos_scheduler", None)
        if callable(loader):
            return tuple(dict(row) for row in (loader() or []))
        loader = getattr(self.db, "listar_recursos_pcfactory", None)
        if not callable(loader):
            return ()
        return tuple(
            {
                "codigo": row.get("codigo"),
                "nome": row.get("nome"),
                "tipo_setor": row.get("tipo_setor"),
                "aliases": [row.get("codigo"), row.get("nome")],
                "calendario_codigo": row.get("calendario_codigo"),
                "sincronizado_em": row.get("sincronizado_em"),
            }
            for row in (loader(somente_habilitados=True) or [])
            if row.get("codigo")
        )

    @staticmethod
    def _profile_matches(profile, value):
        key = str(value or "").strip().casefold()
        return bool(key) and key in {
            str(alias or "").strip().casefold()
            for alias in (profile.get("aliases") or [profile.get("codigo"), profile.get("nome")])
            if str(alias or "").strip()
        }

    def active_break(self, profile, now):
        """``(início, nome)`` da pausa configurada vigente para o setor, ou None."""

        sector = str(profile.get("tipo_setor") or "").strip().casefold()
        for start_time, end_time, name, configured_sector in self.configured_breaks():
            if configured_sector and str(configured_sector).strip().casefold() != sector:
                continue
            start = datetime.combine(now.date(), start_time)
            end = datetime.combine(now.date(), end_time)
            if end <= start:
                if now < start:
                    start -= timedelta(days=1)
                else:
                    end += timedelta(days=1)
            if start <= now < end:
                return start, name
        return None

    def _synchronize_missing_resources(self, now, profiles):
        """Cria o primeiro estado de todo recurso ativo ainda sem timeline."""

        state_loader = getattr(self.db, "listar_estados_recurso_atuais", None)
        transition = getattr(self.db, "transicionar_estado_recurso", None)
        if not callable(state_loader) or not callable(transition):
            return []
        current = list(state_loader(reference_time=now) or [])
        active_loader = getattr(self.db, "listar_recursos_ativos_no_instante", None)
        executing = list(active_loader(now) or []) if callable(active_loader) else []
        calendar = CalendarService(self.db, self.rules)
        created = []
        for profile in profiles:
            if any(self._profile_matches(profile, row.get("recurso")) for row in current):
                continue
            if any(self._profile_matches(profile, row.get("recurso")) for row in executing):
                continue
            resource = profile.get("codigo")
            sector = profile.get("tipo_setor")
            window = calendar.shift_window_kind(resource, now)
            active_break = self.active_break(profile, now)
            if window is ShiftWindowKind.OUT_OF_SHIFT:
                category = "fora_turno"
                reason = SHIFT_END_REASON
                origin = "sincronizacao_calendario_recurso"
                planned = True
                interruption_type = SHIFT_END_INTERRUPTION_TYPE
            elif active_break:
                category = "parada"
                reason = f"Intervalo automático — {active_break[1]}"
                origin = "intervalo_programado_inicio"
                planned = True
                interruption_type = AUTOMATIC_BREAK_INTERRUPTION_TYPE
            else:
                category = "fila"
                reason = SHIFT_START_NO_DEMAND_REASON
                origin = "sincronizacao_recurso_sem_demanda"
                planned = None
                interruption_type = SHIFT_START_NO_DEMAND_TYPE
            state = transition(
                resource,
                category,
                tipo_setor=sector,
                operador=SYSTEM_OPERATOR,
                motivo=reason,
                data_hora=now,
                origem=origin,
                planejado=planned,
                automatico=True,
                tipo_interrupcao=interruption_type,
            )
            if state and not state.get("retroativo_ignorado"):
                created.append(dict(state))
                current.append(state)
        return created

    def due_resource_calendar_events(self, now, profiles, *, lookback_hours=24):
        """Aberturas/fechamentos dos calendários próprios por recurso."""

        floor = now - timedelta(hours=max(1, int(lookback_hours)))
        calendar = CalendarService(self.db, self.rules)
        grouped = {}
        for profile in profiles:
            if not profile.get("calendario_codigo"):
                continue
            intervals = calendar.operational_intervals(
                profile.get("codigo"),
                floor - timedelta(days=1),
                now + timedelta(days=2),
            )
            for start, end in intervals:
                synchronized_at = profile.get("sincronizado_em")
                if floor <= start <= now and (
                    synchronized_at is None or synchronized_at <= start
                ):
                    grouped.setdefault((start, "inicio"), []).append(profile)
                if floor <= end <= now and (
                    synchronized_at is None or synchronized_at <= end
                ):
                    grouped.setdefault((end, "fim"), []).append(profile)
        return tuple(
            (moment, kind, tuple(rows))
            for (moment, kind), rows in sorted(
                grouped.items(), key=lambda item: (item[0][0], 0 if item[0][1] == "fim" else 1)
            )
        )

    def apply_due(self, now=None):
        """Aplica todos os limites recentes ainda pendentes às OPs abertas.

        A interrupção é persistida no horário oficial (17:30/21:30), e não no
        instante em que o timer a detecta. O repositório garante idempotência.
        """

        now = now or self._now()
        profiles = self.active_resource_profiles()
        custom_profiles = tuple(
            profile for profile in profiles if profile.get("calendario_codigo")
        )
        custom_codes = [profile.get("codigo") for profile in custom_profiles]

        def belongs_to_custom_calendar(row):
            value = row.get("maquina") or row.get("recurso")
            return any(self._profile_matches(profile, value) for profile in custom_profiles)

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
                    if belongs_to_custom_calendar(row):
                        continue
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
                    if belongs_to_custom_calendar(row):
                        continue
                    result = cut_interrupter(
                        row["id"],
                        data_hora=boundary,
                        operador=SYSTEM_OPERATOR,
                        motivo=SHIFT_END_REASON,
                        tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                    )
                    if result is not None and result.get("interrupcao_registrada"):
                        cut_interrupted.append(result)

        # Complemento do corte acima: a maioria dos recursos, na maioria dos
        # dias, já está ociosa (sem OP nem nesting aberto) bem antes do limite
        # oficial. Sem isto, esses recursos nunca recebem o evento físico de
        # "fora de turno" e somem do Andon em vez de aparecer como "Sem
        # demanda" — ver mes/services/andon.py.
        idle_interrupter = getattr(self.db, "interromper_recursos_ociosos_fim_turno", None)
        idle_interrupted = []
        if callable(idle_interrupter):
            for boundary in boundaries:
                kwargs = {
                    "operador": SYSTEM_OPERATOR,
                    "motivo": SHIFT_END_REASON,
                    "tipo_interrupcao": SHIFT_END_INTERRUPTION_TYPE,
                }
                if custom_codes:
                    kwargs["excluir_recursos"] = custom_codes
                rows = list(idle_interrupter(boundary, **kwargs) or [])
                if rows:
                    idle_interrupted.extend(rows)

        shift_returns = []
        shift_returner = getattr(
            self.db, "finalizar_fora_turno_automatico", None
        )
        if callable(shift_returner):
            for moment in self.due_shift_starts(now):
                kwargs = {
                    "operador": SYSTEM_OPERATOR,
                    "motivo": SHIFT_START_NO_DEMAND_REASON,
                    "tipo_interrupcao": SHIFT_START_NO_DEMAND_TYPE,
                }
                if custom_codes:
                    kwargs["excluir_recursos"] = custom_codes
                rows = list(shift_returner(moment, **kwargs) or [])
                if rows:
                    shift_returns.extend(rows)

        resource_calendar_changes = []
        for moment, event_kind, event_profiles in self.due_resource_calendar_events(
            now, profiles
        ):
            event_codes = [profile.get("codigo") for profile in event_profiles]
            changed = []
            if event_kind == "fim":
                if callable(loader) and callable(interrupter):
                    for row in list(loader(moment) or []):
                        if not any(self._profile_matches(p, row.get("maquina")) for p in event_profiles):
                            continue
                        result = interrupter(
                            row["id"], data_hora=moment, operador=SYSTEM_OPERATOR,
                            motivo=SHIFT_END_REASON,
                            tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                        )
                        if result is not None and result.get("interrupcao_registrada"):
                            interrupted.append(result)
                            changed.append(result)
                if callable(cut_loader) and callable(cut_interrupter):
                    for row in list(cut_loader(moment) or []):
                        if not any(self._profile_matches(p, row.get("maquina")) for p in event_profiles):
                            continue
                        result = cut_interrupter(
                            row["id"], data_hora=moment, operador=SYSTEM_OPERATOR,
                            motivo=SHIFT_END_REASON,
                            tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                        )
                        if result is not None and result.get("interrupcao_registrada"):
                            cut_interrupted.append(result)
                            changed.append(result)
                if callable(idle_interrupter):
                    rows = list(idle_interrupter(
                        moment, operador=SYSTEM_OPERATOR, motivo=SHIFT_END_REASON,
                        tipo_interrupcao=SHIFT_END_INTERRUPTION_TYPE,
                        recursos=event_codes,
                    ) or [])
                    idle_interrupted.extend(rows)
                    changed.extend(rows)
            elif callable(shift_returner):
                rows = list(shift_returner(
                    moment, operador=SYSTEM_OPERATOR,
                    motivo=SHIFT_START_NO_DEMAND_REASON,
                    tipo_interrupcao=SHIFT_START_NO_DEMAND_TYPE,
                    recursos=event_codes,
                ) or [])
                shift_returns.extend(rows)
                changed.extend(rows)
            if changed:
                resource_calendar_changes.append({
                    "data_hora": moment,
                    "evento": event_kind,
                    "recursos": changed,
                })

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

        initialized_resources = self._synchronize_missing_resources(now, profiles)

        return {
            "boundary": boundaries[-1] if boundaries else None,
            "boundaries": list(boundaries),
            "checked_at": now,
            "interrupted": interrupted,
            "cut_interrupted": cut_interrupted,
            "idle_interrupted": idle_interrupted,
            "shift_returns": shift_returns,
            "resource_calendar_changes": resource_calendar_changes,
            "break_changes": break_changes,
            "initialized_resources": initialized_resources,
            "count": len(interrupted) + len(cut_interrupted) + len(idle_interrupted)
            + len(shift_returns) + len(initialized_resources) + sum(
                len(item["recursos"]) for item in break_changes
            ),
        }
