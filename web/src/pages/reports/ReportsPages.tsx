import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { formatHours, formatNumber } from "../../utils/format";
import { humanizeSystemState } from "../../utils/systemState";

type ReportType = "gerencial" | "producao" | "perdas" | "indicadores" | "dados_analiticos";
type JsonRecord = Record<string, unknown>;

const labels: Record<ReportType, { title: string; subtitle: string }> = {
  gerencial: { title: "Relatórios — Relatório Gerencial", subtitle: "Resumo executivo a partir das mesmas fontes das telas gerenciais." },
  producao: { title: "Relatórios — Produção", subtitle: "Produção boa, refugo e retrabalho preservados em campos independentes." },
  perdas: { title: "Relatórios — Perdas", subtitle: "Paradas e qualidade sem conversão silenciosa de ausência em zero." },
  indicadores: { title: "Relatórios — Indicadores", subtitle: "Indicadores com disponibilidade e justificativa explícitas." },
  dados_analiticos: { title: "Relatórios — Dados Analíticos", subtitle: "Conjunto analítico para conferência e exportação, sem editar a origem." },
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

function DownloadAction({ type, query }: { type: ReportType; query: string }) {
  return <a className="button button--primary" href={`/api/v1/reports/${type}/export.xlsx?${query}`} title="Baixar em Excel (.xlsx)" download>Exportar</a>;
}

function ReportContent({ type, payload }: { type: ReportType; payload: JsonRecord }) {
  if (type === "gerencial") {
    const overview = record(payload.overview);
    const production = record(overview.production);
    const kpis = record(overview.kpis);
    return <>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={productionValue(production, "good")} detail={String(production.reason ?? "")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="success" />
        <MetricCard label="Refugo" value={productionValue(production, "scrap")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="danger" />
        <MetricCard label="Retrabalho" value={productionValue(production, "rework")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="warning" />
        <MetricCard label="OEE" value={metricValue(kpis.oee)} detail={String(record(kpis.oee).reason ?? "")} accent="purple" availability={String(record(kpis.oee).availability ?? "dados_insuficientes") as never} />
      </div>
      <SectionCard title="Setores" className="content-section section-card--table">
        <DataTable rows={rows(overview.sectors)} rowKey={(row, index) => String(row.setor ?? index)} columns={[
          { key: "sector", label: "Setor", render: (row) => String(row.setor ?? "Não disponível") },
          { key: "good", label: "Produção boa", render: (row) => formatNumber(numeric(row.producao_boa)) },
          { key: "scrap", label: "Refugo", render: (row) => formatNumber(numeric(row.refugo)) },
          { key: "rework", label: "Retrabalho", render: (row) => formatNumber(numeric(row.retrabalho)) },
          { key: "production", label: "Tempo produtivo", render: (row) => formatHours(numeric(row.tempo_produtivo_segundos)) },
        ]} />
      </SectionCard>
    </>;
  }
  if (type === "producao") {
    const production = record(payload.production);
    const quality = record(payload.quality);
    return <>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={productionValue(production, "good")} detail={String(production.reason ?? "")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="success" />
        <MetricCard label="Refugo" value={productionValue(production, "scrap")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="danger" />
        <MetricCard label="Retrabalho" value={productionValue(production, "rework")} availability={String(production.availability ?? "dados_insuficientes") as never} accent="warning" />
        <MetricCard label="OPs" value={formatNumber(numeric(production.ops))} />
      </div>
      <SectionCard title="Produção por setor" className="content-section section-card--table">
        <DataTable rows={rows(payload.sectors)} rowKey={(row, index) => String(row.setor ?? index)} columns={[
          { key: "sector", label: "Setor", render: (row) => String(row.setor ?? "Não disponível") },
          { key: "good", label: "Boas", render: (row) => formatNumber(numeric(row.producao_boa)) },
          { key: "scrap", label: "Refugo", render: (row) => formatNumber(numeric(row.refugo)) },
          { key: "rework", label: "Retrabalho", render: (row) => formatNumber(numeric(row.retrabalho)) },
          { key: "quality", label: "Fonte de qualidade", render: () => String(quality.reason ?? "Não disponível") },
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
        <MetricCard label="Tempo de parada" value={formatHours(numeric(downtimes.total_seconds))} accent="danger" />
        <MetricCard label="Ocorrências" value={formatNumber(numeric(downtimes.count))} accent="warning" />
        <MetricCard label="Refugo" value={formatNumber(numeric(totals.refugo))} accent="danger" />
        <MetricCard label="Retrabalho" value={formatNumber(numeric(totals.retrabalho))} accent="warning" />
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
        <MetricCard label="OEE" value={metricValue(oee)} detail={String(oee.reason ?? "")} accent="purple" availability={String(oee.availability ?? "nao_configurado") as never} />
        <MetricCard label="FTT" value={metricValue(ftt)} detail={String(ftt.reason ?? "")} accent="teal" availability={String(ftt.availability ?? "dados_insuficientes") as never} />
        <MetricCard label="Tempo físico" value={formatHours(numeric(time.physical_seconds))} accent="success" />
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
      <MetricCard label="Inconsistências" value={formatNumber(numeric(audit.count))} accent="danger" />
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

function ReportPage({ type }: { type: ReportType }) {
  const filters = useManagementFilters();
  const query = useApiQuery<JsonRecord>(`/api/v1/reports/${type}?${filters.query}`);
  const copy = labels[type];
  if (query.loading) return <PageFrame sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={<DownloadAction type={type} query={filters.query} />}><LoadingState /></PageFrame>;
  if (query.error && !query.data) return <PageFrame sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={<DownloadAction type={type} query={filters.query} />}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  return <PageFrame staleError={query.error} sectionId="reports" title={copy.title} subtitle={copy.subtitle} actions={<DownloadAction type={type} query={filters.query} />}>{query.data ? <ReportContent type={type} payload={query.data} /> : <EmptyState />}</PageFrame>;
}

export const ManagementReportPage = () => <ReportPage type="gerencial" />;
export const ProductionReportPage = () => <ReportPage type="producao" />;
export const LossesReportPage = () => <ReportPage type="perdas" />;
export const IndicatorsReportPage = () => <ReportPage type="indicadores" />;
export const AnalyticalDataReportPage = () => <ReportPage type="dados_analiticos" />;
