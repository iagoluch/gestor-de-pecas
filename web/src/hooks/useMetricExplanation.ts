import { toQuery } from "../filters/FilterContext";
import type { ExplanationTree, OverviewFilters } from "../types/explanation";
import { useApiQuery } from "./useApiQuery";

/**
 * Busca a explicação de uma métrica com os mesmos filtros da Visão Geral
 * (`toQuery`, o mesmo serializador do `FilterContext`). O cancelamento ao
 * trocar de métrica ou fechar o painel vem do `useApiQuery`.
 */
export function useMetricExplanation(metric: string | null, filters: OverviewFilters) {
  const path = metric ? `/api/v1/management/explicacao?metric=${encodeURIComponent(metric)}&${toQuery(filters)}` : null;
  return useApiQuery<ExplanationTree>(path, { ignoreLiveTick: true });
}
