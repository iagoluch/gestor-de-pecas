import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DashboardCardKey, UserDashboardPreferences, UserPreferences } from "../types/api";

export const DEFAULT_PREFERENCES: UserDashboardPreferences = {
  cards: {
    producao_boa: true,
    oee: true,
    disponibilidade: true,
    performance: true,
    ftt: true,
    simulation: true,
    planned_vs_actual: true,
    exceptions: true,
    time_composition: true,
    top_losses: true,
    live_events: true,
    sectors_table: true,
    top_resources: true,
    audit_issues: true,
  },
  order: [
    "producao_boa",
    "oee",
    "disponibilidade",
    "performance",
    "ftt",
    "simulation",
    "planned_vs_actual",
    "exceptions",
    "time_composition",
    "top_losses",
    "live_events",
    "sectors_table",
    "top_resources",
    "audit_issues",
  ],
};

const clonePreferences = (prefs: UserDashboardPreferences): UserDashboardPreferences => ({
  cards: { ...prefs.cards },
  order: [...prefs.order],
});

const DEFAULT_KEYS = new Set<DashboardCardKey>(Object.keys(DEFAULT_PREFERENCES.cards) as DashboardCardKey[]);

/** Funde o que veio do servidor com o default: chave nova ou vencida nunca quebra a tela. */
function mergePreferences(remote?: Partial<UserDashboardPreferences> | null): UserDashboardPreferences {
  const cards = { ...DEFAULT_PREFERENCES.cards };
  if (remote?.cards) {
    for (const key of Object.keys(cards) as DashboardCardKey[]) {
      if (typeof remote.cards[key] === "boolean") cards[key] = remote.cards[key] as boolean;
    }
  }
  const seen = new Set<DashboardCardKey>();
  const order: DashboardCardKey[] = [];
  if (Array.isArray(remote?.order)) {
    for (const key of remote.order) {
      if (typeof key === "string" && DEFAULT_KEYS.has(key as DashboardCardKey) && !seen.has(key as DashboardCardKey)) {
        const typed = key as DashboardCardKey;
        seen.add(typed);
        order.push(typed);
      }
    }
  }
  order.push(...DEFAULT_PREFERENCES.order.filter((key) => !seen.has(key)));
  return { cards, order };
}

export function moveDashboardCard(
  order: DashboardCardKey[],
  card: DashboardCardKey,
  target: DashboardCardKey,
  before: boolean,
): DashboardCardKey[] {
  const current = order.filter((key) => key !== card);
  const index = current.indexOf(target);
  if (index < 0) return [...order];
  current.splice(before ? index : index + 1, 0, card);
  return current;
}

// ponytail: reverts locally on save failure; a retry queue can be added when flaky networks are measured.
/** Preferências pessoais da dashboard home. */
export function useUserPreferences() {
  const [preferences, setPreferences] = useState<UserDashboardPreferences>(clonePreferences(DEFAULT_PREFERENCES));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const preferencesRef = useRef(preferences);
  preferencesRef.current = preferences;

  useEffect(() => {
    let cancelled = false;
    api
      .get<UserPreferences>("/api/v1/auth/preferences")
      .then((data) => {
        if (cancelled) return;
        const merged = mergePreferences(data?.dashboard_home);
        setPreferences(merged);
        setError(null);
      })
      .catch((reason) => {
        if (cancelled) return;
        setError(
          reason instanceof ApiError
            ? reason
            : new ApiError(0, { code: "network_error", message: "Não foi possível carregar suas preferências." }),
        );
        setPreferences(clonePreferences(DEFAULT_PREFERENCES));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const saveDashboard = useCallback(
    async (next: UserDashboardPreferences, previous: UserDashboardPreferences) => {
      setSaving(true);
      setError(null);
      setPreferences(next);
      try {
        const data = await api.post<UserPreferences>("/api/v1/auth/preferences", {
          dashboard_home: clonePreferences(next),
        });
        const merged = mergePreferences(data?.dashboard_home ?? next);
        setPreferences(merged);
      } catch (reason) {
        setPreferences(previous);
        setError(
          reason instanceof ApiError
            ? reason
            : new ApiError(0, { code: "network_error", message: "Não foi possível salvar suas preferências." }),
        );
      } finally {
        setSaving(false);
      }
    },
    [],
  );

  const moveCard = useCallback(
    (card: DashboardCardKey, target: DashboardCardKey, before: boolean) => {
      const previous = clonePreferences(preferencesRef.current);
      const next = {
        cards: { ...previous.cards },
        order: moveDashboardCard(previous.order, card, target, before),
      };
      void saveDashboard(next, previous);
    },
    [saveDashboard],
  );

  const toggleCard = useCallback(
    (card: DashboardCardKey) => {
      const previous = clonePreferences(preferencesRef.current);
      const next = {
        cards: { ...previous.cards, [card]: !previous.cards[card] },
        order: [...previous.order],
      };
      void saveDashboard(next, previous);
    },
    [saveDashboard],
  );

  const resetToDefault = useCallback(() => {
    const previous = clonePreferences(preferencesRef.current);
    void saveDashboard(clonePreferences(DEFAULT_PREFERENCES), previous);
  }, [saveDashboard]);

  return {
    preferences,
    cards: preferences.cards,
    order: preferences.order,
    loading,
    saving,
    error,
    moveCard,
    toggleCard,
    resetToDefault,
  };
}
