import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";

/**
 * Relógio de referência oficial da aplicação.
 *
 * O backend é a única autoridade sobre "agora". Em modo de simulação ele publica
 * `simulation.reference_time` em `/api/v1/system/capabilities`, e é essa a
 * referência que a interface precisa usar para montar períodos padrão — caso
 * contrário o relógio local do navegador produz um início posterior ao fim que o
 * backend admite, e a consulta é recusada com `invalid_period`.
 *
 * Em ambiente normal a simulação está desligada, `reference` é `null` e a
 * interface volta a usar o relógio real.
 */

type Capabilities = {
  simulation?: {
    enabled?: boolean;
    reference_time?: string | null;
  };
};

export interface ReferenceClock {
  /** Referência oficial quando a simulação está ativa; `null` em ambiente normal. */
  reference: Date | null;
  /** `false` enquanto as capabilities não responderam. */
  ready: boolean;
}

// Sem provider (renderização isolada em teste) a interface opera com o relógio
// real, que é exatamente o comportamento de ambiente normal.
const ReferenceClockContext = createContext<ReferenceClock>({ reference: null, ready: true });

export function ReferenceClockProvider({ children }: PropsWithChildren) {
  const [state, setState] = useState<ReferenceClock>({ reference: null, ready: false });

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/system/capabilities", { credentials: "include", signal: controller.signal })
      .then((response) => (response.ok ? (response.json() as Promise<Capabilities>) : null))
      .then((payload) => {
        const raw = payload?.simulation?.enabled ? payload.simulation.reference_time : null;
        const parsed = raw ? new Date(raw) : null;
        setState({
          reference: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null,
          ready: true,
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setState({ reference: null, ready: true });
      });
    return () => controller.abort();
  }, []);

  return <ReferenceClockContext.Provider value={state}>{children}</ReferenceClockContext.Provider>;
}

export function useReferenceClock() {
  return useContext(ReferenceClockContext);
}

/** Instante que a interface deve tratar como "agora". */
export function referenceNow(reference: Date | null) {
  return reference ? new Date(reference.getTime()) : new Date();
}

/** Data local no formato `YYYY-MM-DD`, sem deslocar o dia por fuso. */
export function localDate(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}
