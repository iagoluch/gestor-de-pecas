import type { DashboardCardKey, DashboardCardSize } from "../types/api";

/**
 * Catálogo único dos blocos da Visão Geral no frontend. Espelha
 * ``app/core/preferences.py``: mesmas chaves, mesmos padrões e mesmos tetos.
 * O backend é a fonte final (normaliza tudo que chega); aqui só evitamos
 * mandar algo fora da faixa.
 */
export const DASHBOARD_CARD_KEYS = [
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
  "chamadas",
  "metas",
  "andon",
] as const satisfies readonly DashboardCardKey[];

export const MAX_CARD_COLS = 6;
export const MAX_CARD_ROWS = 4;
export const MAX_CARDS_ON_SCREEN = 14;
export const DASHBOARD_GRID_COLUMNS = 6;
/** Altura mínima de uma linha da grade; o conteúdo pode crescer além dela. */
export const DASHBOARD_ROW_HEIGHT = 84;

/** Blocos que já existiam: entram visíveis para quem nunca personalizou. */
export const DEFAULT_VISIBLE_CARDS: readonly DashboardCardKey[] = DASHBOARD_CARD_KEYS.filter(
  (key) => key !== "chamadas" && key !== "metas" && key !== "andon",
);

export const DEFAULT_DASHBOARD_SIZES: Record<DashboardCardKey, DashboardCardSize> = {
  producao_boa: { cols: 2, rows: 1 },
  oee: { cols: 1, rows: 1 },
  disponibilidade: { cols: 1, rows: 1 },
  performance: { cols: 1, rows: 1 },
  ftt: { cols: 1, rows: 1 },
  simulation: { cols: 6, rows: 2 },
  planned_vs_actual: { cols: 3, rows: 2 },
  exceptions: { cols: 3, rows: 2 },
  time_composition: { cols: 2, rows: 2 },
  top_losses: { cols: 2, rows: 2 },
  live_events: { cols: 2, rows: 2 },
  sectors_table: { cols: 6, rows: 3 },
  top_resources: { cols: 3, rows: 2 },
  audit_issues: { cols: 3, rows: 2 },
  chamadas: { cols: 2, rows: 2 },
  metas: { cols: 2, rows: 2 },
  andon: { cols: 2, rows: 2 },
};

export const DASHBOARD_CARD_LIMITS: Record<DashboardCardKey, { minCols: number; minRows: number }> = {
  producao_boa: { minCols: 1, minRows: 1 },
  oee: { minCols: 1, minRows: 1 },
  disponibilidade: { minCols: 1, minRows: 1 },
  performance: { minCols: 1, minRows: 1 },
  ftt: { minCols: 1, minRows: 1 },
  simulation: { minCols: 3, minRows: 1 },
  planned_vs_actual: { minCols: 2, minRows: 1 },
  exceptions: { minCols: 2, minRows: 1 },
  time_composition: { minCols: 2, minRows: 1 },
  top_losses: { minCols: 2, minRows: 1 },
  live_events: { minCols: 2, minRows: 1 },
  sectors_table: { minCols: 4, minRows: 2 },
  top_resources: { minCols: 2, minRows: 1 },
  audit_issues: { minCols: 2, minRows: 1 },
  chamadas: { minCols: 2, minRows: 1 },
  metas: { minCols: 2, minRows: 1 },
  andon: { minCols: 2, minRows: 1 },
};

export const DASHBOARD_CARD_COPY: Record<DashboardCardKey, { label: string; description: string }> = {
  producao_boa: { label: "Produção boa", description: "Total de peças boas no período" },
  oee: { label: "OEE", description: "Ineficiência global efetiva" },
  disponibilidade: { label: "Disponibilidade", description: "Tempo efetivo vs. tempo planejado" },
  performance: { label: "Performance", description: "Velocidade real vs. velocidade esperada" },
  ftt: { label: "FTT / Qualidade", description: "Peças boas na primeira tentativa" },
  simulation: { label: "Indicadores de simulação", description: "Planejado, atingimento, utilização, produtividade e AE" },
  planned_vs_actual: { label: "Planejado × realizado", description: "Acumulado do período e resumo" },
  exceptions: { label: "O que precisa de atenção", description: "Exceções operacionais priorizadas" },
  time_composition: { label: "Composição do tempo", description: "Para onde o tempo foi" },
  top_losses: { label: "Maiores perdas", description: "Causas com maior impacto" },
  live_events: { label: "Agora na fábrica", description: "Mudanças de estado dos recursos" },
  sectors_table: { label: "Setores — leitura rápida", description: "Produção, OEE e tempos por setor" },
  top_resources: { label: "Recursos com maior impacto", description: "Ranking por impacto" },
  audit_issues: { label: "Inconsistências de dados", description: "Alertas de auditoria abertos" },
  chamadas: { label: "Chamadas da gestão", description: "Últimas chamadas do operador e da gestão" },
  metas: { label: "Metas e atingimento", description: "Planejado, realizado e atingimento do período" },
  andon: { label: "Alertas ao vivo", description: "Estado atual dos recursos no Andon" },
};

export function clampCardSize(key: DashboardCardKey, size: Partial<DashboardCardSize> | null | undefined): DashboardCardSize {
  const limits = DASHBOARD_CARD_LIMITS[key];
  const fallback = DEFAULT_DASHBOARD_SIZES[key];
  const clamp = (value: unknown, min: number, max: number, def: number) => {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return def;
    return Math.min(max, Math.max(min, Math.round(parsed)));
  };
  return {
    cols: clamp(size?.cols, limits.minCols, MAX_CARD_COLS, fallback.cols),
    rows: clamp(size?.rows, limits.minRows, MAX_CARD_ROWS, fallback.rows),
  };
}

export function cloneSizes(sizes: Record<DashboardCardKey, DashboardCardSize>): Record<DashboardCardKey, DashboardCardSize> {
  return Object.fromEntries(DASHBOARD_CARD_KEYS.map((key) => [key, { ...sizes[key] }])) as Record<DashboardCardKey, DashboardCardSize>;
}
