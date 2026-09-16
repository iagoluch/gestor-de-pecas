import type { Availability, MetricValue, SectorSummary, SimulationSummary } from "./api";

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  pages: number;
}

export interface ResourceOperation {
  apontamento_id?: number | null;
  recurso?: string | null;
  setor?: string | null;
  op?: string | null;
  operacao?: string | number | null;
  produto?: string | null;
  quantidade_planejada?: number | null;
  quantidade_boa?: number | null;
  refugo?: number | null;
  retrabalho?: number | null;
  operador_inicio?: string | null;
  status?: string | null;
  inicio?: string | null;
}

export interface ResourceRow {
  estado_recurso_id?: number | null;
  recurso: string;
  recurso_nome?: string | null;
  setor?: string | null;
  categoria?: string | null;
  codigo_status?: string | null;
  motivo?: string | null;
  causa_raiz?: string | null;
  inicio?: string | null;
  duracao_segundos?: number | null;
  planejado?: boolean | null;
  automatico?: boolean;
  tipo_interrupcao?: string | null;
  ops_ativas: ResourceOperation[];
  quantidade_ops_ativas: number;
  fonte?: string;
}

export interface OperationsOverview {
  periodo: Record<string, string | null>;
  agora: string;
  resources: ResourceRow[];
  summary?: {
    resources: number;
    active_operations: number;
    by_category: Record<string, number>;
  };
  availability?: Availability;
}

export interface OrderRow {
  apontamento_id?: number | null;
  op?: string | null;
  produto?: string | null;
  descricao?: string | null;
  operacao_atual?: string | number | null;
  descricao_operacao?: string | null;
  sequencia?: string | number | null;
  setor?: string | null;
  recurso_planejado?: string | null;
  recurso_real?: string | null;
  prioridade?: string | number | null;
  inicio_planejado?: string | null;
  fim_planejado?: string | null;
  prazo_entrega?: string | null;
  inicio_real?: string | null;
  fim_real?: string | null;
  operador_inicio?: string | null;
  operador_fim?: string | null;
  quantidade_planejada?: number | null;
  quantidade_boa: number;
  refugo: number;
  retrabalho: number;
  quantidade_atendida?: number;
  saldo_quantidade?: number | null;
  progresso_percentual?: number | null;
  status?: string | null;
  proxima_operacao?: string | number | null;
  fonte?: string;
}

export interface PagedOrders {
  periodo: Record<string, string | null>;
  availability: Availability;
  items: OrderRow[];
  page: PageMeta;
}

export interface IssueRow {
  id?: number | null;
  type?: string;
  tipo?: string;
  severity?: string;
  severidade?: string;
  message?: string;
  mensagem?: string;
  op?: string | null;
  operation?: string | number | null;
  resource?: string | null;
  sector?: string | null;
  start?: string | null;
  end?: string | null;
  seconds?: number | null;
  source?: string | null;
}

export interface AuditResponse {
  periodo: Record<string, string | null>;
  issues: IssueRow[];
  count: number;
  by_severity: Record<string, number>;
  records_analyzed: number;
  resource_states_analyzed: number;
  rateio_sessions_analyzed: number;
  physical_state_source: string;
  reliability_percentage: number | null;
  reliability_reason: string;
  page?: PageMeta;
}

export interface SegmentRow {
  estado_recurso_id?: number | null;
  evento_id?: number | null;
  apontamento_id?: number | null;
  op?: string | null;
  operacao?: string | number | null;
  produto?: string | null;
  setor?: string | null;
  recurso?: string | null;
  inicio?: string | null;
  fim?: string | null;
  segundos?: number;
  motivo?: string | null;
  programada?: boolean | null;
  automatica?: boolean;
  tipo_setup?: string | null;
  fonte?: string;
}

export interface TraceOperation {
  apontamento_id?: number | null;
  operacao?: string | number | null;
  descricao_operacao?: string | null;
  produto?: string | null;
  recurso_previsto?: string | null;
  recurso_real?: string | null;
  setor?: string | null;
  status?: string | null;
  inicio?: string | null;
  fim?: string | null;
  quantidade_boa: number;
  refugo: number;
  retrabalho: number;
  lote?: string | null;
}

export interface TimelineEvent {
  timestamp?: string | null;
  type?: string | null;
  status?: string | null;
  reason?: string | null;
  operator?: string | null;
  resource?: string | null;
  operation?: string | number | null;
  source?: string | null;
  record_id?: number | null;
  appointment_id?: number | null;
  quantity?: number | null;
}

export interface TraceabilityResponse {
  op: string;
  operations: TraceOperation[];
  quantity_events: Array<Record<string, unknown>>;
  cutting_nestings: NestingRow[];
  physical_states: Array<Record<string, unknown>>;
  rateio_sessions: Array<Record<string, unknown>>;
  operator_participations: Array<Record<string, unknown>>;
  legacy_movements: Array<Record<string, unknown>>;
  timeline: TimelineEvent[];
  source_refs: Record<string, Array<number | string>>;
}

export interface PagedNestings {
  periodo: Record<string, string | null>;
  items: NestingRow[];
  count: number;
  page: PageMeta;
  availability: Availability;
  time_policy: { total_field: string; filtered_period_field: string; reason: string };
}

export interface RankedSeconds {
  motivo?: string;
  recurso?: string;
  seconds?: number;
  segundos?: number;
}

export interface SegmentSummary {
  periodo: Record<string, string | null>;
  count: number;
  total_seconds: number;
  raw_attributed_seconds: number;
  overlap_removed_seconds: number;
  items: SegmentRow[];
  by_reason: RankedSeconds[];
  by_resource: RankedSeconds[];
  kind: string;
}

export interface TimeBreakdown {
  periodo: Record<string, string | null>;
  totals: Record<string, number>;
  physical_seconds: number;
  raw_attributed_timeline_seconds: number;
  overlap_removed_seconds: number;
  overlap_seconds: number;
  conflicting_state_seconds: number;
  conflicting_sector_seconds: number;
  by_sector: Array<Record<string, string | number>>;
  by_resource: Array<Record<string, string | number>>;
  availability: Availability;
  reason: string;
  simulation?: SimulationSummary | null;
}

export interface QualityResponse {
  periodo: Record<string, string | null>;
  totals: { boa: number; refugo: number; retrabalho: number };
  by_sector: Array<{ setor: string; boa: number; refugo: number; retrabalho: number }>;
  by_product: Array<{ produto: string; boa: number; refugo: number; retrabalho: number }>;
  scrap_reasons: Array<Record<string, string | number>>;
  rework_reasons: Array<Record<string, string | number>>;
  ftt: MetricValue;
  availability: Availability;
  reason: string;
}

/**
 * Histórico do portão Setup/Qualidade (Wave 6B). É a mesma primeira peça que o
 * posto registra: a gestão apenas lê, sem recalcular nada.
 */
export interface FirstPieceHistoryRow {
  id: number;
  codigo_op: string;
  numero_operacao?: string | null;
  tipo_setor?: string | null;
  codigo_recurso?: string | null;
  recurso_apontado?: string | null;
  produto_codigo?: string | null;
  produto_descricao?: string | null;
  status: string;
  resultado?: string | null;
  /** Resumo das cotas medidas no checklist, como o posto registrou. */
  observacao?: string | null;
  setup_obrigatorio?: boolean;
  setup_registrado_em?: string | null;
  peca_produzida_em?: string | null;
  inspecionada_em?: string | null;
  inspecionada_por?: string | null;
  bloqueio_ativo?: boolean;
  liberada_por_nome?: string | null;
}

export interface FirstPieceAuthorizationRow {
  id: number;
  codigo_op: string;
  numero_operacao?: string | null;
  tipo_setor?: string | null;
  ocorrencia: string;
  cracha: string;
  autorizado_por_nome?: string | null;
  decisao: string;
  motivo_recusa?: string | null;
  operador?: string | null;
  data_hora?: string | null;
}

export interface FirstPieceHistoryResponse {
  items: FirstPieceHistoryRow[];
  count: number;
  blocked: number;
  summary: Array<{ status: string; total: number; bloqueadas: number }>;
  authorizations: FirstPieceAuthorizationRow[];
}

export interface StandardRow {
  apontamento_id?: number | null;
  op?: string | null;
  operacao?: string | number | null;
  produto?: string | null;
  setor?: string | null;
  recurso_previsto?: string | null;
  recurso_real?: string | null;
  quantidade_boa: number;
  tempo_padrao_unitario_segundos?: number | null;
  tempo_padrao_estimado_segundos?: number | null;
  tempo_producao_real_segundos?: number | null;
  fonte_tempo_producao?: string;
  tempo_real_por_peca_segundos?: number | null;
  desvio_segundos?: number | null;
  desvio_percentual?: number | null;
}

export interface NestingRow {
  apontamento_id?: number | null;
  plano_hash?: string;
  tarefa?: string;
  programa?: string;
  nesting?: number;
  maquina?: string;
  material?: string | null;
  espessura?: number | null;
  inicio?: string | null;
  fim?: string | null;
  previsto_segundos?: number | null;
  real_segundos?: number | null;
  real_periodo_segundos?: number | null;
  desvio_segundos?: number | null;
  desvio_percentual?: number | null;
  status?: string;
  operador_inicio?: string | null;
  operador_fim?: string | null;
  ops_relacionadas?: string[];
}

export interface ProductionResponse {
  periodo: Record<string, string | null>;
  production: {
    good: number;
    scrap: number;
    rework: number;
    ops: number;
    resources: number;
    availability: Availability;
    reason?: string | null;
    source: string;
  };
  sectors: SectorSummary[];
  quality: QualityResponse;
}
