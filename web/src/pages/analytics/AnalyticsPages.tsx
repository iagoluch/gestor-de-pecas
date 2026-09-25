import { useState } from "react";
import { Link } from "react-router-dom";
import { BarList } from "../../components/BarList";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { Availability, MetricValue } from "../../types/api";
import type {
  FirstPieceHistoryResponse,
  QualityResponse,
  SegmentSummary,
  StandardRow,
  TimeBreakdown,
} from "../../types/management";
import {
  availabilityLabel,
  formatDateTime,
  formatDuration,
  formatHours,
  formatNumber,
  formatPercent,
  formatSignedDuration,
  humanize,
} from "../../utils/format";

interface OeeResponse {
  oee: { value: number | null; availability: string; reason: string };
  components: {
    oee?: MetricValue;
    availability?: MetricValue;
    performance?: MetricValue;
    ftt?: MetricValue;
  };
  evolution?: {
    points: Array<{
      at: string;
      period_start?: string;
      period_end?: string;
      value: number;
      unit?: string;
      components?: {
        oee?: MetricValue;
        availability?: MetricValue;
        performance?: MetricValue;
        ftt?: MetricValue;
      };
    }>;
    availability: string;
    reason: string | null;
    bucket_days?: number;
    total_buckets?: number;
    available_points?: number;
    missing_points?: number;
  };
  availability: string;
  reason: string;
  extended_metrics?: {
    utilization?: MetricValue;
    productivity?: MetricValue;
    ae?: MetricValue;
  };
  losses_breakdown?: {
    fora_de_turno_segundos?: number | null;
    parada_planejada_segundos?: number | null;
    parada_nao_planejada_segundos?: number | null;
    ritmo_segundos?: number | null;
    refugo_quantidade?: number | null;
    retrabalho_quantidade?: number | null;
  };
}

interface StandardResponse {
  periodo: Record<string, string | null>;
  items: StandardRow[];
}

interface ChronoGroup {
  produto: string;
  operacao: string;
  recurso: string;
  amostras: number;
  media_segundos_por_peca: number;
  mediana_segundos_por_peca: number;
  minimo_segundos_por_peca: number;
  maximo_segundos_por_peca: number;
  desvio_padrao_segundos_por_peca: number;
}

interface ChronoResponse {
  periodo: Record<string, string | null>;
  groups: ChronoGroup[];
}

interface CapacityItem {
  codigo?: string;
  nome?: string;
  recurso?: string;
  tipo_setor?: string;
  setor?: string;
  capacidade_segundos?: number | null;
  capacidade_unidade?: string | null;
  carga_segundos?: number | null;
  capacidade_restante_segundos?: number | null;
  utilizacao_percentual?: number | null;
  calendario_codigo?: string | null;
  calendario_reason?: string | null;
  fila?: number | null;
}

interface CapacityResponse {
  items: CapacityItem[];
  unidade?: string;
  availability: "disponivel" | "parcial" | "nao_configurado" | "dados_insuficientes" | "sem_registros";
  reason: string;
  recursos?: number;
  recursos_com_calendario?: number;
  recursos_sem_calendario?: number;
  total_capacity_seconds?: number | null;
  total_load_seconds?: number | null;
  total_remaining_seconds?: number | null;
  utilizacao_percentual?: number | null;
  bottleneck_resource?: string | null;
  bottleneck_utilizacao_percentual?: number | null;
}

interface ReliabilityResponse {
  periodo: Record<string, string | null>;
  mtbf_segundos: number | null;
  mttr_segundos: number | null;
  falhas: number;
  reparos_concluidos: number;
  tempo_operacional_segundos: number;
  tempo_reparo_segundos: number;
  por_recurso: Array<{ recurso: string; falhas: number; tempo_reparo_segundos: number; mttr_segundos: number | null }>;
  motivos: Array<{ motivo: string; quantidade: number }>;
  taxonomia: string;
  availability: "disponivel" | "parcial" | "nao_configurado" | "dados_insuficientes" | "sem_registros";
  reason: string;
}

function LoadingPage({ title, subtitle }: { title: string; subtitle: string }) {
  return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><LoadingState /></PageFrame>;
}

/** Traduz um componente do OEE em perda percentual — a leitura que o gestor usa
 *  para decidir onde agir. A fórmula continua sendo do backend; aqui só se lê
 *  o quanto falta para 100%. */
function lossLabel(component: MetricValue | undefined) {
  if (!component || component.value === null || component.value === undefined) {
    return component?.reason ?? "Sem dado suficiente no período.";
  }
  const loss = Math.max(0, 100 - component.value);
  return loss < 0.05 ? "Sem perda registrada no período." : `${formatNumber(loss, 1)} p.p. de perda no período.`;
}

function metric(metric: MetricValue | undefined) {
  if (!metric || metric.value === null) return metric ? availabilityLabel[metric.availability] : "Dados insuficientes";
  return `${formatNumber(metric.value, 1)}${metric.unit ?? ""}`;
}

// A ausência do próprio indicador é "dados insuficientes": sem este padrão o
// cartão herdaria o estado "disponivel" e exibiria a frase de indisponibilidade
// com a tipografia de número (grande, escura e truncada por reticências).
function metricState(metric: MetricValue | undefined): Availability {
  return metric?.availability ?? "dados_insuficientes";
}

function evolutionDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}

function evolutionFullDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("pt-BR");
}

function evolutionPeriod(point: NonNullable<OeeResponse["evolution"]>["points"][number]) {
  const start = evolutionFullDate(point.period_start ?? point.at);
  const end = evolutionFullDate(point.period_end ?? point.at);
  return start === end ? start : `${start} a ${end}`;
}

function evolutionMetric(value: MetricValue | undefined) {
  return value?.value === null || value?.value === undefined
    ? "Não disponível"
    : formatPercent(value.value);
}

function OeeEvolutionChart({ evolution }: { evolution: NonNullable<OeeResponse["evolution"]> }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const points = evolution.points;
  const width = 680;
  const height = 210;
  const margin = { top: 20, right: 18, bottom: 34, left: 45 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const values = points.map((point) => point.value);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  let yMin = Math.max(0, Math.floor((minimum - 5) / 10) * 10);
  let yMax = Math.ceil((maximum + 5) / 10) * 10;
  if (yMax <= yMin) yMax = yMin + 10;
  const x = (index: number) => margin.left + (index / Math.max(1, points.length - 1)) * plotWidth;
  const y = (value: number) => margin.top + ((yMax - value) / (yMax - yMin)) * plotHeight;
  const line = points.map((point, index) => `${x(index)},${y(point.value)}`).join(" ");
  const yTicks = [yMax, (yMax + yMin) / 2, yMin];
  const labelStep = Math.max(1, Math.ceil((points.length - 1) / 5));
  const visibleLabels = new Set(
    points.map((_point, index) => index).filter((index) => index % labelStep === 0 || index === points.length - 1),
  );
  const latest = points[points.length - 1];
  const activePoint = activeIndex === null ? null : points[activeIndex];
  const tooltipWidth = 420;
  const tooltipHeight = 58;
  const tooltipX = activeIndex === null
    ? 0
    : Math.min(
      width - margin.right - tooltipWidth,
      Math.max(margin.left, x(activeIndex) - tooltipWidth / 2),
    );
  const tooltipY = activePoint && y(activePoint.value) - tooltipHeight - 12 >= margin.top
    ? y(activePoint.value) - tooltipHeight - 12
    : activePoint
      ? y(activePoint.value) + 12
      : 0;
  const pointLabel = (point: typeof latest) => {
    const components = point.components;
    return [
      evolutionPeriod(point),
      `OEE ${formatPercent(components?.oee?.value ?? point.value)}`,
      `Disponibilidade ${evolutionMetric(components?.availability)}`,
      `Performance ${evolutionMetric(components?.performance)}`,
      `FTT/Qualidade ${evolutionMetric(components?.ftt)}`,
    ].join(". ");
  };

  return (
    <div className="oee-evolution">
      <div className="oee-evolution__summary">
        <span><i aria-hidden="true" /> OEE canônico</span>
        <strong>Último ponto: {formatPercent(latest.value)}</strong>
      </div>
      <svg
        className="oee-evolution__chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Evolução do OEE com ${points.length} pontos; último valor ${formatPercent(latest.value)}.`}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line x1={margin.left} y1={y(tick)} x2={width - margin.right} y2={y(tick)} className="oee-evolution__grid" />
            <text x={margin.left - 8} y={y(tick) + 4} textAnchor="end" className="oee-evolution__axis-label">
              {formatPercent(tick)}
            </text>
          </g>
        ))}
        <polyline points={line} className="oee-evolution__line" />
        {points.map((point, index) => (
          <g key={`${point.at}-${index}`}>
            <circle
              cx={x(index)}
              cy={y(point.value)}
              r="12"
              className="oee-evolution__hit"
              tabIndex={0}
              aria-label={pointLabel(point)}
              onMouseEnter={() => setActiveIndex(index)}
              onMouseLeave={() => setActiveIndex(null)}
              onFocus={() => setActiveIndex(index)}
              onBlur={() => setActiveIndex(null)}
            />
            <circle
              cx={x(index)}
              cy={y(point.value)}
              r={activeIndex === index ? "6" : "4"}
              className="oee-evolution__point"
              aria-hidden="true"
            />
            {visibleLabels.has(index) ? (
              <text x={x(index)} y={height - 9} textAnchor="middle" className="oee-evolution__axis-label">
                {evolutionDate(point.at)}
              </text>
            ) : null}
          </g>
        ))}
        {activePoint ? (
          <g className="oee-evolution__tooltip" role="tooltip" aria-label={`Detalhes de ${evolutionPeriod(activePoint)}`}>
            <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height={tooltipHeight} rx="6" className="oee-evolution__tooltip-box" />
            <text x={tooltipX + 12} y={tooltipY + 18} className="oee-evolution__tooltip-date">
              {evolutionPeriod(activePoint)}
            </text>
            <text x={tooltipX + 12} y={tooltipY + 41} className="oee-evolution__tooltip-value">
              OEE: {formatPercent(activePoint.components?.oee?.value ?? activePoint.value)}
            </text>
            <text x={tooltipX + 108} y={tooltipY + 41} className="oee-evolution__tooltip-value">
              Disp.: {evolutionMetric(activePoint.components?.availability)}
            </text>
            <text x={tooltipX + 210} y={tooltipY + 41} className="oee-evolution__tooltip-value">
              Perf.: {evolutionMetric(activePoint.components?.performance)}
            </text>
            <text x={tooltipX + 310} y={tooltipY + 41} className="oee-evolution__tooltip-value">
              FTT/Qua.: {evolutionMetric(activePoint.components?.ftt)}
            </text>
          </g>
        ) : null}
      </svg>
      {evolution.reason ? <p className="oee-evolution__note">{evolution.reason}</p> : null}
      <ul className="visually-hidden">
        {points.map((point) => <li key={point.at}>{pointLabel(point)}</li>)}
      </ul>
    </div>
  );
}

export function AnalyticsOeePage() {
  const filters = useManagementFilters();
  // O gráfico histórico é atualizado por eventos de dados; o pulso técnico de
  // relógio não deve refazer dezenas de intervalos enquanto nada foi alterado.
  const query = useApiQuery<OeeResponse>(
    `/api/v1/analytics/oee?${filters.query}`,
    { ignoreLiveTick: true },
  );
  const title = "Análises — OEE";
  const subtitle = "Disponibilidade × Performance × FTT do período selecionado.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const components = data?.components ?? {};
  const extended = data?.extended_metrics ?? {};
  const losses = data?.losses_breakdown ?? {};
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="OEE" value={metric(components.oee)} detail={components.oee?.reason ?? data?.reason ?? undefined} accent="purple" availability={metricState(components.oee)} />
        <MetricCard label="Disponibilidade" value={metric(components.availability)} detail={components.availability?.reason ?? undefined} accent="success" availability={metricState(components.availability)} />
        <MetricCard label="Performance" value={metric(components.performance)} detail={components.performance?.reason ?? undefined} accent="warning" availability={metricState(components.performance)} />
        <MetricCard label="FTT / Qualidade" value={metric(components.ftt)} detail={components.ftt?.reason ?? undefined} accent="teal" availability={metricState(components.ftt)} />
      </div>
      <div className="metric-grid metric-grid--four content-section">
        <MetricCard label="AE" value={metric(extended.ae)} detail={extended.ae?.reason ?? "Produtivo líquido sobre tempo disponível."} accent="purple" availability={metricState(extended.ae)} />
        <MetricCard label="Produtividade" value={metric(extended.productivity)} detail={extended.productivity?.reason ?? "Produtivo bruto sobre tempo operacional."} accent="teal" availability={metricState(extended.productivity)} />
        <MetricCard label="Utilização" value={metric(extended.utilization)} detail={extended.utilization?.reason ?? "Tempo trabalhado sobre tempo operacional."} accent="warning" availability={metricState(extended.utilization)} />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Evolução do OEE">
          {data?.evolution && data.evolution.points.length >= 2 ? (
            <OeeEvolutionChart evolution={data.evolution} />
          ) : (
            <EmptyState
              title="Dados insuficientes"
              detail={data?.evolution?.reason ?? "Dados insuficientes para exibir a evolução do OEE no período selecionado."}
            />
          )}
        </SectionCard>
        <SectionCard title="Onde o OEE está sendo perdido">
          <div className="explanation-list">
            <div><i className="dot dot--success" /><strong>Disponibilidade</strong><span>{lossLabel(components.availability)}</span></div>
            <div><i className="dot dot--warning" /><strong>Performance</strong><span>{lossLabel(components.performance)}</span></div>
            <div><i className="dot dot--teal" /><strong>FTT / Qualidade</strong><span>{lossLabel(components.ftt)}</span></div>
          </div>
        </SectionCard>
      </div>
      <SectionCard title="Perdas por motivo" className="content-section">
        <div className="explanation-list">
          <div><i className="dot dot--muted" /><strong>Fora de turno</strong><span>{formatDuration(losses.fora_de_turno_segundos ?? null)}</span></div>
          <div><i className="dot dot--success" /><strong>Parada planejada</strong><span>{formatDuration(losses.parada_planejada_segundos ?? null)}</span></div>
          <div><i className="dot dot--danger" /><strong>Parada não planejada</strong><span>{formatDuration(losses.parada_nao_planejada_segundos ?? null)}</span></div>
          <div><i className="dot dot--warning" /><strong>Ritmo (performance)</strong><span>{formatDuration(losses.ritmo_segundos ?? null)}</span></div>
          <div><i className="dot dot--teal" /><strong>Refugo</strong><span>{formatNumber(losses.refugo_quantidade ?? null)} peça(s)</span></div>
          <div><i className="dot dot--teal" /><strong>Retrabalho</strong><span>{formatNumber(losses.retrabalho_quantidade ?? null)} peça(s)</span></div>
        </div>
      </SectionCard>
    </PageFrame>
  );
}

export function AnalyticsHoursPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<TimeBreakdown>(`/api/v1/analytics/hours-utilization?${filters.query}`);
  const title = "Análises — Horas & Utilização";
  const subtitle = "Tempo físico consolidado sem multiplicar a máquina por OPs simultâneas.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const resources = (data?.by_resource ?? []).map((row) => ({ label: String(row.recurso), value: Number(row.producao ?? 0), detail: formatHours(Number(row.producao ?? 0)) }));
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Tempo físico" value={formatHours(data?.physical_seconds)} />
        <MetricCard label="Tempo atribuído bruto" value={formatHours(data?.raw_attributed_timeline_seconds)} accent="teal" />
        <MetricCard label="Sobreposição removida" value={formatHours(data?.overlap_removed_seconds)} accent="warning" />
        <MetricCard
          label="Utilização"
          value={metric(data?.simulation?.metrics.utilization)}
          detail={data?.simulation?.metrics.utilization.reason ?? "Requer capacidade e calendário validados"}
          accent="danger"
          availability={data?.simulation?.metrics.utilization.availability ?? "dados_insuficientes"}
        />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Produção por recurso">{resources.length ? <BarList data={resources.slice(0, 12)} /> : <EmptyState />}</SectionCard>
        <SectionCard title="Resumo por setor">
          <DataTable
            rows={data?.by_sector ?? []}
            rowKey={(row) => String(row.setor)}
            columns={[
              { key: "sector", label: "Setor", render: (row) => String(row.setor) },
              { key: "production", label: "Produção", render: (row) => formatHours(Number(row.producao ?? 0)) },
              { key: "setup", label: "Setup", render: (row) => formatHours(Number(row.setup ?? 0)) },
              { key: "downtime", label: "Paradas", render: (row) => formatHours(Number(row.parada ?? 0)) },
            ]}
          />
        </SectionCard>
      </div>
    </PageFrame>
  );
}

function SegmentPage() {
  const [kind, setKind] = useState<"downtimes" | "setups">("downtimes");
  const filters = useManagementFilters();
  const isStop = kind === "downtimes";
  const endpoint = isStop ? "downtimes" : "setups";
  const title = "Análises — Paradas & Setup";
  const subtitle = isStop
    ? "Tempo, frequência, classificação e motivo das paradas físicas."
    : "Tempo de setup produtivo, separado da produção e sem penalizar Disponibilidade ou Performance.";
  const toggle = (
    <div className="segment-toggle" role="tablist" aria-label="Tipo de análise">
      <button type="button" role="tab" aria-selected={isStop} className={`segment-toggle__btn${isStop ? " segment-toggle__btn--active" : ""}`} onClick={() => setKind("downtimes")}>Paradas</button>
      <button type="button" role="tab" aria-selected={!isStop} className={`segment-toggle__btn${!isStop ? " segment-toggle__btn--active" : ""}`} onClick={() => setKind("setups")}>Setup</button>
    </div>
  );
  const query = useApiQuery<SegmentSummary>(`/api/v1/analytics/${endpoint}?${filters.query}`);
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}>{toggle}<ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const reasons = (data?.by_reason ?? []).map((row) => ({
    label: String(row.motivo ?? "Não informado"),
    value: Number(row.seconds ?? row.segundos ?? 0),
    detail: formatHours(Number(row.seconds ?? row.segundos ?? 0)),
  }));
  const biggest = reasons[0];
  const resourceRanking = (data?.by_resource ?? []).map((row) => ({
    label: String(row.recurso ?? "Não informado"),
    value: Number(row.seconds ?? row.segundos ?? 0),
  }));
  const topResource = resourceRanking[0];
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      {toggle}
      <div className="metric-grid metric-grid--four">
        <MetricCard label={`Tempo total de ${isStop ? "parada" : "setup"}`} value={formatHours(data?.total_seconds)} accent={isStop ? "danger" : "teal"} />
        <MetricCard label="Ocorrências" value={formatNumber(data?.count)} detail={data?.count ? `Média de ${formatDuration((data?.total_seconds ?? 0) / data.count)} por ocorrência` : undefined} />
        <MetricCard label={isStop ? "Recurso mais parado" : "Recurso com mais setup"} value={topResource?.label ?? "Não determinado"} detail={topResource ? formatHours(topResource.value) : undefined} availability={topResource ? "disponivel" : "sem_registros"} accent="warning" />
        <MetricCard
          label={isStop ? "Maior parada" : "Setup mais longo"}
          value={biggest ? formatHours(biggest.value) : "Nenhuma"}
          detail={biggest?.label}
          availability={biggest ? "disponivel" : "sem_registros"}
          accent={isStop ? "danger" : "teal"}
        />
      </div>
      <div className="analytics-split content-section">
        <SectionCard title={isStop ? "Pareto por motivo" : "Tempo por tipo de setup"}>{reasons.length ? <BarList data={reasons.slice(0, 10)} /> : <EmptyState />}</SectionCard>
        <SectionCard title="Ocorrências" className="section-card--table">
          <DataTable
            rows={data?.items ?? []}
            rowKey={(row, index) => row.estado_recurso_id ?? row.evento_id ?? `${row.inicio}-${index}`}
            columns={[
              { key: "resource", label: "Recurso", render: (row) => row.recurso ?? "Não disponível" },
              { key: "sector", label: "Setor", render: (row) => row.setor ?? "Não disponível" },
              { key: "reason", label: "Motivo", render: (row) => row.motivo ?? "Não disponível" },
              { key: "classification", label: "Classificação", render: (row) => <StatusBadge value={isStop ? (row.programada ? "Programada" : "Não programada") : (row.tipo_setup ?? "Setup")} /> },
              { key: "start", label: "Início", render: (row) => formatDateTime(row.inicio) },
              { key: "time", label: "Tempo", render: (row) => formatDuration(row.segundos) },
              { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            ]}
          />
        </SectionCard>
      </div>
    </PageFrame>
  );
}

export function AnalyticsDowntimesPage() { return <SegmentPage />; }

export function AnalyticsQualityPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<QualityResponse>(`/api/v1/analytics/quality?${filters.query}`);
  const title = "Análises — Qualidade";
  const subtitle = "Peças boas, refugo e retrabalho em fontes separadas, com FTT explícito.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const scrap = (data?.scrap_reasons ?? []).map((row) => ({
    label: String(row.motivo ?? row.razao ?? "Não informado"),
    value: Number(row.quantidade ?? row.count ?? 0),
  }));
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={formatNumber(data?.totals.boa)} accent="success" />
        <MetricCard label="Refugo" value={formatNumber(data?.totals.refugo)} accent="danger" />
        <MetricCard label="Retrabalho" value={formatNumber(data?.totals.retrabalho)} accent="warning" />
        <MetricCard label="FTT" value={data?.ftt.value === null ? availabilityLabel[data.ftt.availability] : formatPercent(data?.ftt.value)} detail={data?.ftt.reason ?? undefined} accent="teal" availability={metricState(data?.ftt)} />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Refugo por motivo">{scrap.length ? <BarList data={scrap} unit=" peças" /> : <EmptyState />}</SectionCard>
        <SectionCard title="Qualidade por setor">
          <DataTable
            rows={data?.by_sector ?? []}
            rowKey={(row) => row.setor}
            columns={[
              { key: "sector", label: "Setor", render: (row) => row.setor },
              { key: "good", label: "Boas", render: (row) => formatNumber(row.boa) },
              { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
              { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
            ]}
          />
        </SectionCard>
      </div>
      <FirstPieceHistorySection />
    </PageFrame>
  );
}

/**
 * Histórico do portão Setup/Qualidade do posto (Wave 6B).
 *
 * O operador deixou de ter uma aba de Qualidade, mas o que ele registrou
 * continua existindo: esta seção lê `\/management\/first-pieces`, que projeta a
 * mesma primeira peça persistida pelo posto — Setup apontado, resultado da
 * inspeção, as cotas medidas e as autorizações por crachá. A gestão apenas lê.
 */
function FirstPieceHistorySection() {
  const query = useApiQuery<FirstPieceHistoryResponse>("/api/v1/management/first-pieces");
  const items = query.data?.items ?? [];
  const authorizations = query.data?.authorizations ?? [];
  return (
    <div className="content-section">
      <SectionCard title="Primeira peça — Setup e checklist do posto">
        {query.loading && !query.data ? <LoadingState label="Carregando o histórico…" /> : query.error ? (
          <ErrorState error={query.error} onRetry={query.reload} />
        ) : items.length ? (
          <DataTable
            rows={items}
            rowKey={(row) => String(row.id)}
            columns={[
              { key: "inspecao", label: "Inspecionada em", render: (row) => formatDateTime(row.inspecionada_em) },
              { key: "op", label: "OP", render: (row) => row.codigo_op },
              { key: "operacao", label: "Operação", render: (row) => row.numero_operacao ?? "—" },
              { key: "setor", label: "Setor", render: (row) => row.tipo_setor ?? "—" },
              { key: "produto", label: "Produto", render: (row) => row.produto_codigo ?? "—" },
              { key: "setup", label: "Setup", render: (row) => (row.setup_registrado_em ? formatDateTime(row.setup_registrado_em) : row.setup_obrigatorio ? "Pendente" : "Não se aplica") },
              { key: "status", label: "Resultado", render: (row) => <StatusBadge value={row.bloqueio_ativo ? "Bloqueada" : row.status} /> },
              { key: "operador", label: "Inspecionou", render: (row) => row.inspecionada_por ?? "—" },
              { key: "cotas", label: "Cotas medidas", render: (row) => row.observacao ?? "—" },
            ]}
          />
        ) : <EmptyState title="Nenhuma primeira peça registrada" />}
      </SectionCard>
      <SectionCard title="Autorizações por crachá — retrabalho e refugo">
        {authorizations.length ? (
          <DataTable
            rows={authorizations}
            rowKey={(row) => String(row.id)}
            columns={[
              { key: "data", label: "Data", render: (row) => formatDateTime(row.data_hora) },
              { key: "op", label: "OP", render: (row) => row.codigo_op },
              { key: "ocorrencia", label: "Ocorrência", render: (row) => humanize(row.ocorrencia) },
              { key: "decisao", label: "Decisão", render: (row) => <StatusBadge value={row.decisao} /> },
              { key: "cracha", label: "Crachá", render: (row) => row.cracha },
              { key: "responsavel", label: "Responsável", render: (row) => row.autorizado_por_nome ?? "—" },
              { key: "motivo", label: "Motivo da recusa", render: (row) => row.motivo_recusa ?? "—" },
            ]}
          />
        ) : <EmptyState title="Nenhuma autorização registrada" />}
      </SectionCard>
    </div>
  );
}

export function AnalyticsStandardPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<StandardResponse>(`/api/v1/analytics/standard-vs-actual?${filters.query}`);
  const title = "Análises — Tempo padrão";
  const subtitle = "Tempo padrão e execução real por OP/operação com fonte temporal identificada.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  const standard = rows.reduce(
    (acc, row) => {
      const expected = row.tempo_padrao_estimado_segundos;
      const real = row.tempo_producao_real_segundos;
      if (expected == null || real == null) return acc;
      return { comparable: acc.comparable + 1, expected: acc.expected + Number(expected), real: acc.real + Number(real) };
    },
    { comparable: 0, expected: 0, real: 0 },
  );
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Comparações" value={formatNumber(rows.length)} detail={rows.length ? `${formatNumber(standard.comparable)} com tempo padrão cadastrado` : undefined} />
        <MetricCard label="Tempo padrão acumulado" value={standard.comparable ? formatHours(standard.expected) : "Não configurado"} availability={standard.comparable ? "disponivel" : "nao_configurado"} accent="warning" />
        <MetricCard label="Tempo real acumulado" value={standard.comparable ? formatHours(standard.real) : "Dados insuficientes"} availability={standard.comparable ? "disponivel" : "dados_insuficientes"} accent="success" />
        <MetricCard
          label="Desvio do padrão"
          value={standard.comparable && standard.expected > 0 ? formatPercent((standard.real - standard.expected) / standard.expected * 100) : "Dados insuficientes"}
          detail={standard.comparable ? formatSignedDuration(standard.real - standard.expected) : undefined}
          availability={standard.comparable && standard.expected > 0 ? "disponivel" : "dados_insuficientes"}
          accent={standard.real > standard.expected ? "danger" : "success"}
        />
      </div>
      <SectionCard title="Desvios por OP/operação" className="content-section section-card--table">
        <DataTable
          rows={rows}
          rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
          columns={[
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "operation", label: "Operação", render: (row) => row.operacao ?? "Não disponível" },
            { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
            { key: "resource", label: "Recurso real", render: (row) => row.recurso_real ?? "Não disponível" },
            { key: "good", label: "Peças boas", render: (row) => formatNumber(row.quantidade_boa) },
            { key: "standard", label: "Padrão estimado", render: (row) => formatDuration(row.tempo_padrao_estimado_segundos) },
            { key: "real", label: "Tempo real", render: (row) => formatDuration(row.tempo_producao_real_segundos) },
            { key: "deviation", label: "Desvio", render: (row) => formatSignedDuration(row.desvio_segundos) },
            { key: "deviation-percent", label: "Desvio %", render: (row) => formatPercent(row.desvio_percentual) },
            { key: "source", label: "Fonte", render: (row) => humanize(row.fonte_tempo_producao) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function AnalyticsChronoPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<ChronoResponse>(`/api/v1/analytics/chronoanalysis?${filters.query}`);
  const title = "Análises — Cronoanálise";
  const subtitle = "Distribuição do tempo real por peça, agrupada por produto, operação e recurso.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const groups = query.data?.groups ?? [];
  const bars = groups.slice(0, 10).map((row) => ({ label: `${row.produto} • ${row.operacao}`, value: row.media_segundos_por_peca, detail: formatDuration(row.media_segundos_por_peca) }));
  const samples = groups.reduce((total, row) => total + row.amostras, 0);
  const chrono = {
    samples,
    average: samples ? groups.reduce((total, row) => total + row.media_segundos_por_peca * row.amostras, 0) / samples : 0,
    slowest: [...groups].sort((left, right) => right.media_segundos_por_peca - left.media_segundos_por_peca)[0],
    mostVariable: [...groups].sort((left, right) => right.desvio_padrao_segundos_por_peca - left.desvio_padrao_segundos_por_peca)[0],
  };
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Grupos analisados" value={formatNumber(groups.length)} detail={groups.length ? `${formatNumber(chrono.samples)} execuções medidas` : undefined} />
        <MetricCard label="Ciclo médio por peça" value={groups.length ? formatDuration(chrono.average) : "Dados insuficientes"} availability={groups.length ? "disponivel" : "dados_insuficientes"} accent="success" />
        <MetricCard label="Maior variação" value={chrono.mostVariable ? formatDuration(chrono.mostVariable.desvio_padrao_segundos_por_peca) : "Dados insuficientes"} detail={chrono.mostVariable ? `${chrono.mostVariable.produto} • ${chrono.mostVariable.operacao}` : undefined} availability={chrono.mostVariable ? "disponivel" : "dados_insuficientes"} accent="warning" />
        <MetricCard label="Ciclo mais lento" value={chrono.slowest ? formatDuration(chrono.slowest.media_segundos_por_peca) : "Dados insuficientes"} detail={chrono.slowest ? `${chrono.slowest.produto} • ${chrono.slowest.recurso}` : undefined} availability={chrono.slowest ? "disponivel" : "dados_insuficientes"} accent="purple" />
      </div>
      <div className="analytics-split content-section">
        <SectionCard title="Média real por peça">{bars.length ? <BarList data={bars} /> : <EmptyState title="Dados insuficientes" />}</SectionCard>
        <SectionCard title="Amostras" className="section-card--table">
          <DataTable
            rows={groups}
            rowKey={(row) => `${row.produto}-${row.operacao}-${row.recurso}`}
            columns={[
              { key: "product", label: "Produto", render: (row) => row.produto },
              { key: "operation", label: "Operação", render: (row) => row.operacao },
              { key: "resource", label: "Recurso", render: (row) => row.recurso },
              { key: "sample", label: "Amostra", render: (row) => formatNumber(row.amostras) },
              { key: "average", label: "Média", render: (row) => formatDuration(row.media_segundos_por_peca) },
              { key: "median", label: "Mediana", render: (row) => formatDuration(row.mediana_segundos_por_peca) },
              { key: "min", label: "Mínimo", render: (row) => formatDuration(row.minimo_segundos_por_peca) },
              { key: "max", label: "Máximo", render: (row) => formatDuration(row.maximo_segundos_por_peca) },
              { key: "deviation", label: "Desvio", render: (row) => formatDuration(row.desvio_padrao_segundos_por_peca) },
            ]}
          />
        </SectionCard>
      </div>
    </PageFrame>
  );
}

export function AnalyticsCapacityPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<CapacityResponse>(`/api/v1/analytics/capacity?${filters.query}`);
  const title = "Análises — Capacidade";
  const subtitle = "Quanto do tempo disponível pelo calendário produtivo virou trabalho, e onde está o gargalo.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const configured = data?.availability !== "nao_configurado";
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard
          label="Utilização do período"
          value={data?.utilizacao_percentual == null ? availabilityLabel[data?.availability ?? "dados_insuficientes"] : formatPercent(data.utilizacao_percentual)}
          detail={data?.utilizacao_percentual == null ? data?.reason : "Tempo ocupado ÷ tempo disponível no calendário"}
          availability={data?.availability ?? "dados_insuficientes"}
          accent="purple"
        />
        <MetricCard
          label="Tempo disponível"
          value={configured && data?.total_capacity_seconds != null ? formatHours(data.total_capacity_seconds) : "Não configurado"}
          detail={data?.recursos_sem_calendario ? `${formatNumber(data.recursos_sem_calendario)} recurso(s) sem calendário` : undefined}
          availability={configured ? "disponivel" : "nao_configurado"}
          accent="warning"
        />
        <MetricCard
          label="Capacidade livre"
          value={configured && data?.total_remaining_seconds != null ? formatHours(data.total_remaining_seconds) : "Não configurado"}
          detail={configured && data?.total_load_seconds != null ? `${formatHours(data.total_load_seconds)} já ocupados` : undefined}
          availability={configured ? "disponivel" : "nao_configurado"}
          accent="success"
        />
        <MetricCard
          label="Gargalo"
          value={data?.bottleneck_resource ?? "Não determinado"}
          detail={data?.bottleneck_utilizacao_percentual != null ? `${formatPercent(data.bottleneck_utilizacao_percentual)} de utilização` : "Depende de calendário cadastrado"}
          availability={data?.bottleneck_resource ? "disponivel" : "nao_configurado"}
          accent="danger"
        />
      </div>
      <SectionCard title="Utilização por recurso" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row, index) => row.codigo ?? row.recurso ?? index}
          emptyTitle="Nenhum recurso no filtro"
          columns={[
            { key: "resource", label: "Recurso", render: (row) => row.nome ?? row.codigo ?? row.recurso ?? "Não disponível" },
            { key: "sector", label: "Setor", render: (row) => row.tipo_setor ?? row.setor ?? "Não disponível" },
            { key: "capacity", label: "Tempo disponível", render: (row) => row.capacidade_segundos == null ? "Não configurado" : formatHours(row.capacidade_segundos) },
            { key: "load", label: "Tempo ocupado", render: (row) => formatHours(row.carga_segundos) },
            { key: "remaining", label: "Livre", render: (row) => row.capacidade_restante_segundos == null ? "Não configurado" : formatHours(row.capacidade_restante_segundos) },
            { key: "utilization", label: "Utilização", render: (row) => row.utilizacao_percentual == null ? "Não configurado" : formatPercent(row.utilizacao_percentual) },
            { key: "queue", label: "Fila", render: (row) => formatNumber(row.fila) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function AnalyticsReliabilityPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<ReliabilityResponse>(`/api/v1/analytics/reliability?${filters.query}`);
  const title = "Análises — Confiabilidade";
  const subtitle = "Quebras de equipamento no período: com que frequência param e quanto tempo levam para voltar.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="analytics" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const measurable = data?.availability === "disponivel" || data?.availability === "parcial";
  const critical = data?.por_recurso?.[0];
  return (
    <PageFrame staleError={query.error} sectionId="analytics" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard
          label="MTBF"
          value={data?.mtbf_segundos == null ? availabilityLabel[data?.availability ?? "dados_insuficientes"] : formatHours(data.mtbf_segundos)}
          detail={data?.mtbf_segundos == null ? data?.reason : "Tempo operacional entre quebras"}
          availability={data?.availability ?? "dados_insuficientes"}
          accent="primary"
        />
        <MetricCard
          label="MTTR"
          value={data?.mttr_segundos == null ? availabilityLabel[data?.availability ?? "dados_insuficientes"] : formatDuration(data.mttr_segundos)}
          detail={data?.mttr_segundos == null ? undefined : "Tempo médio até voltar a produzir"}
          availability={data?.availability ?? "dados_insuficientes"}
          accent="warning"
        />
        <MetricCard
          label="Quebras no período"
          value={formatNumber(data?.falhas ?? 0)}
          detail={measurable ? `${formatHours(data?.tempo_reparo_segundos ?? 0)} de máquina parada` : undefined}
          accent={(data?.falhas ?? 0) > 0 ? "danger" : "success"}
        />
        <MetricCard
          label="Equipamento mais crítico"
          value={critical?.recurso ?? "Nenhum"}
          detail={critical ? `${formatNumber(critical.falhas)} quebra(s) · ${formatHours(critical.tempo_reparo_segundos)} parado` : "Nenhuma quebra registrada"}
          availability={critical ? "disponivel" : "sem_registros"}
          accent="danger"
        />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Quebras por equipamento">
          {data?.por_recurso?.length ? (
            <DataTable
              rows={data.por_recurso}
              rowKey={(row) => row.recurso}
              columns={[
                { key: "resource", label: "Recurso", render: (row) => row.recurso },
                { key: "failures", label: "Quebras", render: (row) => formatNumber(row.falhas) },
                { key: "downtime", label: "Tempo parado", render: (row) => formatHours(row.tempo_reparo_segundos) },
                { key: "mttr", label: "MTTR", render: (row) => row.mttr_segundos == null ? "Não disponível" : formatDuration(row.mttr_segundos) },
              ]}
            />
          ) : <EmptyState title="Nenhuma quebra no período" detail={data?.reason} />}
        </SectionCard>
        <SectionCard title="Causas das quebras">
          {data?.motivos?.length ? (
            <BarList data={data.motivos.map((row) => ({ label: row.motivo, value: row.quantidade }))} unit=" ocorrência(s)" />
          ) : <EmptyState title="Nenhuma causa registrada" detail={data?.taxonomia} />}
        </SectionCard>
      </div>
    </PageFrame>
  );
}
