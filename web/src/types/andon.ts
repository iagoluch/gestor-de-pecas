import type { Availability, MetricValue, StopClassification } from "./api";

export type AndonPhysicalState =
  | "fila"
  | "producao"
  | "parada"
  | "setup"
  | "retrabalho"
  | "atividade_sem_op"
  | "fora_turno"
  | "desconhecido";

/**
 * `sem_demanda` é leitura, não categoria física: fora de turno, sem hora extra
 * e sem ninguém trabalhando. O backend decide (ManufacturingRules) e entrega
 * pronto; `physical_category` preserva o estado persistido por trás dela.
 */
export type AndonState = AndonPhysicalState | "sem_demanda";

export interface AndonOperation {
  op?: string | null;
  operation?: string | number | null;
  operation_description?: string | null;
  product?: string | null;
  product_description?: string | null;
  good_quantity?: number | null;
  planned_quantity?: number | null;
  scrap_quantity?: number | null;
  rework_quantity?: number | null;
  operator?: string | null;
  started_at?: string | null;
}

export interface AndonResource {
  code: string;
  name: string;
  sector: string;
  order?: number | null;
  state: {
    category: AndonState;
    /** Estado físico persistido; `sem_demanda` é derivado dele, não o apaga. */
    physical_category?: AndonPhysicalState;
    label: string;
    display_label?: string | null;
    /** Classificação central da parada; `null` para estados produtivos. */
    stop_classification?: StopClassification | null;
    /** Cor derivada da classificação: `warning` (amarela) ou `danger` (vermelha). */
    color?: "warning" | "danger" | null;
    started_at?: string | null;
    duration_seconds?: number | null;
    reason?: string | null;
    activity_description?: string | null;
    status_code?: string | null;
    source?: string | null;
  };
  panel?: "Corte" | "Caldeiraria" | "Solda" | "Pintura" | string;
  group?: string | null;
  operation?: AndonOperation | null;
  active_operations: number;
  metrics: {
    oee: MetricValue;
    availability: MetricValue;
    performance: MetricValue;
    ftt: MetricValue;
  };
}

export interface AndonSnapshot {
  period: Record<string, string | null>;
  generated_at: string;
  clock: { now: string; running: boolean };
  current_shift: {
    value?: string | null;
    availability: Availability;
    reason?: string | null;
  };
  summary: {
    resources: number;
    production: number;
    downtime: number;
    setup: number;
    rework: number;
    queue: number;
    activity_without_op: number;
    out_of_shift: number;
    no_demand: number;
    unknown: number;
    oee: MetricValue;
    availability: MetricValue;
    performance: MetricValue;
    ftt: MetricValue;
  };
  sectors: Array<{
    name: string;
    resource_count?: number;
    groups?: Array<{ name: string; resources: AndonResource[] }>;
    resources: AndonResource[];
  }>;
  resource_count: number;
  simulation_only: boolean;
  availability: Availability;
  sources: Record<string, string>;
}
