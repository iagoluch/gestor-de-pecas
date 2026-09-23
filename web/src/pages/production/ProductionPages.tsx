import { useState } from "react";
import { Link } from "react-router-dom";
import { BarList } from "../../components/BarList";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SearchInput } from "../../components/SearchInput";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { PageMeta, PagedOrders, ProductionResponse } from "../../types/management";
import { formatDateTime, formatHours, formatNumber, formatPercent } from "../../utils/format";
import { humanizeSystemState } from "../../utils/systemState";

interface PlanActualRow {
  apontamento_id?: number | null;
  op?: string | null;
  operacao?: string | number | null;
  produto?: string | null;
  recurso_planejado?: string | null;
  recurso_real?: string | null;
  quantidade_planejada?: number | null;
  quantidade_boa: number;
  refugo: number;
  retrabalho: number;
  quantidade_atendida?: number;
  saldo_quantidade?: number | null;
  inicio_planejado?: string | null;
  fim_planejado?: string | null;
  prazo_entrega?: string | null;
  inicio_real?: string | null;
  fim_real?: string | null;
  prioridade?: string | number | null;
}

interface PlanActualResponse {
  periodo: Record<string, string | null>;
  items: PlanActualRow[];
  planning_dates: { availability: string; reason: string };
  page: PageMeta;
}

function LoadingPage({ title, subtitle }: { title: string; subtitle: string }) {
  return <PageFrame sectionId="production" title={title} subtitle={subtitle}><LoadingState /></PageFrame>;
}

export function ProductionOrdersPage() {
  const filters = useManagementFilters();
  const [search, setSearch] = useState("");
  const deferredSearch = useDebouncedValue(search);
  const query = useApiQuery<PagedOrders>(`/api/v1/orders?${filters.query}&page=1&page_size=200${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ""}`);
  const title = "Produção — Ordens de Produção";
  const subtitle = "Plano corporativo em leitura e execução real do Gestor, sem permitir edição do planejamento.";
  if (query.loading && !query.data) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar OP, produto ou recurso" />}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  // Somatório das linhas já entregues pelo backend: apresentação, não regra.
  const orderTotals = (data?.items ?? []).reduce(
    (acc, row) => {
      const planned = Number(row.quantidade_planejada ?? 0);
      const good = Number(row.quantidade_boa ?? 0);
      const scrap = Number(row.refugo ?? 0);
      return {
        planned: acc.planned + planned,
        good: acc.good + good,
        scrap: acc.scrap + scrap,
        attended: acc.attended + Number(row.quantidade_atendida ?? good + scrap),
        balance: acc.balance + Number(row.saldo_quantidade ?? Math.max(0, planned - good - scrap)),
      };
    },
    { planned: 0, good: 0, scrap: 0, attended: 0, balance: 0 },
  );
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar OP, produto ou recurso" />}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Ordens no filtro" value={formatNumber(data?.page.total ?? 0)} />
        <MetricCard label="Quantidade planejada" value={formatNumber(orderTotals.planned)} detail="Somatório das OPs do filtro" accent="primary" />
        <MetricCard label="Peças boas produzidas" value={formatNumber(orderTotals.good)} detail={orderTotals.planned ? `${formatPercent(orderTotals.good / orderTotals.planned * 100)} do planejado` : undefined} accent="success" />
        <MetricCard label="Saldo a produzir" value={formatNumber(orderTotals.balance)} detail={`${formatNumber(orderTotals.attended)} atendidas (boas + refugo); retrabalho não reduz saldo`} accent={orderTotals.balance > 0 ? "warning" : "success"} />
      </div>
      <SectionCard title="Ordens de Produção" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
          columns={[
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "product", label: "Produto", render: (row) => <span title={row.descricao ?? undefined}>{row.produto ?? "Não disponível"}</span> },
            { key: "operation", label: "Operação", render: (row) => row.operacao_atual ?? "Não disponível" },
            { key: "sequence", label: "Sequência", render: (row) => row.sequencia ?? "Não disponível" },
            { key: "resource", label: "Recurso", render: (row) => row.recurso_real ?? row.recurso_planejado ?? "Não disponível" },
            { key: "priority", label: "Prioridade", render: (row) => row.prioridade ?? "Não disponível" },
            { key: "planned", label: "Planejada", render: (row) => formatNumber(row.quantidade_planejada) },
            { key: "good", label: "Boa", render: (row) => formatNumber(row.quantidade_boa) },
            { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
            { key: "attended", label: "Atendida", render: (row) => formatNumber(row.quantidade_atendida) },
            { key: "balance", label: "Saldo", render: (row) => formatNumber(row.saldo_quantidade) },
            { key: "progress", label: "Progresso", render: (row) => formatPercent(row.progresso_percentual) },
            { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
            { key: "next", label: "Próxima operação", render: (row) => row.proxima_operacao ?? "Não disponível" },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function ProductionCompletedPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<ProductionResponse>(`/api/v1/orders/production?${filters.query}`);
  const title = "Produção — Produção Realizada";
  const subtitle = "Somente peças boas compõem a produção; perdas permanecem em grandezas separadas.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const sectors = data?.sectors ?? [];
  const productionAvailability = data?.production.availability ?? "dados_insuficientes";
  const hasQuantityRecords = productionAvailability !== "sem_registros";
  const quantityText = (value: number | null | undefined) => hasQuantityRecords ? formatNumber(value) : humanizeSystemState("sem_registros");
  const lossBase = Number(data?.production.good ?? 0) + Number(data?.production.scrap ?? 0);
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={quantityText(data?.production.good)} detail={data?.production.reason ?? undefined} availability={productionAvailability} accent="success" />
        <MetricCard label="Refugo" value={quantityText(data?.production.scrap)} availability={productionAvailability} accent="danger" />
        <MetricCard label="Retrabalho" value={quantityText(data?.production.rework)} availability={productionAvailability} accent="warning" />
        <MetricCard
          label="Taxa de refugo"
          value={hasQuantityRecords && lossBase > 0 ? formatPercent((data?.production.scrap ?? 0) / lossBase * 100) : humanizeSystemState("sem_registros")}
          detail={hasQuantityRecords && lossBase > 0 ? `${formatNumber(data?.production.resources)} recursos no período` : undefined}
          availability={hasQuantityRecords && lossBase > 0 ? "disponivel" : "sem_registros"}
          accent="teal"
        />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Peças boas por setor">
          {hasQuantityRecords && sectors.length ? <BarList data={sectors.map((row) => ({ label: row.setor, value: row.producao_boa, detail: `${formatNumber(row.producao_boa)} peças` }))} /> : <EmptyState detail={data?.production.reason ?? undefined} />}
        </SectionCard>
        <SectionCard title="Qualidade por setor">
          {hasQuantityRecords ? <DataTable
            rows={sectors}
            rowKey={(row) => row.setor}
            columns={[
              { key: "sector", label: "Setor", render: (row) => row.setor },
              { key: "good", label: "Boas", render: (row) => formatNumber(row.producao_boa) },
              { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
              { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
            ]}
          /> : <EmptyState detail={data?.production.reason ?? undefined} />}
        </SectionCard>
      </div>
    </PageFrame>
  );
}

export function ProductionPlanActualPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<PlanActualResponse>(`/api/v1/orders/planned-vs-actual?${filters.query}&page=1&page_size=200`);
  const title = "Produção — Planejado × Realizado";
  const subtitle = "Comparação somente leitura entre o plano corporativo e a execução registrada.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  const comparison = rows.reduce(
    (acc, row) => ({
      planned: acc.planned + Number(row.quantidade_planejada ?? 0),
      good: acc.good + Number(row.quantidade_boa ?? 0),
      scrap: acc.scrap + Number(row.refugo ?? 0),
      rework: acc.rework + Number(row.retrabalho ?? 0),
      attended: acc.attended + Number(row.quantidade_atendida ?? Number(row.quantidade_boa ?? 0) + Number(row.refugo ?? 0)),
      balance: acc.balance + Number(row.saldo_quantidade ?? Math.max(0, Number(row.quantidade_planejada ?? 0) - Number(row.quantidade_boa ?? 0) - Number(row.refugo ?? 0))),
    }),
    { planned: 0, good: 0, scrap: 0, rework: 0, attended: 0, balance: 0 },
  );
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Quantidade planejada" value={formatNumber(comparison.planned)} detail={`${formatNumber(query.data?.page.total ?? 0)} comparações no filtro`} accent="primary" />
        <MetricCard label="Realizado (boas)" value={formatNumber(comparison.good)} accent="success" />
        <MetricCard label="Atendimento" value={comparison.planned ? formatPercent(comparison.attended / comparison.planned * 100) : "Sem plano no filtro"} detail={`${formatNumber(comparison.attended)} boas + refugo · saldo ${formatNumber(comparison.balance)}`} availability={comparison.planned ? "disponivel" : "dados_insuficientes"} accent="teal" />
        <MetricCard label="Perdas no período" value={formatNumber(comparison.scrap + comparison.rework)} detail={`${formatNumber(comparison.scrap)} refugo · ${formatNumber(comparison.rework)} retrabalho`} accent={comparison.scrap + comparison.rework > 0 ? "danger" : "success"} />
      </div>
      <SectionCard title="Plano × Real por OP/operação" className="content-section section-card--table">
        <DataTable
          rows={rows}
          rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
          columns={[
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "operation", label: "Operação", render: (row) => row.operacao ?? "Não disponível" },
            { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
            { key: "planned-resource", label: "Recurso planejado", render: (row) => row.recurso_planejado ?? "Não disponível" },
            { key: "real-resource", label: "Recurso real", render: (row) => row.recurso_real ?? "Não disponível" },
            { key: "planned-qty", label: "Quantidade plano", render: (row) => formatNumber(row.quantidade_planejada) },
            { key: "good", label: "Quantidade boa", render: (row) => formatNumber(row.quantidade_boa) },
            { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
            { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
            { key: "attended", label: "Atendida", render: (row) => formatNumber(row.quantidade_atendida) },
            { key: "balance", label: "Saldo", render: (row) => formatNumber(row.saldo_quantidade) },
            { key: "planned-date", label: "Início planejado", render: (row) => formatDateTime(row.inicio_planejado) },
            { key: "real-date", label: "Início real", render: (row) => formatDateTime(row.inicio_real) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}
