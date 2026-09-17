export type Availability =
  | "disponivel"
  | "parcial"
  | "nao_configurado"
  | "dados_insuficientes"
  | "sem_registros"
  | "nao_aplicavel"
  | "inconsistente";

export interface ApiErrorPayload {
  code: string;
  message: string;
  request_id?: string | null;
  details?: unknown;
}

export interface SessionUser {
  id: number;
  name: string;
  role: string;
  management_access: boolean;
  andon_access: boolean;
  operator_access: boolean;
  operator_sector?: string | null;
  operator_resources?: string[];
  operator_automatic_queue?: boolean;
}

export interface OperatorContext {
  sector: string;
  route: string;
  resources: string[];
  automatic_queue: boolean;
  fixed_resource?: boolean;
  station_profile_required?: boolean;
  has_setup?: boolean;
  workflow: "workbench" | "cutting" | "highlight";
}

export interface OperatorOperation extends Record<string, unknown> {
  id?: number;
  catalogo_operacao_id?: number;
  numero_operacao?: string;
  codigo?: string;
  descricao_operacao?: string;
  codigo_recurso?: string;
  recurso_nome?: string;
  produto_codigo?: string;
  produto_descricao?: string;
  quantidade?: number;
  quantidade_planejada?: number;
  quantidade_boa_registrada?: number;
  quantidade_refugo_registrada?: number;
  quantidade_atendida?: number;
  saldo_quantidade?: number;
  saldo_quantidade_boa?: number;
  visual_status?: "done" | "current" | "pending";
  visual_current?: boolean;
  pointable?: boolean;
  sector_compatible?: boolean;
  resource_compatible?: boolean;
  /** O posto aberto executa esta operação (setor + recurso compatíveis). */
  station_eligible?: boolean;
  /** O operador pode escolher esta etapa no roteiro. */
  selectable?: boolean;
  /** Etapa fora da atual: exige confirmação explícita antes de iniciar. */
  requires_confirmation?: boolean;
  /** Etapa atual do posto: apontável sem exceção. */
  actionable?: boolean;
  /** Wave 5: portão da primeira peça, calculado pelo backend. */
  primeira_peca?: FirstPieceGate;
  primeira_peca_id?: number | null;
  /** Wave 5: o backend já decidiu se Finalizar pode ser oferecido. */
  pode_finalizar?: boolean;
  /** Wave 6B: a primeira peça desta etapa ainda não foi aprovada — o Setup
   *  abre o checklist e o Finalizar é recusado até a aprovação. */
  exige_gate_primeira_peca?: boolean;
}

/**
 * Portão da primeira peça. A UI **não** recalcula nada disto: ela exibe
 * `message` e desabilita Finalizar quando `liberado` é falso.
 */
export interface FirstPieceGate {
  aplicavel: boolean;
  liberado: boolean;
  status: "PENDENTE" | "PRODUZIDA" | "CONFORME" | "RETRABALHO" | "REFUGO";
  peca_produzida: boolean;
  setup_obrigatorio: boolean;
  setup_registrado: boolean;
  inspecao_concluida: boolean;
  bloqueio_ativo: boolean;
  /** Wave 6B: setor com checklist estruturado (Dobra, Usinagem e Serra). O
   *  backend decide; a tela apenas abre o popup Setup/Qualidade no Iniciar. */
  gate_estruturado: boolean;
  code: string;
  message: string;
  pendencias: string[];
}

/** Checklist de cotas do produto, publicado junto com o portão (Wave 6B). */
export interface FirstPieceChecklist {
  produto: string;
  produto_descricao?: string | null;
  template: QualityTemplate | null;
  /** Verdadeiro quando o produto ainda não possui cotas cadastradas. */
  configuravel: boolean;
}

/** Estado completo do portão, como o endpoint do posto devolve. */
export interface FirstPieceState extends FirstPieceGate {
  op?: string;
  operation_id?: number | null;
  operation_number?: string | null;
  registro?: FirstPieceRecord | null;
  checklist?: FirstPieceChecklist | null;
}

export interface FirstPieceRecord {
  id: number;
  op: string;
  operacao?: string | null;
  status: string;
  resultado?: string | null;
  observacao?: string | null;
  setup_obrigatorio: boolean;
  setup_registrado_em?: string | null;
  peca_produzida_em?: string | null;
  peca_produzida_por?: string | null;
  inspecionada_em?: string | null;
  inspecionada_por?: string | null;
  bloqueio_ativo: boolean;
  bloqueio_ocorrencia?: string | null;
  liberada_em?: string | null;
  liberada_por_nome?: string | null;
  liberada_por_cracha?: string | null;
}

/** Desenho (PDF) da peça resolvido pelo backend na rede da engenharia. */
export interface OperatorDrawing {
  available: boolean;
  reason: string;
  op: string;
  produto: string;
  produto_descricao: string;
  message: string;
  filename?: string | null;
  modified_at?: string | null;
  size_bytes?: number | null;
  candidate_count: number;
  candidates: Array<{ filename: string; modified_at: string; size_bytes: number }>;
}

export interface OperatorCard extends Record<string, unknown> {
  id?: number;
  catalogo_operacao_id?: number;
  op?: string;
  operation?: string;
  numero_operacao?: string;
  product?: string;
  description?: string;
  qty?: number;
  good?: number;
  scrap?: number;
  attended?: number;
  balance?: number;
  status?: string;
  elapsed?: string;
  motivo_parada?: string;
  status_elapsed?: string;
  stopped_since?: string | null;
  last_updated_at?: string | null;
  virtual_queue?: boolean;
  rework_return?: boolean;
}

export interface QualityQueueItem {
  op: string;
  operacao: string;
  descricao: string;
  produto: string;
  recurso: string;
  recurso_nome: string;
  quantidade: number;
  inspecionadas: number;
  pendentes: number;
  data: string | null;
  inspecao_id: number | null;
  em_andamento: boolean;
}

export interface QualitySummary {
  aguardando: number;
  aprovadas: number;
  retrabalho: number;
  refugo: number;
}

export interface QualityQueue {
  sector: string;
  items: QualityQueueItem[];
  resumo: QualitySummary;
  recursos: string[];
  busca: { codigo: string; message: string } | null;
}

export interface QualityDimension {
  id: number | null;
  sequencia: number;
  descricao: string | null;
  padrao: string;
  unidade: string | null;
  // Wave 5.1 - a faixa de conformidade vem calculada do backend. A tela
  // apresenta os limites; ela nunca decide o status gravado.
  referencia: number | null;
  margem: number | null;
  limite_inferior: number | null;
  limite_superior: number | null;
  conformidade_automatica: boolean;
}

export interface QualityTemplate {
  id: number;
  produto: string;
  revisao: number;
  atualizado_por: string | null;
  atualizado_em: string | null;
  cotas: QualityDimension[];
}

export interface QualityDrawing {
  id: number;
  produto: string;
  filename: string;
  versao: number;
  size_bytes: number;
  enviado_em: string | null;
  enviado_por: string | null;
}

export interface QualityInspectedPiece {
  numero_peca: number;
  resultado: string;
  rnc: string | null;
  operador: string;
  registrada_em: string | null;
}

export interface QualityInspection {
  id: number;
  op: string;
  operacao: string;
  produto: string;
  produto_descricao: string | null;
  recurso: string;
  quantidade_total: number;
  pecas_registradas: number;
  peca_atual: number | null;
  ultima_peca: boolean;
  status: string;
  operador: string;
  template: QualityTemplate | null;
  template_editavel: boolean;
  desenho: QualityDrawing | null;
  pecas: QualityInspectedPiece[];
}

export interface QualityHistoryItem {
  peca_id: number;
  inspecao_id: number;
  data: string | null;
  op: string;
  operacao: string;
  produto: string;
  descricao: string | null;
  peca: string;
  numero_peca: number;
  recurso: string;
  operador: string;
  resultado: string;
  rnc: string | null;
  rnc_motivo: string | null;
}

export type StopClassification = "planejada" | "nao_planejada";

export interface StopReason extends Record<string, unknown> {
  codigo: string;
  nome: string;
  requer_comentario?: boolean;
  grupo_codigo?: string;
  /** Classificação central decidida no backend. */
  classificacao?: StopClassification;
  /** Token visual derivado da classificação: `warning` (amarela) ou `danger` (vermelha). */
  cor?: "warning" | "danger";
}

export interface MetricValue {
  value: number | null;
  availability: Availability;
  unit?: string | null;
  reason?: string | null;
}

export interface SectorSummary {
  setor: string;
  producao_boa: number;
  refugo: number;
  retrabalho: number;
  ops: number;
  tempo_producao_segundos: number;
  tempo_setup_segundos: number;
  tempo_parada_segundos: number;
  tempo_produtivo_segundos: number;
}

export interface TimeCompositionItem {
  label: string;
  seconds: number;
  percentage: number | null;
  source_field: string;
}

export interface SimulationSummary {
  enabled: boolean;
  reference_time: string;
  planned_quantity: number;
  actual_quantity: number;
  attainment_percentage: number | null;
  difference_quantity: number;
  time_bases: Record<string, number | null>;
  metrics: {
    availability: MetricValue;
    performance: MetricValue;
    ftt: MetricValue;
    oee: MetricValue;
    utilization: MetricValue;
    productivity: MetricValue;
    ae: MetricValue;
  };
  policy: "canonical_oee";
}

export interface InsightEvidence {
  source: string;
  kind: string;
  source_id?: string | null;
  sector?: string | null;
  resource?: string | null;
  op?: string | null;
  operation?: string | null;
  product?: string | null;
  reason?: string | null;
  occurred_at?: string | null;
  start?: string | null;
  end?: string | null;
  duration_seconds?: number | null;
  quantity?: number | null;
  details: Record<string, unknown>;
}

export interface ManagementException {
  id: string;
  type: string;
  severity: "alta" | "atencao" | "informativa";
  priority: number;
  entity_type: string;
  entity_id: string;
  title: string;
  summary: string;
  justification: string;
  period: Record<string, string | null>;
  sector?: string | null;
  resource?: string | null;
  op?: string | null;
  operation?: string | null;
  current_value?: number | null;
  reference_value?: number | null;
  deviation?: number | null;
  unit?: string | null;
  cause?: string | null;
  impact_value?: number | null;
  impact_unit?: string | null;
  evidence: InsightEvidence[];
}

export interface KpiExplanation {
  key: "oee" | "availability" | "performance" | "ftt";
  label: string;
  metric: MetricValue;
  period: Record<string, string | null>;
  components: Array<Record<string, unknown>>;
  largest_impact?: Record<string, unknown> | null;
  causes: Array<Record<string, unknown>>;
  resources: Array<Record<string, unknown>>;
  evidence: InsightEvidence[];
  calculation_policy: "backend_only";
  simulation_only: boolean;
  limitation?: string | null;
}

export interface ImpactRankingItem {
  rank: number;
  resource?: string;
  cause?: string;
  type?: string;
  criterion?: string;
  impact_value: number;
  impact_unit: string;
  evidence: InsightEvidence[];
}

export interface ManagementInsights {
  periodo: Record<string, string | null>;
  generated_at: string;
  exceptions: ManagementException[];
  exception_count: number;
  losses: ImpactRankingItem[];
  critical_resources: ImpactRankingItem[];
  kpi_explanations: Record<KpiExplanation["key"], KpiExplanation>;
  limitations: Array<{ code: string; message: string }>;
  policies: {
    calculation: "backend_only";
    priority: string;
    resource_ranking: string;
    thresholds: string;
  };
  availability: Availability;
  simulation_only: boolean;
}

export interface ManagementOverview {
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
  production_plan: MetricValue;
  kpis: {
    availability: MetricValue;
    performance: MetricValue;
    ftt: MetricValue;
    oee: MetricValue;
  };
  kpi_contract?: {
    source: string;
    unit: "percent_0_100";
    backend_rounding: "full_precision";
    presentation_rounding: "one_decimal";
  };
  kpi_time_bases: Record<string, number>;
  sectors: SectorSummary[];
  time_composition: {
    items: TimeCompositionItem[];
    total_seconds: number;
    availability: Availability;
  };
  audit: { open_issues: Array<Record<string, unknown>> };
  data_quality: Record<string, unknown>;
  insights: ManagementInsights;
  simulation?: SimulationSummary | null;
}
