import { useCallback, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LineChart, Sparkline, StackBar } from "../components/charts";
import { ErrorState, LoadingState, EmptyState } from "../components/DataState";
import { apiErrorMessage } from "../api/client";
import { ManagementInsightDrawer } from "../components/ManagementInsightDrawer";
import { ExplainableValue } from "../components/ExplainableValue";
import { DraggableDashboardBlock } from "../components/DraggableDashboardBlock";
import { MetricCard } from "../components/MetricCard";
import { MetricExplanationPanel } from "../components/MetricExplanationPanel";
import { PageFrame } from "../components/PageFrame";
import { SectionCard } from "../components/SectionCard";
import { useManagementFilters } from "../filters/FilterContext";
import { useApiQuery } from "../hooks/useApiQuery";
import { useGridFlip } from "../hooks/useGridFlip";
import { useOncePerMinute } from "../hooks/useOncePerMinute";
import { moveDashboardCard, useUserPreferences } from "../hooks/useUserPreferences";
import { explainableComposition } from "../types/explanation";
import type { AndonSnapshot } from "../types/andon";
import type { DashboardCardKey, DashboardCardSize, KpiExplanation, ManagementException, ManagementOverview, MetricValue, OverviewTrend, OverviewTrendPoint } from "../types/api";
import type { SectorSummary } from "../types/api";
import { displayName, displayText, formatHours, formatNumber } from "../utils/format";
import { humanizeSystemState } from "../utils/systemState";
import { MAX_CARDS_ON_SCREEN } from "../utils/dashboardCards";

function metricText(metric: MetricValue) {
  if (metric.value === null) return humanizeSystemState(metric.availability);
  const formatted = metric.value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  return `${formatted}${metric.unit ?? ""}`;
}

function hours(seconds: number) {
  return `${(seconds / 3600).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h`;
}

/** Variação contra o período anterior: diferença simples entre dois valores que o backend já calculou. */
const hasReading = (metric: MetricValue) => metric.availability === "disponivel" || metric.availability === "parcial";

function kpiTrend(current: MetricValue, previous?: MetricValue): { text: string; up: boolean } | undefined {
  if (current.value === null || !hasReading(current) || !previous || previous.value === null || !hasReading(previous)) return undefined;
  const diff = current.value - previous.value;
  return { text: `${Math.abs(diff).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} pp`, up: diff >= 0 };
}

function quantityTrend(current: number, previous?: number): { text: string; up: boolean } | undefined {
  if (previous === undefined || previous <= 0) return undefined;
  const diff = ((current - previous) / previous) * 100;
  return { text: `${Math.abs(diff).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`, up: diff >= 0 };
}

const TIME_COLORS: Record<string, string> = {
  production_seconds: "var(--accent)",
  setup_seconds: "var(--primary)",
  unplanned_downtime_seconds: "var(--warning)",
  planned_downtime_seconds: "var(--orange)",
  rework_seconds: "var(--danger)",
  activity_without_op_seconds: "var(--purple)",
  no_demand_seconds: "var(--teal)",
  out_of_shift_seconds: "var(--muted)",
};
const SERIES_COLORS = { oee: "var(--purple)", availability: "var(--accent)", performance: "var(--warning)", ftt: "var(--teal)", good: "var(--primary)" };

/**
 * Destaque e complemento de cada linha da composição. A média por recurso
 * (total ÷ recursos com turno, vinda do backend) é o destaque: avança no ritmo
 * do relógio. O total somado vai no complemento, junto com quantos recursos;
 * ele sobe N vezes mais rápido (N recursos contando ao mesmo tempo). Sem média,
 * só quem fica fora do total ganha "não somado".
 */
function averageLine(item: { seconds: number; summed?: boolean; average_seconds?: number | null }, resourceCount: number) {
  if (item.average_seconds != null && resourceCount > 1) {
    return { lead: `média ${formatHours(item.average_seconds)}`, hint: `total ${formatHours(item.seconds)} em ${resourceCount} recursos` };
  }
  return { hint: item.summed === false ? "não somado" : undefined };
}

function dayLabel(point: OverviewTrendPoint) {
  const [, month, day] = point.period_start.slice(0, 10).split("-");
  return `${day}/${month}`;
}

function ago(iso: string) {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `há ${minutes} min`;
  const h = Math.floor(minutes / 60);
  return h < 24 ? `há ${h} h` : `há ${Math.floor(h / 24)} d`;
}

function eventColor(state: string) {
  const text = state.toLowerCase();
  if (text.includes("par")) return "var(--danger)";
  if (text.includes("setup")) return "var(--teal)";
  if (text.includes("retrab")) return "var(--purple)";
  if (text.includes("prod")) return "var(--accent)";
  return "var(--primary)";
}

interface ChamadaResumo {
  id: number;
  contato_nome: string;
  motivo: string;
  comentario: string;
  solicitante_nome: string;
  criado_em: string;
}

const sameOrder = (a: readonly DashboardCardKey[], b: readonly DashboardCardKey[]) =>
  a.length === b.length && a.every((key, index) => key === b[index]);

export function ManagementOverviewPage() {
  const {
    cards: visibleCards,
    order: cardOrder,
    sizes,
    visibleCount,
    notice,
    moveCard,
    reorderCards,
    toggleCard,
    resizeCard,
    resetToDefault,
    error: preferencesError,
  } = useUserPreferences();
  const [editMode, setEditMode] = useState(false);
  const [dragSource, setDragSource] = useState<DashboardCardKey | null>(null);
  const [previewOrder, setPreviewOrder] = useState<DashboardCardKey[] | null>(null);
  const [resizePreview, setResizePreview] = useState<{ key: DashboardCardKey; size: DashboardCardSize } | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const displayOrder = previewOrder ?? cardOrder;
  useGridFlip(gridRef, displayOrder.join("|"), dragSource);
  const orderIndex = new Map(displayOrder.map((key, index) => [key, index]));
  const visibleCard = (key: DashboardCardKey) => visibleCards[key] !== false;
  const moveRelative = (key: DashboardCardKey, delta: number) => {
    const index = displayOrder.indexOf(key);
    const targetIndex = index + delta;
    if (index < 0 || targetIndex < 0 || targetIndex >= displayOrder.length) return;
    const target = displayOrder[targetIndex];
    moveCard(key, target, delta < 0);
  };
  const hoverCard = (source: DashboardCardKey, target: DashboardCardKey) => {
    setPreviewOrder((current) => {
      const base = current ?? cardOrder;
      const sourceIndex = base.indexOf(source);
      const targetIndex = base.indexOf(target);
      if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return current;
      // Arrastando para frente, entra depois do alvo; para trás, antes dele.
      const next = moveDashboardCard(base, source, target, sourceIndex > targetIndex);
      return sameOrder(next, base) ? current : next;
    });
  };
  const dropCard = () => {
    if (previewOrder) reorderCards(previewOrder);
    setDragSource(null);
    setPreviewOrder(null);
  };
  const endDrag = () => {
    setDragSource(null);
    setPreviewOrder(null);
  };
  const renderBlock = (key: DashboardCardKey, children: ReactNode) => (
    <DraggableDashboardBlock
      key={key}
      cardKey={key}
      hidden={!visibleCards[key]}
      editMode={editMode}
      index={orderIndex.get(key) ?? 0}
      total={displayOrder.length}
      size={sizes[key]}
      previewSize={resizePreview?.key === key ? resizePreview.size : null}
      dragging={dragSource === key}
      dragSource={dragSource}
      canShow={visibleCount < MAX_CARDS_ON_SCREEN}
      onToggle={toggleCard}
      onMoveUp={(card) => moveRelative(card, -1)}
      onMoveDown={(card) => moveRelative(card, 1)}
      onDragStartCard={(card) => {
        setDragSource(card);
        setPreviewOrder(cardOrder);
      }}
      onDragEndCard={endDrag}
      onHoverCard={hoverCard}
      onDropCard={dropCard}
      onPreviewSize={(card, size) => setResizePreview(size ? { key: card, size } : null)}
      onResizeCard={resizeCard}
    >
      {children}
    </DraggableDashboardBlock>
  );
  const filters = useManagementFilters();
  const navigate = useNavigate();
  const query = useApiQuery<ManagementOverview>(`/api/v1/management/overview?${filters.query}`);
  // Série para gráficos/sparklines: opcional — se falhar ou demorar, a página inteira continua igual.
  const trendQuery = useApiQuery<OverviewTrend>(`/api/v1/management/overview/trend?${filters.query}`, { ignoreLiveTick: true });
  const trend = trendQuery.data && Array.isArray(trendQuery.data.points) && trendQuery.data.availability !== "sem_registros" ? trendQuery.data : null;
  // Cards novos só buscam quando estão visíveis: quem nunca os adicionou não paga a chamada.
  const chamadasQuery = useApiQuery<{ items: ChamadaResumo[] }>(visibleCards.chamadas ? "/api/v1/chamadas/admin/historico" : null);
  const andonQuery = useApiQuery<AndonSnapshot>(visibleCards.andon ? "/api/v1/andon" : null);
  const [selectedKpi, setSelectedKpi] = useState<KpiExplanation | null>(null);
  const closeInsight = useCallback(() => {
    setSelectedKpi(null);
  }, []);
  // Painel "de onde vem este número" (composição do tempo): guarda só o id da métrica.
  const [explainedMetric, setExplainedMetric] = useState<string | null>(null);
  const closeExplanation = useCallback(() => setExplainedMetric(null), []);
  // A composição soma N recursos e sobe N minutos por minuto: só muda na virada do minuto, para não parecer segundos.
  const heldComposition = useOncePerMinute(query.data?.time_composition, filters.query);

  const navigateTo = useCallback((path: string, overrides: Partial<typeof filters.filters> = {}) => {
    filters.setFilters({ ...filters.filters, ...overrides });
    navigate(path);
  }, [filters, navigate]);

  const exceptionDestination = (exception: ManagementException) => {
    const scopedFilters = {
      sector: exception.sector ?? "",
      resource: exception.resource ?? "",
      op: exception.op ?? "",
      operation: exception.operation ?? "",
    };
    if (exception.type === "actual_time_above_standard") {
      return () => navigateTo("/analises/tempo-padrao-real", scopedFilters);
    }
    if (exception.type === "configured_kpi_target") {
      // Aba Metas oculta temporariamente (01/10/2026): leva ao OEE, onde os KPIs ficam.
      return () => navigateTo("/analises/oee", scopedFilters);
    }
    return () => navigateTo("/analises/paradas", scopedFilters);
  };

  if (query.loading) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><LoadingState label="Carregando visão gerencial…" /></PageFrame>;
  if (query.error && !query.data) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  if (!query.data) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><EmptyState state="sem_registros" /></PageFrame>;

  const data = query.data;
  const composition = explainableComposition(heldComposition ?? data.time_composition);
  const kpis = data.kpis;
  const simulation = data.simulation;
  const insights = data.insights;
  const hasQuantityRecords = data.production.availability !== "sem_registros";
  // GE-13: sem fonte de metas o backend avisa em `limitations`; o card diz isso
  // em vez de deixar o percentual solto. Com metas, o desvio vira exceção.
  const targetNote = insights.limitations.some((item) => item.code === "kpi_targets_not_configured") ? "Sem meta definida" : undefined;
  const kpiCards = [
    { key: "oee", label: "OEE", accent: "purple", preferenceKey: "oee" },
    { key: "availability", label: "Disponibilidade", accent: "success", preferenceKey: "disponibilidade" },
    { key: "performance", label: "Performance", accent: "warning", preferenceKey: "performance" },
    { key: "ftt", label: "FTT / Qualidade", accent: "teal", preferenceKey: "ftt" },
  ] as const;
  const noneVisibleCustomBlock = Object.values(visibleCards).every((visible) => !visible);
  const sparkOf = (pick: (point: OverviewTrendPoint) => number | null, color: string) => (trend && trend.points.length > 1 ? <Sparkline values={trend.points.map(pick)} color={color} /> : null);
  const kpiNodes = kpiCards.map((card) => ({
    preferenceKey: card.preferenceKey as DashboardCardKey,
    node: (
      <MetricCard
        label={card.label}
        value={metricText(kpis[card.key])}
        detail={kpis[card.key].reason ?? targetNote}
        accent={card.accent}
        availability={kpis[card.key].availability}
        actionLabel="Entender"
        onClick={() => setSelectedKpi(insights.kpi_explanations[card.key])}
        trend={trend ? kpiTrend(kpis[card.key], trend.previous?.kpis[card.key]) : undefined}
        spark={kpis[card.key].value !== null && kpis[card.key].value !== undefined ? sparkOf((point) => point.kpis[card.key].value, SERIES_COLORS[card.key]) : null}
      />
    ),
  }));
  const plannedSeries = trend && trend.points.length > 1 && trend.points.every((point) => point.planned_quantity !== null) ? trend.points.map((point) => point.planned_quantity) : null;
  const sectorSummary = new Map((trend?.sector_summary ?? []).map((item) => [item.setor, item]));
  // Período ainda em andamento (ex.: "Hoje" às 10h): comparar peças com o período anterior inteiro daria queda falsa.
  const lastPoint = trend?.points[trend.points.length - 1];
  const periodOpen = lastPoint ? new Date(lastPoint.period_end).getTime() > Date.now() : false;
  const quantityText = (value: number) => hasQuantityRecords ? value.toLocaleString("pt-BR") : humanizeSystemState("sem_registros");
  // Só vira clicável o que tem valor para explicar; zero fica texto simples. "Paradas" fica de fora:
  // mistura planejada, não planejada e sem identificação, e ainda não tem uma explicação única.
  const sectorCell = (metric: string, row: SectorSummary, label: string, text: string, value: number) => (
    value > 0 ? (
      <ExplainableValue metric={metric} filters={{ ...filters.filters, sector: row.setor }} context={`${label} em ${displayName(row.setor)} ${text}`}>{text}</ExplainableValue>
    ) : text
  );
  const chamadas = chamadasQuery.data?.items ?? [];
  const andon = andonQuery.data;
  const andonStops = (andon?.sectors.flatMap((sector) => sector.resources) ?? [])
    .filter((resource) => resource.state.category === "parada")
    .slice(0, 4);
  return (
    <PageFrame staleError={query.error} sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro." actions={<button type="button" className="button button--secondary" onClick={() => setEditMode((value) => !value)}>{editMode ? "Concluir" : "Personalizar"}</button>}>
        {editMode ? (
          <div className="dashboard-edit-bar" role="status">
            <strong>Personalização ativa</strong>
            <span>Arraste o card para onde ele deve ficar, use ↑ e ↓ ou puxe as alças para redimensionar. Salvamos automaticamente.</span>
            <span className="dashboard-edit-bar__count">{visibleCount} de {MAX_CARDS_ON_SCREEN} blocos visíveis</span>
            <button type="button" className="button button--secondary" onClick={resetToDefault}>Restaurar padrão</button>
            <button type="button" className="button button--primary" onClick={() => setEditMode(false)}>Concluir</button>
          </div>
        ) : null}
        {notice ? <p role="alert" className="dashboard-customization-error">{notice}</p> : null}
        {preferencesError ? <p role="alert" className="dashboard-customization-error">Não foi possível salvar a personalização: {apiErrorMessage(preferencesError)}</p> : null}
        <div className="home-dashboard-grid" ref={gridRef}>
          {renderBlock("producao_boa", (
            <MetricCard
              label="Produção boa"
              value={quantityText(data.production.good)}
              valueNode={hasQuantityRecords ? (
                <ExplainableValue metric="qtd.boa" filters={filters.filters} context={`Produção boa ${quantityText(data.production.good)}`}>{quantityText(data.production.good)}</ExplainableValue>
              ) : undefined}
              detail={data.production.reason ?? "Peças boas; refugo e retrabalho permanecem separados."}
              availability={data.production.availability}
              trend={trend && hasQuantityRecords && !periodOpen ? quantityTrend(data.production.good, trend.previous?.production.good) : undefined}
              spark={hasQuantityRecords ? sparkOf((point) => point.production.good, SERIES_COLORS.good) : null}
            />
          ))}
          {kpiNodes.map(({ preferenceKey, node }) => renderBlock(preferenceKey, node))}
          {simulation && renderBlock("simulation", (
            <div className="metric-grid metric-grid--auto simulation-metrics">
              <MetricCard label="Planejado" value={simulation.planned_quantity.toLocaleString("pt-BR")} detail="Peças no período" />
              <MetricCard label="Realizado" value={simulation.actual_quantity.toLocaleString("pt-BR")} detail="Somente peças boas" accent="success" />
              <MetricCard label="Atingimento" value={simulation.attainment_percentage === null ? "Não disponível" : `${simulation.attainment_percentage.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`} accent="teal" />
              <MetricCard label="Utilização" value={metricText(simulation.metrics.utilization)} accent="warning" />
              <MetricCard label="Produtividade" value={metricText(simulation.metrics.productivity)} accent="purple" />
              <MetricCard label="AE" value={metricText(simulation.metrics.ae)} detail="Eficiência global efetiva" />
            </div>
          ))}
          {renderBlock("planned_vs_actual", (
          <SectionCard
            title="Planejado × realizado — acumulado"
            className="overview-grid__chart"
            navigation={{ label: "Abrir Produção: Planejado versus Realizado", onNavigate: () => navigateTo("/producao/planejado-realizado") }}
          >
            {trend && trend.points.length > 1 ? (
              <>
                <div className="chart-key">
                  <span><i style={{ "--c": SERIES_COLORS.good } as React.CSSProperties} />Realizado (peças boas)</span>
                  {plannedSeries ? <span><i style={{ "--c": "var(--muted)" } as React.CSSProperties} />Planejado</span> : null}
                </div>
                <LineChart
                  labels={trend.points.map(dayLabel)}
                  series={[
                    ...(plannedSeries ? [{ name: "Planejado", color: "var(--muted)", values: plannedSeries, dashed: true }] : []),
                    { name: "Realizado", color: SERIES_COLORS.good, values: trend.points.map((point) => point.production.good) },
                  ]}
                />
                {plannedSeries ? null : <p className="chart-note">Planejado indisponível: depende do contrato de planejamento confirmado com o Protheus.</p>}
              </>
            ) : null}
            {simulation ? (
              <div className="plan-actual-summary">
                <div><span>Quantidade planejada</span><strong>{simulation.planned_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Quantidade boa realizada</span><strong>{simulation.actual_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Diferença</span><strong>{simulation.difference_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div className="plan-actual-summary__progress"><i style={{ width: `${Math.min(100, simulation.attainment_percentage ?? 0)}%` }} /></div>
              </div>
            ) : trend && trend.points.length > 1 ? null : (
              <EmptyState
                title="Dados insuficientes"
                detail="O planejamento corporativo ainda não possui contrato confirmado para esta consolidação."
              />
            )}
          </SectionCard>
          ))}
          {renderBlock("exceptions", (
          <SectionCard
            title="O que precisa de atenção"
            className="management-attention-card"
            action={<span className="section-count">{insights.exception_count} exceções</span>}
            navigation={{ label: "Abrir análise das exceções", onNavigate: () => navigateTo("/analises/paradas") }}
          >
            {insights.exceptions.length === 0 ? (
              <EmptyState title="Nenhuma exceção identificada" detail="Não há fatos confiáveis que exijam priorização no filtro atual." />
            ) : (
              <ul className="management-exception-list">
                {insights.exceptions.slice(0, 4).map((exception) => (
                  <li key={exception.id}>
                    <button
                      type="button"
                      onClick={exceptionDestination(exception)}
                      aria-label={`Ver análise relacionada a ${displayText(exception.title)}`}
                    >
                      <i data-severity={exception.severity} />
                      <span>
                        <strong>{displayText(exception.title)}</strong>
                        <small>{displayText(exception.summary)}</small>
                      </span>
                      <span className="management-exception-list__impact">
                        <strong>{exception.impact_unit === "s" ? formatHours(exception.impact_value) : `${(exception.impact_value ?? 0).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} ${exception.impact_unit ?? ""}`}</strong>
                        <small>Ver evidências</small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
          ))}
          {renderBlock("time_composition", (
          <SectionCard
            title="Composição do tempo"
            navigation={{ label: "Abrir Análises: Horas & Utilização", onNavigate: () => navigateTo("/analises/horas-utilizacao") }}
          >
            {composition.availability === "sem_registros" ? (
              <EmptyState state={composition.availability} />
            ) : (
              <div className="time-composition">
                <div className="time-composition__total">
                  {(composition.resource_count ?? 0) > 1 ? (
                    <>
                      {/* A soma de N recursos anda N vezes mais rápido que o relógio; em destaque fica a média, que anda no ritmo do relógio. */}
                      <strong>{formatHours(composition.total_seconds / (composition.resource_count ?? 1))}</strong>
                      <span>média por recurso · total {formatHours(composition.total_seconds)} somado de {composition.resource_count} máquinas (sobe {composition.resource_count} min a cada minuto)</span>
                    </>
                  ) : (
                    <>
                      <strong>{formatHours(composition.total_seconds)}</strong>
                      <span>no período</span>
                    </>
                  )}
                </div>
                {composition.average_note ? <p className="time-composition__note">{composition.average_note}</p> : null}
                <StackBar
                  parts={composition.items.map((item) => ({
                    name: item.label,
                    value: item.seconds,
                    color: TIME_COLORS[item.source_field] ?? "var(--muted)",
                    outside: item.summed === false,
                    text: formatHours(item.seconds),
                    ...averageLine(item, composition.resource_count ?? 0),
                    ...(item.metric ? { explainMetric: item.metric, onSelect: () => setExplainedMetric(item.metric ?? null) } : {}),
                  }))}
                />
              </div>
            )}
          </SectionCard>
          ))}
          {renderBlock("top_losses", (
          <SectionCard
            title="Maiores perdas"
            navigation={{ label: "Abrir análise das maiores perdas", onNavigate: () => navigateTo("/analises/paradas") }}
          >
            {insights.losses.length === 0 ? <EmptyState /> : (
              <ol className="management-impact-list">
                {insights.losses.slice(0, 4).map((item) => (
                  <li key={`${item.rank}-${item.cause}`}>
                    <button type="button" onClick={() => navigateTo("/analises/paradas")} aria-label={`Ver paradas por ${item.cause ?? "motivo não informado"}`}>
                      <span><b>{item.rank}</b><span>{displayName(item.cause, "Não informado")}</span></span>
                      <strong>{item.impact_unit === "s" ? formatHours(item.impact_value) : `${item.impact_value.toLocaleString("pt-BR")} ${item.impact_unit}`}</strong>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
          ))}
          {renderBlock("live_events", (
          <SectionCard title="Agora na fábrica">
            {!trend || trend.recent_events.length === 0 ? <EmptyState title="Sem eventos recentes" detail="Mudanças de estado dos recursos aparecem aqui." /> : (
              <ul className="feed">
                {trend.recent_events.slice(0, 8).map((event, index) => (
                  <li key={`${event.resource}-${event.at}`} style={{ animationDelay: `${index * 60}ms` }}>
                    <span className="feed__dot" style={{ "--c": eventColor(event.state) } as React.CSSProperties} aria-hidden="true">{displayName(event.resource_name ?? event.resource).slice(0, 2).toUpperCase()}</span>
                    <span><strong>{displayName(event.resource_name ?? event.resource)}</strong> · {displayText(event.state)}</span>
                    <span className="feed__time">{ago(event.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
          ))}
          {renderBlock("sectors_table", (
          <SectionCard
            title="Setores — leitura rápida e execução real"
            className="overview-grid__table"
            navigation={{ label: "Abrir Consulta Operacional: Recursos", onNavigate: () => navigateTo("/consulta-operacional/recursos") }}
          >
            {data.sectors.length === 0 ? <EmptyState /> : (
              <>
              <div className="metric-grid metric-grid--four">
                {(data.sector_highlights ?? []).map((highlight, index) => (
                  <MetricCard
                    key={highlight.key}
                    label={highlight.label}
                    value={highlight.unit === "s" ? formatHours(highlight.value) : `${formatNumber(highlight.value)} peças`}
                    detail={displayName(highlight.sector, "")}
                    accent={(["success", "warning", "primary", "teal"] as const)[index % 4]}
                  />
                ))}
              </div>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Setor</th>{trend ? <th>OEE</th> : null}{trend ? <th>Recursos produzindo</th> : null}<th>Produção boa</th><th>Refugo</th><th>Retrabalho</th><th>OPs</th><th>Tempo produtivo</th><th>Produção</th><th>Setup</th><th>Paradas</th>{trend ? <th>Tendência</th> : null}</tr></thead>
                  <tbody>
                    {data.sectors.map((sector) => {
                      const summary = sectorSummary.get(sector.setor);
                      const oee = data.sector_kpis?.find((item) => item.setor === sector.setor)?.metrics.oee?.value ?? null;
                      return (
                        <tr key={sector.setor}>
                          <th><Link className="table-link" to={`/consulta-operacional/recursos?setor=${encodeURIComponent(sector.setor)}`}>{displayName(sector.setor)}</Link></th>
                          {trend ? (
                            <td>
                              {oee === null ? "—" : (
                                <span className="sector-oee"><span><i style={{ "--w": `${Math.min(100, oee)}%`, "--c": "var(--purple)" } as React.CSSProperties} /></span><b>{oee.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</b></span>
                              )}
                            </td>
                          ) : null}
                          {trend ? <td>{summary && summary.resources_total > 0 ? `${summary.resources_with_production} de ${summary.resources_total}` : "—"}</td> : null}
                          <td>{sectorCell("qtd.boa", sector, "Produção boa", quantityText(sector.producao_boa), hasQuantityRecords ? sector.producao_boa : 0)}</td>
                          <td>{sectorCell("qtd.refugo", sector, "Refugo", quantityText(sector.refugo), hasQuantityRecords ? sector.refugo : 0)}</td>
                          <td>{sectorCell("qtd.retrabalho", sector, "Retrabalho", quantityText(sector.retrabalho), hasQuantityRecords ? sector.retrabalho : 0)}</td>
                          <td>{sector.setor.trim().toLowerCase() === "corte" ? "—" : sector.ops}</td>
                          <td>{hours(sector.tempo_produtivo_segundos)}</td>
                          <td>{sectorCell("tempo.producao", sector, "Tempo de produção", formatHours(sector.tempo_producao_segundos), sector.tempo_producao_segundos)}</td>
                          <td>{sectorCell("tempo.setup", sector, "Tempo de setup", formatHours(sector.tempo_setup_segundos), sector.tempo_setup_segundos)}</td>
                          <td>{formatHours(sector.tempo_parada_segundos)}</td>
                          {trend ? (
                            <td className="sector-spark">
                              <Sparkline values={trend.points.map((point) => point.sectors.find((item) => item.setor === sector.setor)?.producao_boa ?? null)} color="var(--primary)" />
                            </td>
                          ) : null}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              </>
            )}
          </SectionCard>
          ))}
          {renderBlock("top_resources", (
          <SectionCard
            title="Recursos com maior impacto"
            navigation={{ label: "Abrir análise dos recursos com maior impacto", onNavigate: () => navigateTo("/analises/paradas") }}
          >
            {insights.critical_resources.length === 0 ? <EmptyState /> : (
              <ol className="management-impact-list">
                {insights.critical_resources.slice(0, 4).map((item) => (
                  <li key={`${item.rank}-${item.resource}`}>
                    <button
                      type="button"
                      onClick={() => navigateTo("/analises/paradas", { resource: item.resource ?? "" })}
                      aria-label={`Ver paradas do recurso ${item.resource ?? "não informado"}`}
                    >
                      <span><b>{item.rank}</b><span>{displayName(item.resource, "Não informado")}</span></span>
                      <strong>{item.impact_unit === "s" ? formatHours(item.impact_value) : `${item.impact_value.toLocaleString("pt-BR")} ${item.impact_unit}`}</strong>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
          ))}
          {renderBlock("audit_issues", (
          <SectionCard
            title="Inconsistências de dados"
            navigation={{ label: "Abrir Auditoria: Alertas e inconsistências", onNavigate: () => navigateTo("/auditoria/alertas-inconsistencias") }}
          >
            {data.audit.open_issues.length === 0 ? (
              <EmptyState title="Sem inconsistências abertas" />
            ) : (
              <ul className="issue-list">
                {data.audit.open_issues.slice(0, 4).map((issue, index) => (
                  <li key={String(issue.id ?? index)}>
                    <i />
                    <div><strong>{String(issue.tipo ?? "Inconsistência")}</strong><span>{String(issue.descricao ?? issue.mensagem ?? "Revisar registro")}</span></div>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
          ))}
          {renderBlock("chamadas", (
          <SectionCard
            title="Chamadas da gestão"
            action={<span className="section-count">{chamadas.length}</span>}
            navigation={{ label: "Abrir Chamadas da Gestão", onNavigate: () => navigate("/inicio/chamadas") }}
          >
            {chamadasQuery.loading && !chamadasQuery.data ? (
              <p className="chart-note">Carregando chamadas…</p>
            ) : chamadasQuery.error && !chamadasQuery.data ? (
              <p className="chart-note">Não foi possível carregar as chamadas agora.</p>
            ) : chamadas.length === 0 ? (
              <EmptyState title="Nenhuma chamada registrada" detail="Chamadas do operador e da gestão aparecem aqui." />
            ) : (
              <ul className="feed">
                {chamadas.slice(0, 4).map((item) => (
                  <li key={item.id}>
                    <span className="feed__dot" style={{ "--c": "var(--primary)" } as CSSProperties} aria-hidden="true">
                      {displayName(item.solicitante_nome, "?").slice(0, 2).toUpperCase()}
                    </span>
                    <span>
                      <strong>{displayName(item.motivo)}</strong> · {displayName(item.contato_nome)}
                      {item.comentario ? <small className="feed__detail">{item.comentario}</small> : null}
                    </span>
                    <span className="feed__time">{ago(item.criado_em)}</span>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
          ))}
          {renderBlock("metas", (
          <SectionCard
            title="Metas e atingimento"
            navigation={{ label: "Abrir Análises: OEE", onNavigate: () => navigateTo("/analises/oee") }}
          >
            {simulation ? (
              <div className="plan-actual-summary">
                <div><span>Quantidade planejada</span><strong>{simulation.planned_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Quantidade boa realizada</span><strong>{simulation.actual_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Atingimento</span><strong>{simulation.attainment_percentage === null ? "Não disponível" : `${simulation.attainment_percentage.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`}</strong></div>
                <div className="plan-actual-summary__progress"><i style={{ width: `${Math.min(100, simulation.attainment_percentage ?? 0)}%` }} /></div>
              </div>
            ) : (
              <EmptyState
                title="Sem meta definida"
                detail="O atingimento depende da meta do período; o planejamento consolidado continua no card Planejado × realizado."
              />
            )}
          </SectionCard>
          ))}
          {renderBlock("andon", (
          <SectionCard
            title="Alertas ao vivo"
            action={<span className="section-count">{andonStops.length} parada(s)</span>}
            navigation={{ label: "Abrir Andon", onNavigate: () => navigate("/andon") }}
          >
            {andonQuery.loading && !andon ? (
              <p className="chart-note">Carregando Andon…</p>
            ) : andonQuery.error && !andon ? (
              <p className="chart-note">O Andon não está disponível para esta conta ou o painel não respondeu.</p>
            ) : !andon ? (
              <EmptyState />
            ) : (
              <>
                <div className="metric-grid metric-grid--four">
                  <MetricCard label="Produzindo" value={String(andon.summary.production)} accent="success" />
                  <MetricCard label="Em parada" value={String(andon.summary.downtime)} accent="danger" />
                  <MetricCard label="Sem demanda" value={String(andon.summary.no_demand)} accent="teal" />
                  <MetricCard label="Fora de turno" value={String(andon.summary.out_of_shift)} accent="warning" />
                </div>
                {andonStops.length === 0 ? <EmptyState title="Nenhuma parada agora" /> : (
                  <ul className="feed">
                    {andonStops.map((resource) => (
                      <li key={`${resource.sector}-${resource.code}`}>
                        <span className="feed__dot" style={{ "--c": "var(--danger)" } as CSSProperties} aria-hidden="true">{resource.code.slice(0, 2).toUpperCase()}</span>
                        <span><strong>{displayName(resource.name)}</strong> · {displayText(resource.state.reason ?? resource.state.label)}</span>
                        <span className="feed__time">{formatHours(resource.state.duration_seconds ?? 0)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </SectionCard>
          ))}
        </div>
        {noneVisibleCustomBlock ? (
          <EmptyState title="Nenhum bloco visível na tela inicial" detail="Clique em Personalizar no cabeçalho para escolher o que deseja visualizar." />
        ) : null}
        <ManagementInsightDrawer explanation={selectedKpi} exception={null} onClose={closeInsight} onExplain={setExplainedMetric} />
        {explainedMetric ? <MetricExplanationPanel metric={explainedMetric} filters={filters.filters} onClose={closeExplanation} /> : null}
    </PageFrame>
  );
}
