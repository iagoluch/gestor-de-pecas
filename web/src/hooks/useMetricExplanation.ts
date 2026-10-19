import { toQuery } from "../filters/FilterContext";
import type { OverviewFilters } from "../types/explanation";
import type { ExplanationResponse } from "../types/valueExplanation";
import { useApiQuery } from "./useApiQuery";

/**
 * Busca a explicação de uma métrica com os mesmos filtros da Visão Geral
 * (`toQuery`, o mesmo serializador do `FilterContext`). O cancelamento ao
 * trocar de métrica ou fechar o painel vem do `useApiQuery`. A resposta é a
 * forma de tempo (`ExplanationTree`) ou a de valor (`kind: "value"`).
 */
export function useMetricExplanation(metric: string | null, filters: OverviewFilters) {
  const path = metric ? `/api/v1/management/explicacao?metric=${encodeURIComponent(metric)}&${toQuery(filters)}` : null;
  return useApiQuery<ExplanationResponse>(path, { ignoreLiveTick: true });
}
