import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ErrorState, LoadingState, EmptyState } from "../components/DataState";
import { ManagementInsightDrawer } from "../components/ManagementInsightDrawer";
import { MetricCard } from "../components/MetricCard";
import { PageFrame } from "../components/PageFrame";
import { SectionCard } from "../components/SectionCard";
import { useManagementFilters } from "../filters/FilterContext";
import { useApiQuery } from "../hooks/useApiQuery";
import type { KpiExplanation, ManagementException, ManagementOverview, MetricValue } from "../types/api";
import { formatHours } from "../utils/format";
import { humanizeSystemState } from "../utils/systemState";

function metricText(metric: MetricValue) {
  if (metric.value === null) return humanizeSystemState(metric.availability);
  const formatted = metric.value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
  return `${formatted}${metric.unit ?? ""}`;
}

function hours(seconds: number) {
  return `${(seconds / 3600).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} h`;
}

export function ManagementOverviewPage() {
  const filters = useManagementFilters();
  const navigate = useNavigate();
  const query = useApiQuery<ManagementOverview>(`/api/v1/management/overview?${filters.query}`);
  const [selectedKpi, setSelectedKpi] = useState<KpiExplanation | null>(null);
  const closeInsight = useCallback(() => {
    setSelectedKpi(null);
  }, []);

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
      return () => navigateTo("/inicio/metas");
    }
    return () => navigateTo("/analises/paradas", scopedFilters);
  };

  if (query.loading) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><LoadingState label="Carregando visão gerencial…" /></PageFrame>;
  if (query.error && !query.data) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  if (!query.data) return <PageFrame sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro."><EmptyState state="sem_registros" /></PageFrame>;

  const data = query.data;
  const kpis = data.kpis;
  const simulation = data.simulation;
  const insights = data.insights;
  const hasQuantityRecords = data.production.availability !== "sem_registros";
  const quantityText = (value: number) => hasQuantityRecords ? value.toLocaleString("pt-BR") : humanizeSystemState("sem_registros");
  return (
    <PageFrame staleError={query.error} sectionId="home" title="Tela inicial — Visão Geral" subtitle="Como estamos, onde estamos perdendo e onde agir primeiro.">
        <div className="metric-grid metric-grid--five">
          <MetricCard
            label="Produção boa"
            value={quantityText(data.production.good)}
            detail={data.production.reason ?? "Peças boas; refugo e retrabalho permanecem separados."}
            availability={data.production.availability}
          />
          <MetricCard label="OEE" value={metricText(kpis.oee)} detail={kpis.oee.reason ?? undefined} accent="purple" availability={kpis.oee.availability} actionLabel="Entender" onClick={() => setSelectedKpi(insights.kpi_explanations.oee)} />
          <MetricCard label="Disponibilidade" value={metricText(kpis.availability)} detail={kpis.availability.reason ?? undefined} accent="success" availability={kpis.availability.availability} actionLabel="Entender" onClick={() => setSelectedKpi(insights.kpi_explanations.availability)} />
          <MetricCard label="Performance" value={metricText(kpis.performance)} detail={kpis.performance.reason ?? undefined} accent="warning" availability={kpis.performance.availability} actionLabel="Entender" onClick={() => setSelectedKpi(insights.kpi_explanations.performance)} />
          <MetricCard label="FTT / Qualidade" value={metricText(kpis.ftt)} detail={kpis.ftt.reason ?? undefined} accent="teal" availability={kpis.ftt.availability} actionLabel="Entender" onClick={() => setSelectedKpi(insights.kpi_explanations.ftt)} />
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
        <div className="management-insight-grid">
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
                      aria-label={`Ver análise relacionada a ${exception.title}`}
                    >
                      <i data-severity={exception.severity} />
                      <span>
                        <strong>{exception.title}</strong>
                        <small>{exception.summary}</small>
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
          <SectionCard
            title="Maiores perdas"
            navigation={{ label: "Abrir análise das maiores perdas", onNavigate: () => navigateTo("/analises/paradas") }}
          >
            {insights.losses.length === 0 ? <EmptyState /> : (
              <ol className="management-impact-list">
                {insights.losses.slice(0, 4).map((item) => (
                  <li key={`${item.rank}-${item.cause}`}>
                    <button type="button" onClick={() => navigateTo("/analises/paradas")} aria-label={`Ver paradas por ${item.cause ?? "motivo não informado"}`}>
                      <span><b>{item.rank}</b><span>{item.cause ?? "Não informado"}</span></span>
                      <strong>{item.impact_unit === "s" ? formatHours(item.impact_value) : `${item.impact_value.toLocaleString("pt-BR")} ${item.impact_unit}`}</strong>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
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
                      <span><b>{item.rank}</b><span>{item.resource ?? "Não informado"}</span></span>
                      <strong>{item.impact_unit === "s" ? formatHours(item.impact_value) : `${item.impact_value.toLocaleString("pt-BR")} ${item.impact_unit}`}</strong>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
        </div>
        <div className="overview-grid">
          <SectionCard
            title="Planejado × realizado — acumulado"
            className="overview-grid__chart"
            navigation={{ label: "Abrir Produção: Planejado versus Realizado", onNavigate: () => navigateTo("/producao/planejado-realizado") }}
          >
            {simulation ? (
              <div className="plan-actual-summary">
                <div><span>Quantidade planejada</span><strong>{simulation.planned_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Quantidade boa realizada</span><strong>{simulation.actual_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div><span>Diferença</span><strong>{simulation.difference_quantity.toLocaleString("pt-BR")} peças</strong></div>
                <div className="plan-actual-summary__progress"><i style={{ width: `${Math.min(100, simulation.attainment_percentage ?? 0)}%` }} /></div>
              </div>
            ) : (
              <EmptyState
                title="Dados insuficientes"
                detail="O planejamento corporativo ainda não possui contrato confirmado para esta consolidação."
              />
            )}
          </SectionCard>
          <SectionCard
            title="Composição do tempo"
            navigation={{ label: "Abrir Consulta Operacional: Tempo MES", onNavigate: () => navigateTo("/consulta-operacional/tempo-mes") }}
          >
            {data.time_composition.availability === "sem_registros" ? (
              <EmptyState state={data.time_composition.availability} />
            ) : (
              <div className="time-composition">
                {data.time_composition.items.map((item) => (
                  <div key={item.source_field}>
                    <span>{item.label}</span>
                    <strong>{hours(item.seconds)}</strong>
                    <div><i style={{ width: `${item.percentage ?? 0}%` }} /></div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </div>
        <div className="overview-grid overview-grid--bottom">
          <SectionCard
            title="Setores — leitura rápida"
            className="overview-grid__table"
            navigation={{ label: "Abrir Consulta Operacional: Recursos", onNavigate: () => navigateTo("/consulta-operacional/recursos") }}
          >
            {data.sectors.length === 0 ? <EmptyState /> : (
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Setor</th><th>Produção boa</th><th>Refugo</th><th>Retrabalho</th><th>OPs</th><th>Tempo produtivo</th></tr></thead>
                  <tbody>
                    {data.sectors.map((sector) => (
                      <tr key={sector.setor}>
                        <th>{sector.setor}</th>
                        <td>{quantityText(sector.producao_boa)}</td>
                        <td>{quantityText(sector.refugo)}</td>
                        <td>{quantityText(sector.retrabalho)}</td>
                        <td>{sector.ops}</td>
                        <td>{hours(sector.tempo_produtivo_segundos)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
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
    </PageFrame>
  );
}
