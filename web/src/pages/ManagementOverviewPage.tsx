import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LineChart, Sparkline, StackBar } from "../components/charts";
import { ErrorState, LoadingState, EmptyState } from "../components/DataState";
import { ManagementInsightDrawer } from "../components/ManagementInsightDrawer";
import { MetricCard } from "../components/MetricCard";
import { MetricExplanationPanel } from "../components/MetricExplanationPanel";
import { PageFrame } from "../components/PageFrame";
import { SectionCard } from "../components/SectionCard";
import { useManagementFilters } from "../filters/FilterContext";
import { useApiQuery } from "../hooks/useApiQuery";
import { explainableComposition } from "../types/explanation";
import type { KpiExplanation, ManagementException, ManagementOverview, MetricValue, OverviewTrend, OverviewTrendPoint } from "../types/api";
import { displayName, displayText, formatHours } from "../utils/format";
import { humanizeSystemState } from "../utils/systemState";

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
 * Complemento de cada linha da composição. A média vem pronta do backend
 * (total ÷ recursos com turno) e sempre diz quantos recursos; sem média, só
 * quem fica fora do total ganha "não somado".
 */
function averageHint(item: { summed?: boolean; average_seconds?: number | null }, resourceCount: number) {
  if (item.average_seconds != null && resourceCount > 0) {
    return `média ${hours(item.average_seconds)} (${resourceCount} ${resourceCount === 1 ? "recurso" : "recursos"})`;
  }
  return item.summed === false ? "não somado" : undefined;
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

export function ManagementOverviewPage() {
  const filters = useManagementFilters();
  const navigate = useNavigate();
  const query = useApiQuery<ManagementOverview>(`/api/v1/management/overview?${filters.query}`);
  // Série para gráficos/sparklines: opcional — se falhar ou demorar, a página inteira continua igual.
  const trendQuery = useApiQuery<OverviewTrend>(`/api/v1/management/overview/trend?${filters.query}`, { ignoreLiveTick: true });
  const trend = trendQuery.data && Array.isArray(trendQuery.data.points) && trendQuery.data.availability !== "sem_registros" ? trendQuery.data : null;
  const [selectedKpi, setSelectedKpi] = useState<KpiExplanation | null>(null);
  const closeInsight = useCallback(() => {
    setSelectedKpi(null);
  }, []);
  // Painel "de onde vem este número" (composição do tempo): guarda só o id da métrica.
  const [explainedMetric, setExplainedMetric] = useState<string | null>(null);
  const closeExplanation = useCallback(() => setExplainedMetric(null), []);

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
  const composition = explainableComposition(data.time_composition);
  const kpis = data.kpis;
  const simulation = data.simulation;
  const insights = data.insights;
  const hasQuantityRecords = data.production.availability !== "sem_registros";
  // GE-13: sem fonte de metas o backend avisa em `limitations`; o card diz isso
  // em vez de deixar o percentual solto. Com metas, o desvio vira exceção.
  const targetNote = insights.limitations.some((item) => item.code === "kpi_targets_not_configured") ? "Sem meta definida" : undefined;
  const kpiCards = [
    { key: "oee", label: "OEE", accent: "purple" },
    { key: "availability", label: "Disponibilidade", accent: "success" },
    { key: "performance", label: "Performance", accent: "warning" },
    { key: "ftt", label: "FTT / Qualidade", accent: "teal" },
  ] as const;
  const sparkOf = (pick: (point: OverviewTrendPoint) => number | null, color: string) => (trend && trend.points.length > 1 ? <Sparkline values={trend.points.map(pick)} color={color} /> : null);
  const plannedSeries = trend && trend.points.length > 1 && trend.points.every((point) => point.planned_quantity !== null) ? trend.points.map((point) => point.planned_quantity) : null;
  const sectorSummary = new Map((trend?.sector_summary ?? []).map((item) => [item.setor, item]));
  // Período ainda em andamento (ex.: "Hoje" às 10h): comparar peças com o período anterior inteiro daria queda falsa.
  const lastPoint = trend?.points[trend.points.length - 1];
  const periodOpen = lastPoint ? new Date(lastPoint.period_end).getTime() > Date.now() : false;
  const quantityText = (value: number) => hasQuantityRecords ? value.toLocaleString("pt-BR") : humanizeSystemState("sem_registros");
  return (
    <PageFrame staleError={query.error} sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro.">
        <div className="metric-grid metric-grid--five">
          <MetricCard
            label="Produção boa"
            value={quantityText(data.production.good)}
            detail={data.production.reason ?? "Peças boas; refugo e retrabalho permanecem separados."}
            availability={data.production.availability}
            trend={trend && hasQuantityRecords && !periodOpen ? quantityTrend(data.production.good, trend.previous?.production.good) : undefined}
            spark={hasQuantityRecords ? sparkOf((point) => point.production.good, SERIES_COLORS.good) : null}
          />
          {kpiCards.map((card) => (
            <MetricCard
              key={card.key}
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
          ))}
        </div>
        {simulation ? (
          <div className="metric-grid metric-grid--six simulation-metrics">
            <MetricCard label="Planejado" value={simulation.planned_quantity.toLocaleString("pt-BR")} detail="Peças no período" />
            <MetricCard label="Realizado" value={simulation.actual_quantity.toLocaleString("pt-BR")} detail="Somente peças boas" accent="success" />
            <MetricCard label="Atingimento" value={simulation.attainment_percentage === null ? "Não disponível" : `${simulation.attainment_percentage.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`} accent="teal" />
            <MetricCard label="Utilização" value={metricText(simulation.metrics.utilization)} accent="warning" />
            <MetricCard label="Produtividade" value={metricText(simulation.metrics.productivity)} accent="purple" />
            <MetricCard label="AE" value={metricText(simulation.metrics.ae)} detail="Eficiência global efetiva" />
          </div>
        ) : null}
        <div className="overview-grid">
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
        </div>
        <div className="management-insight-grid management-insight-grid--three">
          <SectionCard
            title="Composição do tempo"
            navigation={{ label: "Abrir Consulta Operacional: Tempo MES", onNavigate: () => navigateTo("/consulta-operacional/tempo-mes") }}
          >
            {composition.availability === "sem_registros" ? (
              <EmptyState state={composition.availability} />
            ) : (
              <div className="time-composition">
                <div className="time-composition__total">
                  <strong>{hours(composition.total_seconds)}</strong>
                  <span>{(composition.resource_count ?? 0) > 1 ? `somado em ${composition.resource_count} recursos` : "no período"}</span>
                </div>
                {composition.average_note ? <p className="time-composition__note">{composition.average_note}</p> : null}
                <StackBar
                  parts={composition.items.map((item) => ({
                    name: item.label,
                    value: item.seconds,
                    color: TIME_COLORS[item.source_field] ?? "var(--muted)",
                    outside: item.summed === false,
                    text: hours(item.seconds),
                    hint: averageHint(item, composition.resource_count ?? 0),
                    ...(item.metric ? { explainMetric: item.metric, onSelect: () => setExplainedMetric(item.metric ?? null) } : {}),
                  }))}
                />
              </div>
            )}
          </SectionCard>
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
        </div>
        <div className="overview-grid overview-grid--single">
          <SectionCard
            title="Setores — leitura rápida"
            className="overview-grid__table"
            navigation={{ label: "Abrir Consulta Operacional: Recursos", onNavigate: () => navigateTo("/consulta-operacional/recursos") }}
          >
            {data.sectors.length === 0 ? <EmptyState /> : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Setor</th>{trend ? <th>OEE</th> : null}{trend ? <th>Recursos produzindo</th> : null}<th>Produção boa</th><th>Refugo</th><th>Retrabalho</th><th>OPs</th><th>Tempo produtivo</th>{trend ? <th>Tendência</th> : null}</tr></thead>
                  <tbody>
                    {data.sectors.map((sector) => {
                      const summary = sectorSummary.get(sector.setor);
                      const oee = data.sector_kpis?.find((item) => item.setor === sector.setor)?.metrics.oee?.value ?? null;
                      return (
                        <tr key={sector.setor}>
                          <th>{displayName(sector.setor)}</th>
                          {trend ? (
                            <td>
                              {oee === null ? "—" : (
                                <span className="sector-oee"><span><i style={{ "--w": `${Math.min(100, oee)}%`, "--c": "var(--purple)" } as React.CSSProperties} /></span><b>{oee.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%</b></span>
                              )}
                            </td>
                          ) : null}
                          {trend ? <td>{summary && summary.resources_total > 0 ? `${summary.resources_with_production} de ${summary.resources_total}` : "—"}</td> : null}
                          <td>{quantityText(sector.producao_boa)}</td>
                          <td>{quantityText(sector.refugo)}</td>
                          <td>{quantityText(sector.retrabalho)}</td>
                          <td>{sector.ops}</td>
                          <td>{hours(sector.tempo_produtivo_segundos)}</td>
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
            )}
          </SectionCard>
        </div>
        <div className="management-insight-grid management-insight-grid--two">
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
          <SectionCard
            title="Inconsistências de dados"
            navigation={{ label: "Abrir Auditoria: Inconsistências", onNavigate: () => navigateTo("/auditoria/inconsistencias") }}
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
        </div>
        <ManagementInsightDrawer explanation={selectedKpi} exception={null} onClose={closeInsight} />
        {explainedMetric ? <MetricExplanationPanel metric={explainedMetric} filters={filters.filters} onClose={closeExplanation} /> : null}
    </PageFrame>
  );
}
