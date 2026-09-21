import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BarList } from "../../components/BarList";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { ResourceCard } from "../../components/ResourceCard";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useOperationsStream } from "../../hooks/useOperationsStream";
import { localDate, referenceNow, useReferenceClock } from "../../system/ReferenceClock";
import type { OperationsOverview, PagedOrders, ResourceRow, TimeBreakdown } from "../../types/management";
import { formatDateTime, formatDuration, formatHours, formatNumber, formatPercent, formatResourceName, humanize } from "../../utils/format";

interface ResourceSummary {
  resources: number;
  active_operations: number;
  by_category: Record<string, number>;
  longest_stop?: { resource?: string | null; sector?: string | null; reason?: string | null; seconds?: number } | null;
}

interface ResourcePage {
  periodo: Record<string, string | null>;
  agora: string;
  summary?: ResourceSummary;
  items: ResourceRow[];
  page: { total: number; page: number; page_size: number; pages: number };
}

function stoppedCount(summary?: ResourceSummary) {
  return summary?.by_category.parada ?? 0;
}

function producingCount(summary?: ResourceSummary) {
  return (summary?.by_category.producao ?? 0) + (summary?.by_category["produção"] ?? 0);
}

function LoadingPage({ title, subtitle, period = true, filters = true }: { title: string; subtitle: string; period?: boolean; filters?: boolean }) {
  return <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={period} filters={filters}><LoadingState /></PageFrame>;
}

export function OperationsOverviewPage() {
  // Visão geral não usa o filtro compartilhado entre sub-abas: ela sempre
  // mostra o dia corrente completo, e o próprio setor é escolhido abaixo, no
  // seletor local de "Recursos por estado" — um filtro mestre aqui só
  // duplicaria esse seletor e arriscaria esconder dados por um filtro
  // deixado ligado em outra sub-aba.
  const { reference } = useReferenceClock();
  const today = localDate(referenceNow(reference));
  const dailyQuery = new URLSearchParams({ inicio: `${today}T00:00:00`, fim: `${today}T23:59:59` }).toString();
  const query = useApiQuery<OperationsOverview>(`/api/v1/operations/overview?${dailyQuery}`);
  const stream = useOperationsStream(dailyQuery);
  const [selectedSector, setSelectedSector] = useState("");
  const title = "Consulta Operacional — Visão Geral";
  const subtitle = "Situação física atual dos recursos e OPs associadas no dia corrente, com atualização incremental.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} period={false} filters={false} />;
  if (query.error) return <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false} filters={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  if (!data) return <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false} filters={false}><EmptyState /></PageFrame>;
  const resources = stream.snapshot?.resources ?? data.resources;
  const summary: ResourceSummary = data.summary ?? { resources: resources.length, active_operations: 0, by_category: {} };
  const sectors = [...new Set(resources.map((resource) => resource.setor ?? "Setor não informado"))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const activeSector = sectors.includes(selectedSector) ? selectedSector : sectors[0] ?? "";
  const sectorResources = resources.filter((resource) => (resource.setor ?? "Setor não informado") === activeSector);
  return (
    <PageFrame
      sectionId="operations"
      title={title}
      subtitle={subtitle}
      period={false}
      filters={false}
      actions={<span className={`live-indicator ${stream.connected ? "live-indicator--connected" : ""}`}><i />{stream.connected ? "Atualização ao vivo" : "Reconectando atualizações"}</span>}
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Em produção agora" value={`${formatNumber(producingCount(summary))} de ${formatNumber(summary.resources)}`} detail="Recursos com estado produtivo" accent="success" />
        <MetricCard label="OPs em execução" value={formatNumber(summary.active_operations)} accent="primary" />
        <MetricCard label="Recursos parados" value={formatNumber(stoppedCount(summary))} detail={stoppedCount(summary) ? "Exigem ação imediata" : "Nenhuma parada aberta"} accent={stoppedCount(summary) ? "danger" : "success"} />
        <MetricCard
          label="Maior parada aberta"
          value={summary.longest_stop ? formatDuration(summary.longest_stop.seconds) : "Nenhuma"}
          detail={summary.longest_stop ? `${formatResourceName(summary.longest_stop.resource)} — ${summary.longest_stop.reason ?? "motivo não informado"}` : undefined}
          accent={summary.longest_stop ? "warning" : "success"}
          availability={summary.longest_stop ? "disponivel" : "sem_registros"}
        />
      </div>
      <SectionCard
        title="Recursos por estado"
        className="content-section"
        action={sectors.length > 1 ? (
          <label className="resource-sector-select">
            <span>Setor</span>
            <select value={activeSector} onChange={(event) => setSelectedSector(event.target.value)} aria-label="Selecionar setor">
              {sectors.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
            </select>
          </label>
        ) : undefined}
      >
        {resources.length ? <div className="resource-grid">{sectorResources.map((resource) => <ResourceCard key={`${resource.setor}-${resource.recurso}`} resource={resource} />)}</div> : <EmptyState />}
      </SectionCard>
    </PageFrame>
  );
}

export function OperationsResourcesPage() {
  const filters = useManagementFilters();
  const [params] = useSearchParams();
  const sector = params.get("setor");
  const queryText = sector ? `${filters.dailyQuery}&setor=${encodeURIComponent(sector)}` : filters.dailyQuery;
  const query = useApiQuery<ResourcePage>(`/api/v1/operations/resources?${queryText}&page=1&page_size=200`);
  const title = "Consulta Operacional — Recursos";
  const subtitle = "Estado, OP, operador e duração por recurso físico no dia corrente.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} period={false} />;
  if (query.error) return <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  return (
    <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Recursos no filtro" value={formatNumber(data?.page.total ?? 0)} />
        <MetricCard label="Em produção agora" value={formatNumber(producingCount(data?.summary))} accent="success" />
        <MetricCard label="Parados" value={formatNumber(stoppedCount(data?.summary))} detail={stoppedCount(data?.summary) ? "Verifique o motivo na tabela" : "Nenhuma parada aberta"} accent={stoppedCount(data?.summary) ? "danger" : "success"} />
        <MetricCard
          label="Maior parada aberta"
          value={data?.summary?.longest_stop ? formatDuration(data.summary.longest_stop.seconds) : "Nenhuma"}
          detail={data?.summary?.longest_stop ? `${formatResourceName(data.summary.longest_stop.resource)} — ${data.summary.longest_stop.reason ?? "motivo não informado"}` : `Atualizado em ${formatDateTime(data?.agora)}`}
          accent={data?.summary?.longest_stop ? "warning" : "teal"}
          availability={data?.summary?.longest_stop ? "disponivel" : "sem_registros"}
        />
      </div>
      <SectionCard title="Recursos" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row) => row.estado_recurso_id ?? `${row.setor}-${row.recurso}`}
          columns={[
            { key: "resource", label: "Recurso", render: (row) => <strong>{formatResourceName(row.recurso_nome ?? row.recurso)}</strong> },
            { key: "sector", label: "Setor", render: (row) => row.setor ?? "Não disponível" },
            { key: "state", label: "Estado", render: (row) => <StatusBadge value={row.categoria ?? row.codigo_status} /> },
            { key: "op", label: "OP", render: (row) => row.ops_ativas[0]?.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.ops_ativas[0].op!)}`}>{row.ops_ativas[0].op}</Link> : "Não disponível" },
            { key: "product", label: "Produto", render: (row) => row.ops_ativas[0]?.produto ?? "Não disponível" },
            { key: "operator", label: "Operador", render: (row) => row.ops_ativas[0]?.operador_inicio ?? "Não disponível" },
            { key: "start", label: "Início", render: (row) => formatDateTime(row.inicio) },
            { key: "duration", label: "Duração", render: (row) => formatDuration(row.duracao_segundos) },
            { key: "reason", label: "Motivo", render: (row) => row.motivo ?? "Não disponível" },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function OperationsOrdersPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<PagedOrders>(`/api/v1/operations/orders?${filters.dailyQuery}&page=1&page_size=200`);
  const title = "Consulta Operacional — OPs em Andamento";
  const subtitle = "Execuções do dia corrente, mantendo quantidade boa, refugo e retrabalho separados.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} period={false} />;
  if (query.error) return <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  // Somatório de linhas já entregues pelo backend: apresentação, não regra.
  const totals = rows.reduce(
    (acc, row) => ({
      good: acc.good + Number(row.quantidade_boa ?? 0),
      scrap: acc.scrap + Number(row.refugo ?? 0),
      stopped: acc.stopped + (String(row.status ?? "") === "Parada" ? 1 : 0),
    }),
    { good: 0, scrap: 0, stopped: 0 },
  );
  return (
    <PageFrame sectionId="operations" title={title} subtitle={subtitle} period={false}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="OPs em andamento" value={formatNumber(query.data?.page.total ?? 0)} />
        <MetricCard label="Peças boas hoje" value={formatNumber(totals.good)} detail="Somente peças boas" accent="success" />
        <MetricCard label="Refugo" value={formatNumber(totals.scrap)} detail={totals.good ? `${formatPercent(totals.scrap / Math.max(1, totals.good + totals.scrap) * 100)} da produção` : undefined} accent="danger" />
        <MetricCard label="OPs paradas" value={formatNumber(totals.stopped)} detail={totals.stopped ? "Verifique o motivo na tabela" : "Nenhuma OP parada"} accent={totals.stopped ? "warning" : "success"} />
      </div>
      <OrdersTable rows={rows} />
    </PageFrame>
  );
}

function OrdersTable({ rows }: { rows: PagedOrders["items"] }) {
  return (
    <SectionCard title="Ordens em execução" className="content-section section-card--table">
      <DataTable
        rows={rows}
        rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
        columns={[
          { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
          { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
          { key: "operation", label: "Operação", render: (row) => row.operacao_atual ?? "Não disponível" },
          { key: "resource", label: "Recurso", render: (row) => row.recurso_real ?? "Não disponível" },
          { key: "planned", label: "Planejado", render: (row) => formatNumber(row.quantidade_planejada) },
          { key: "good", label: "Boas", render: (row) => formatNumber(row.quantidade_boa) },
          { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
          { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
          { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
          { key: "start", label: "Início", render: (row) => formatDateTime(row.inicio_real) },
        ]}
      />
    </SectionCard>
  );
}

export function OperationsTimePage() {
  const filters = useManagementFilters();
  const query = useApiQuery<TimeBreakdown>(`/api/v1/operations/time?${filters.query}`);
  const title = "Consulta Operacional — Tempo MES";
  const subtitle = "Tempo físico consolidado por categoria, setor e recurso.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error) return <PageFrame sectionId="operations" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const sectorBars = (data?.by_sector ?? []).map((row) => ({
    label: String(row.setor ?? "Não informado"),
    value: Number(row.producao ?? 0),
    detail: formatHours(Number(row.producao ?? 0)),
  }));
  return (
    <PageFrame sectionId="operations" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Tempo produtivo" value={formatHours(Number(data?.totals?.producao ?? 0) + Number(data?.totals?.setup ?? 0))} detail="Produção e setup" accent="success" />
        <MetricCard label="Tempo parado" value={formatHours(data?.totals?.parada)} accent="danger" />
        <MetricCard label="Tempo total medido" value={formatHours(data?.physical_seconds)} accent="primary" />
        <MetricCard label="Tempo a esclarecer" value={formatHours(data?.conflicting_state_seconds)} detail={Number(data?.conflicting_state_seconds ?? 0) > 0 ? "Estados simultâneos incompatíveis no mesmo recurso" : "Sem conflito no período"} accent={Number(data?.conflicting_state_seconds ?? 0) > 0 ? "warning" : "success"} />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Produção por setor">{sectorBars.length ? <BarList data={sectorBars} /> : <EmptyState />}</SectionCard>
        <SectionCard title="Categorias de tempo">
          <DataTable
            rows={Object.entries(data?.totals ?? {})}
            rowKey={(row) => row[0]}
            columns={[
              { key: "category", label: "Categoria", render: (row) => humanize(row[0]) },
              { key: "time", label: "Tempo físico", render: (row) => formatHours(row[1]) },
            ]}
          />
        </SectionCard>
      </div>
    </PageFrame>
  );
}

