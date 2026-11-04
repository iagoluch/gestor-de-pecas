import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { DashboardCardKey, DashboardCardSize, UserDashboardPreferences, UserPreferences } from "../types/api";
import {
  DASHBOARD_CARD_KEYS,
  DEFAULT_DASHBOARD_SIZES,
  DEFAULT_VISIBLE_CARDS,
  MAX_CARDS_ON_SCREEN,
  clampCardSize,
  cloneSizes,
} from "../utils/dashboardCards";

const defaultCards = Object.fromEntries(
  DASHBOARD_CARD_KEYS.map((key) => [key, DEFAULT_VISIBLE_CARDS.includes(key)]),
) as unknown as UserDashboardPreferences["cards"];

export const DEFAULT_PREFERENCES: UserDashboardPreferences = {
  cards: defaultCards,
  order: [...DASHBOARD_CARD_KEYS],
  sizes: cloneSizes(DEFAULT_DASHBOARD_SIZES),
};

const clonePreferences = (prefs: UserDashboardPreferences): UserDashboardPreferences => ({
  cards: { ...prefs.cards },
  order: [...prefs.order],
  sizes: cloneSizes(prefs.sizes),
});

const DEFAULT_KEYS = new Set<DashboardCardKey>(DASHBOARD_CARD_KEYS);

/** Funde o que veio do servidor com o default: chave nova ou vencida nunca quebra a tela. */
function mergePreferences(remote?: Partial<UserDashboardPreferences> | null): UserDashboardPreferences {
  const cards = { ...DEFAULT_PREFERENCES.cards };
  if (remote?.cards) {
    for (const key of DASHBOARD_CARD_KEYS) {
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
  order.push(...DASHBOARD_CARD_KEYS.filter((key) => !seen.has(key)));
  const sizes = Object.fromEntries(
    DASHBOARD_CARD_KEYS.map((key) => [key, clampCardSize(key, remote?.sizes?.[key])]),
  ) as Record<DashboardCardKey, DashboardCardSize>;
  return { cards, order, sizes };
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

/** Ordem completa: cada chave uma vez, na sequência pedida. */
export function normalizeDashboardOrder(order: readonly DashboardCardKey[]): DashboardCardKey[] {
  const seen = new Set<DashboardCardKey>();
  const normalized: DashboardCardKey[] = [];
  for (const key of order) {
    if (DEFAULT_KEYS.has(key) && !seen.has(key)) {
      seen.add(key);
      normalized.push(key);
    }
  }
  normalized.push(...DASHBOARD_CARD_KEYS.filter((key) => !seen.has(key)));
  return normalized;
}

const sameOrder = (a: readonly DashboardCardKey[], b: readonly DashboardCardKey[]) =>
  a.length === b.length && a.every((key, index) => key === b[index]);

// ponytail: reverts locally on save failure; a retry queue can be added when flaky networks are measured.
/** Preferências pessoais da dashboard home: visibilidade, ordem e tamanho. */
export function useUserPreferences() {
  const [preferences, setPreferences] = useState<UserDashboardPreferences>(clonePreferences(DEFAULT_PREFERENCES));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
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

  const reorderCards = useCallback(
    (order: readonly DashboardCardKey[]) => {
      const previous = clonePreferences(preferencesRef.current);
      const normalized = normalizeDashboardOrder(order);
      if (sameOrder(previous.order, normalized)) return;
      void saveDashboard({ ...previous, order: normalized }, previous);
    },
    [saveDashboard],
  );

  const moveCard = useCallback(
    (card: DashboardCardKey, target: DashboardCardKey, before: boolean) => {
      reorderCards(moveDashboardCard(preferencesRef.current.order, card, target, before));
    },
    [reorderCards],
  );

  const toggleCard = useCallback(
    (card: DashboardCardKey) => {
      const previous = clonePreferences(preferencesRef.current);
      const showing = !previous.cards[card];
      const visibleCount = DASHBOARD_CARD_KEYS.filter((key) => previous.cards[key]).length;
      if (showing && visibleCount >= MAX_CARDS_ON_SCREEN) {
        setNotice(`Limite de ${MAX_CARDS_ON_SCREEN} blocos visíveis. Oculte um bloco antes de mostrar outro.`);
        return;
      }
      setNotice(null);
      const next = { ...previous, cards: { ...previous.cards, [card]: showing } };
      void saveDashboard(next, previous);
    },
    [saveDashboard],
  );

  const resizeCard = useCallback(
    (card: DashboardCardKey, cols: number, rows: number) => {
      const previous = clonePreferences(preferencesRef.current);
      const size = clampCardSize(card, { cols, rows });
      const current = previous.sizes[card];
      if (current.cols === size.cols && current.rows === size.rows) return;
      const next = { ...previous, sizes: { ...previous.sizes, [card]: size } };
      void saveDashboard(next, previous);
    },
    [saveDashboard],
  );

  const resetToDefault = useCallback(() => {
    const previous = clonePreferences(preferencesRef.current);
    setNotice(null);
    void saveDashboard(clonePreferences(DEFAULT_PREFERENCES), previous);
  }, [saveDashboard]);

  return {
    preferences,
    cards: preferences.cards,
    order: preferences.order,
    sizes: preferences.sizes,
    visibleCount: DASHBOARD_CARD_KEYS.filter((key) => preferences.cards[key]).length,
    loading,
    saving,
    error,
    notice,
    clearNotice: () => setNotice(null),
    moveCard,
    reorderCards,
    toggleCard,
    resizeCard,
    resetToDefault,
  };
}
