import type { ExplanationTree } from "./explanation";

/**
 * Explicação de um número que não é tempo (`kind: "value"`). Espelha o contrato
 * em `docs/superpowers/specs/2026-10-19-explicacao-valor-contrato.md`. O mesmo
 * formato é usado pelo servidor (`GET /management/explicacao?metric=qtd.*`) e
 * pelas somas montadas no navegador (`pages/production/productionExplanations.ts`).
 */
export type ValueUnit = "pcs" | "pct" | "brl" | "count" | "hours" | "text";

export type ValueNodeKind = "sector" | "resource" | "op" | "event" | "part" | "input" | "group";

export type ValueDetail = Record<string, string | number | boolean | null>;

export interface ValueNode {
  kind: ValueNodeKind;
  label: string;
  value: number | string | null;
  children: ValueNode[];
  detail: ValueDetail | null;
  truncated: boolean;
}

export interface ValueExcluded {
  label: string;
  value: number | string | null;
  reason: string;
}

export interface ValueReconciliation {
  ok: boolean;
  sum: number | null;
  diff: number | null;
}

export interface ValueExplanation {
  kind: "value";
  metric: string;
  label: string;
  unit: ValueUnit;
  value: number | string | null;
  reason: string;
  rule: string;
  children: ValueNode[];
  excluded: ValueExcluded[];
  reconciliation: ValueReconciliation;
  calculated_at: string;
  truncated: boolean;
  notes: string[];
}

/** O endpoint devolve a forma de tempo (sem `kind`) ou a de valor. */
export type ExplanationResponse = ExplanationTree | ValueExplanation;

export function isValueExplanation(response: ExplanationResponse | null | undefined): response is ValueExplanation {
  return Boolean(response) && (response as { kind?: unknown }).kind === "value";
}
