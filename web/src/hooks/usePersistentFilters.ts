import { useCallback, useMemo, useState } from "react";

/**
 * Filtros locais de uma tela de cadastro (Pausas, Crachás).
 *
 * A seleção sobrevive à navegação dentro da sessão — sair da tela e voltar não
 * descarta o recorte —, porém não se transforma em estado global nem gera
 * consulta nova: a lista já vem completa do backend e o recorte é aplicado em
 * memória.
 */
export function usePersistentFilters<T extends Record<string, string>>(storageKey: string, initial: T) {
  const [values, setValues] = useState<T>(() => restore(storageKey, initial));

  const persist = useCallback((next: T) => {
    setValues(next);
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      // Sessão sem armazenamento disponível: o filtro continua válido na tela.
    }
  }, [storageKey]);

  const set = useCallback(<K extends keyof T>(key: K, value: T[K]) => {
    persist({ ...values, [key]: value });
  }, [persist, values]);

  const reset = useCallback(() => persist({ ...initial }), [initial, persist]);

  const active = useMemo(
    () => Object.keys(initial).some((key) => (values[key] ?? "") !== (initial[key] ?? "")),
    [initial, values],
  );

  return { values, set, reset, active };
}

function restore<T extends Record<string, string>>(storageKey: string, initial: T): T {
  try {
    const raw = window.sessionStorage.getItem(storageKey);
    if (!raw) return { ...initial };
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const restored = { ...initial };
    Object.keys(initial).forEach((key) => {
      const value = parsed[key];
      if (typeof value === "string") restored[key as keyof T] = value as T[keyof T];
    });
    return restored;
  } catch {
    return { ...initial };
  }
}
