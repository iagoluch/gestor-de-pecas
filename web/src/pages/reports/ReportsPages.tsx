import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { ExplainableValue } from "../../components/ExplainableValue";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { OverviewFilters } from "../../types/explanation";
import { formatAveragePerResource, formatHours, formatNumber, formatRecordedTimeDetail } from "../../utils/format";
import { humanizeSystemState } from "../../utils/systemState";

/** "producao" só existe para a exportação .xlsx usada por Produção > Produção realizada. */
export type ReportType = "gerencial" | "producao" | "perdas" | "indicadores" | "dados_analiticos";
type ReportPageType = Exclude<ReportType, "producao">;
type JsonRecord = Record<string, unknown>;

const labels: Record<ReportPageType, { title: string; subtitle: string; tab: string }> = {
  gerencial: { tab: "Gerencial", title: "Relatórios — Gerencial", subtitle: "Resumo executivo a partir das mesmas fontes das telas gerenciais." },
  perdas: { tab: "Perdas", title: "Relatórios — Perdas", subtitle: "Paradas e qualidade sem conversão silenciosa de ausência em zero." },
  indicadores: { tab: "Indicadores", title: "Relatórios — Indicadores", subtitle: "Indicadores com disponibilidade e justificativa explícitas." },
  dados_analiticos: { tab: "Dados analíticos", title: "Relatórios — Dados analíticos", subtitle: "Conjunto analítico para conferência e exportação, sem editar a origem." },
};

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function rows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => Boolean(item && typeof item === "object" && !Array.isArray(item))) : [];
}

function numeric(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function metricValue(value: unknown) {
  const item = record(value);
  if (item.value === null || item.value === undefined) {
    return humanizeSystemState(item.availability ?? "dados_insuficientes", { fallback: "Dados insuficientes" });
  }
  return `${formatNumber(numeric(item.value), 1)}${String(item.unit ?? "")}`;
}

function productionValue(production: JsonRecord, field: string) {
  return production.availability === "sem_registros"
    ? humanizeSystemState("sem_registros")
    : formatNumber(numeric(production[field]));
}

/**
 * Valor com a conta aberta. O número do relatório vem da mesma fonte da explicação (`qtd.*`, `qld.*`, `kpi.*`);
 * só vira clicável o que tem algo para explicar: zero, ausência e texto de estado ficam simples.
 */
function explained(filters: OverviewFilters, metric: string, label: string, value: unknown, text: string, sector?: string) {
  const amount = numeric(value);
  if (amount === null || amount <= 0) return undefined;
  return (
    <ExplainableValue metric={metric} filters={sector ? { ...filters, sector } : filters} context={`${label}${sector ? ` em ${sector}` : ""} ${text}`}>{text}</ExplainableValue>
  );
}

/** Célula de setor: clicável só com setor nomeado ("Não disponível"/"Não informado" não existe como filtro). */
function sectorValue(filters: OverviewFilters, metric: string, label: string, row: JsonRecord, field: string) {
  const text = formatNumber(numeric(row[field]));
  const sector = typeof row.setor === "string" ? row.setor.trim() : "";
  if (!sector || /^nao[_ ]informado$/i.test(sector.normalize("NFD").replace(/[̀-ͯ]/g, ""))) return text;
  return explained(filters, metric, label, row[field], text, sector) ?? text;
}

export function DownloadAction({ type, query }: { type: ReportType; query: string }) {
  const [error, setError] = useState<string | null>(null);

  async function exportXlsx(modo: "tecnico" | "simples") {
    setError(null);
    try {
      await api.download(
        `/api/v1/reports/${type}/export.xlsx?${query}&modo=${modo}`,
        `relatorio_${type}_${modo}.xlsx`,
      );
    } catch (reason) {
      setError(`Não foi possível gerar o Excel. ${apiErrorMessage(reason)}`);
    }
  }

  return (
    <div className="download-action">
      <div className="download-action__buttons">
        <AsyncButton className="button button--primary" pendingLabel="Gerando…" title="Baixar em Excel (.xlsx)" onClick={() => exportXlsx("tecnico")}>Export técnico</AsyncButton>
        <AsyncButton className="button button--primary" pendingLabel="Gerando…" title="Baixar em Excel (.xlsx)" onClick={() => exportXlsx("simples")}>Export simples</AsyncButton>
      </div>
      {error ? <span role="alert" className="download-action__error">{error}</span> : null}
    </div>
  );
}

function ReportContent({ type, payload, filters }: { type: ReportPageType; payload: JsonRecord; filters: OverviewFilters }) {
  if (type === "gerencial") {
    const overview = record(payload.overview);
    const production = record(overview.production);
    const kpis = record(overview.kpis);
    return <>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={productionValue(production, "good")} valueNode={explained(filters, "qtd.boa", "Produção boa", production.good, productionValue(production, "good"))} detail={String(production.reason ?? "")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="success" />
        <MetricCard label="Refugo" value={productionValue(production, "scrap")} valueNode={explained(filters, "qtd.refugo", "Refugo", production.scrap, productionValue(production, "scrap"))} availability={String(production.availability ?? "dados_insuficientes") as never} accent="danger" />
        <MetricCard label="Retrabalho" value={productionValue(production, "rework")} valueNode={explained(filters, "qtd.retrabalho", "Retrabalho", production.rework, productionValue(production, "rework"))} availability={String(production.availability ?? "dados_insuficientes") as never} accent="warning" />
        <MetricCard label="OEE" value={metricValue(kpis.oee)} valueNode={explained(filters, "kpi.oee", "OEE", record(kpis.oee).value, metricValue(kpis.oee))} detail={String(record(kpis.oee).reason ?? "")} accent="purple" availability={String(record(kpis.oee).availability ?? "dados_insuficientes") as never} />
      </div>
      <SectionCard title="Setores" className="content-section section-card--table">
        <DataTable rows={rows(overview.sectors)} rowKey={(row, index) => String(row.setor ?? index)} columns={[
          { key: "sector", label: "Setor", render: (row) => String(row.setor ?? "Não disponível") },
          { key: "good", label: "Produção boa", render: (row) => sectorValue(filters, "qtd.boa", "Produção boa", row, "producao_boa") },
          { key: "scrap", label: "Refugo", render: (row) => sectorValue(filters, "qtd.refugo", "Refugo", row, "refugo") },
          { key: "rework", label: "Retrabalho", render: (row) => sectorValue(filters, "qtd.retrabalho", "Retrabalho", row, "retrabalho") },
          { key: "production", label: "Tempo produtivo", render: (row) => formatHours(numeric(row.tempo_produtivo_segundos)) },
        ]} />
      </SectionCard>
    </>;
  }
  if (type === "perdas") {
    const downtimes = record(payload.paradas);
    const quality = record(payload.qualidade);
    const totals = record(quality.totals);
    return <>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Tempo de parada" value={formatHours(numeric(downtimes.total_seconds))} detail={formatAveragePerResource(numeric(downtimes.total_seconds), rows(downtimes.by_resource).length)} accent="danger" />
        <MetricCard label="Ocorrências" value={formatNumber(numeric(downtimes.count))} accent="warning" />
        <MetricCard label="Refugo" value={formatNumber(numeric(totals.refugo))} valueNode={explained(filters, "qld.refugo", "Refugo", totals.refugo, formatNumber(numeric(totals.refugo)))} accent="danger" />
        <MetricCard label="Retrabalho" value={formatNumber(numeric(totals.retrabalho))} valueNode={explained(filters, "qld.retrabalho", "Retrabalho", totals.retrabalho, formatNumber(numeric(totals.retrabalho)))} accent="warning" />
      </div>
      <SectionCard title="Paradas por motivo" className="content-section section-card--table">
        <DataTable rows={rows(downtimes.by_reason)} rowKey={(row, index) => String(row.motivo ?? index)} columns={[
          { key: "reason", label: "Motivo", render: (row) => String(row.motivo ?? "Não informado") },
          { key: "time", label: "Tempo", render: (row) => formatHours(numeric(row.segundos ?? row.seconds)) },
        ]} />
      </SectionCard>
    </>;
  }
  if (type === "indicadores") {
    const analytics = record(payload.analytics);
    const oee = record(analytics.oee);
    const quality = record(analytics.qualidade);
    const ftt = record(quality.ftt);
    const time = record(analytics.tempos);
    return <>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="OEE" value={metricValue(oee)} valueNode={explained(filters, "kpi.oee", "OEE", oee.value, metricValue(oee))} detail={String(oee.reason ?? "")} accent="purple" availability={String(oee.availability ?? "nao_configurado") as never} />
        <MetricCard label="FTT" value={metricValue(ftt)} valueNode={explained(filters, "qtd.ftt", "FTT", ftt.value, metricValue(ftt))} detail={String(ftt.reason ?? "")} accent="teal" availability={String(ftt.availability ?? "dados_insuficientes") as never} />
        <MetricCard label="Tempo registrado" value={formatHours(numeric(time.physical_seconds))} detail={formatRecordedTimeDetail(numeric(time.physical_seconds), rows(time.by_resource).length)} accent="success" />
        <MetricCard label="Utilização" value={record(analytics.capacidade).utilizacao_percentual == null ? humanizeSystemState(record(analytics.capacidade).availability ?? "dados_insuficientes", { fallback: "Dados insuficientes" }) : `${formatNumber(numeric(record(analytics.capacidade).utilizacao_percentual), 1)}%`} detail={String(record(analytics.capacidade).reason ?? "")} accent="warning" />
      </div>
      <SectionCard title="Confiabilidade e capacidade" className="content-section">
        <div className="quality-summary">
          <div><span>MTBF</span><strong>{record(analytics.confiabilidade).mtbf_segundos == null ? "Não disponível" : formatHours(numeric(record(analytics.confiabilidade).mtbf_segundos))}</strong></div>
          <div><span>MTTR</span><strong>{record(analytics.confiabilidade).mttr_segundos == null ? "Não disponível" : formatHours(numeric(record(analytics.confiabilidade).mttr_segundos))}</strong></div>
          <div><span>Quebras no período</span><strong>{formatNumber(numeric(record(analytics.confiabilidade).falhas))}</strong></div>
          <div><span>Utilização</span><strong>{record(analytics.capacidade).utilizacao_percentual == null ? "Não configurado" : `${formatNumber(numeric(record(analytics.capacidade).utilizacao_percentual), 1)}%`}</strong></div>
        </div>
      </SectionCard>
    </>;
  }
  const orders = record(payload.orders);
  const audit = record(payload.audit);
  const nestings = record(payload.nestings);
  return <>
    <div className="metric-grid metric-grid--four">
      <MetricCard label="Ordens" value={formatNumber(rows(orders.items).length)} />
      <MetricCard label="Inconsistências" value={formatNumber(numeric(audit.count))} valueNode={explained(filters, "qld.auditoria.total", "Inconsistências", audit.count, formatNumber(numeric(audit.count)))} accent="danger" />
      <MetricCard label="Nestings" value={formatNumber(numeric(nestings.count))} accent="purple" />
      <MetricCard label="Período" value={String(record(payload.periodo).inicio ?? "").slice(0, 10) || "Filtro atual"} detail={`até ${String(record(payload.periodo).fim ?? "").slice(0, 10) || "hoje"}`} accent="teal" />
    </div>
    <SectionCard title="Ordens — dados analíticos" className="content-section section-card--table">
      <DataTable rows={rows(orders.items)} rowKey={(row, index) => String(row.apontamento_id ?? index)} columns={[
        { key: "op", label: "OP", render: (row) => String(row.op ?? "Não disponível") },
        { key: "product", label: "Produto", render: (row) => String(row.produto ?? "Não disponível") },
        { key: "operation", label: "Operação", render: (row) => String(row.operacao_atual ?? "Não disponível") },
        { key: "sector", label: "Setor", render: (row) => String(row.setor ?? "Não disponível") },
        { key: "resource", label: "Recurso", render: (row) => String(row.recurso_real ?? "Não disponível") },
        { key: "good", label: "Boas", render: (row) => formatNumber(numeric(row.quantidade_boa)) },
        { key: "scrap", label: "Refugo", render: (row) => formatNumber(numeric(row.refugo)) },
        { key: "status", label: "Status", render: (row) => String(row.status ?? "Não disponível") },
      ]} />
    </SectionCard>
  </>;
}

const REPORT_TYPES: ReportPageType[] = ["gerencial", "perdas", "indicadores", "dados_analiticos"];

/** Uma aba só: o tipo do relatório vem de `?tipo=` (as rotas antigas /relatorios/<tipo> redirecionam para cá). */
export function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const type = REPORT_TYPES.find((item) => item === params.get("tipo")) ?? "gerencial";
  const filters = useManagementFilters();
  const query = useApiQuery<JsonRecord>(`/api/v1/reports/${type}?${filters.query}`);
  const copy = labels[type];
  const action = <DownloadAction type={type} query={filters.query} />;
  const selector = (
    <div className="segment-toggle" role="tablist" aria-label="Tipo de relatório">
      {REPORT_TYPES.map((item) => {
        const active = item === type;
        return <button key={item} type="button" role="tab" aria-selected={active} className={`segment-toggle__btn${active ? " segment-toggle__btn--active" : ""}`} onClick={() => setParams({ tipo: item }, { replace: true })}>{labels[item].tab}</button>;
      })}
    </div>
  );
  if (query.loading) return <PageFrame sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={action}>{selector}<LoadingState /></PageFrame>;
  if (query.error && !query.data) return <PageFrame sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={action}>{selector}<ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  return <PageFrame staleError={query.error} sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={action}>{selector}{query.data ? <ReportContent type={type} payload={query.data} filters={filters.filters} /> : <EmptyState />}</PageFrame>;
}
