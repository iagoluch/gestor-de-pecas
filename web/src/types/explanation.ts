import type { ManagementFilters } from "../filters/FilterContext";
import type { ManagementOverview, TimeCompositionItem } from "./api";

/** Mesmos filtros da Visão Geral (`/management/overview`). */
export type OverviewFilters = ManagementFilters;

/** Espelha `ExplanationNode` de `backend/api/schemas/explanation.py`. */
export interface ExplanationNode {
  kind: "sector" | "resource" | "stretch";
  label: string;
  seconds: number;
  children: ExplanationNode[];
  detail: ExplanationStretchDetail | null;
  truncated: boolean;
}

export interface ExplanationStretchDetail {
  start: string | null;
  end: string | null;
  who: string | null;
  origin: string | null;
  record_id: string | null;
  motivo?: string;
  rule?: string;
}

export interface ExplanationSibling {
  metric: string;
  label: string;
  seconds: number;
}

export interface ExplanationExcluded {
  label: string;
  seconds: number;
  reason: string;
}

export interface ExplanationReconciliation {
  ok: boolean;
  sum_seconds: number;
  diff_seconds: number;
}

/** Espelha `ExplanationResponse` (`GET /management/explicacao`). */
export interface ExplanationTree {
  metric: string;
  label: string;
  total_seconds: number;
  average_seconds: number | null;
  resource_count: number;
  day_count: number;
  parent_total_seconds: number;
  siblings: ExplanationSibling[];
  reason: string;
  rule: string;
  children: ExplanationNode[];
  excluded: ExplanationExcluded[];
  reconciliation: ExplanationReconciliation;
  calculated_at: string;
  truncated: boolean;
  notes: string[];
}

/**
 * Composição do tempo como o backend serve hoje: o item ganhou `metric` e o
 * bloco ganhou `day_count`/`average_note`. Fica aqui (e não em `api.ts`) para
 * não misturar com outras edições do tipo da Visão Geral.
 */
export type ExplainableTimeItem = TimeCompositionItem & { metric?: string | null };
export type ExplainableTimeComposition = Omit<ManagementOverview["time_composition"], "items"> & {
  items: ExplainableTimeItem[];
  day_count?: number;
  average_note?: string | null;
};

export function explainableComposition(composition: ManagementOverview["time_composition"]): ExplainableTimeComposition {
  return composition as ExplainableTimeComposition;
}
