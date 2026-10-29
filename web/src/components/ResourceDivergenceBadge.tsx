import { displayName } from "../utils/format";

/**
 * Apontamento feito em recurso diferente do roteiro. A tela apenas projeta o
 * que o backend registrou (`recurso_divergente`); não compara nomes por conta própria.
 */
export function ResourceDivergenceBadge({ planned, actual }: { planned?: string | null; actual?: string | null }) {
  const from = String(planned ?? "").trim();
  const to = String(actual ?? "").trim();
  const text = from && to ? `Divergente: previsto ${displayName(from)} → real ${displayName(to)}` : "Divergente";
  return <span className="status-badge status-badge--warning" title="Apontado em recurso diferente do roteiro">{text}</span>;
}

type DivergenceEvent = {
  recurso_divergente?: boolean | null;
  recurso_apontado?: string | null;
  recurso_roteiro_codigo?: string | null;
  recurso_roteiro_nome?: string | null;
};

/** Primeiro evento divergente do apontamento, ou null; zero/ausente não vira selo. */
export function divergentEvent(events: DivergenceEvent[] | null | undefined) {
  return (events ?? []).find((event) => event.recurso_divergente === true) ?? null;
}

export function routeResourceLabel(event: DivergenceEvent) {
  const code = String(event.recurso_roteiro_codigo ?? "").trim();
  const name = String(event.recurso_roteiro_nome ?? "").trim();
  return code && name && name !== code ? `${code} (${name})` : code || name;
}
