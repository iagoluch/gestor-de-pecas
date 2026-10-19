import { useState } from "react";
import { Link } from "react-router-dom";
import { BarList } from "../../components/BarList";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { ExplainableValue } from "../../components/ExplainableValue";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SearchInput } from "../../components/SearchInput";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { PageMeta, PagedOrders, ProductionResponse } from "../../types/management";
import { displayName, formatDateTime, formatNumber, formatPercent } from "../../utils/format";
import { humanizeSystemState } from "../../utils/systemState";
import { buildAttendanceExplanation, buildSumExplanation, ROW_LIMIT, sumQuantities, type ExplanationScope, type SumMetric } from "./productionExplanations";

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
  const query = useApiQuery<PagedOrders>(`/api/v1/orders?${filters.query}&page=1&page_size=${ROW_LIMIT}${deferredSearch ? `&search=${encodeURIComponent(deferredSearch)}` : ""}`);
  const title = "Produção — Ordens de Produção";
  const subtitle = "Plano corporativo em leitura e execução real do Gestor, sem permitir edição do planejamento.";
  if (query.loading && !query.data) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar OP, produto ou recurso" />}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  // Somatório das linhas já entregues pelo backend: apresentação, não regra.
  // A explicação clicável usa as mesmas linhas e a mesma conta (`sumQuantities`).
  const scope: ExplanationScope = { rows: data?.items ?? [], filterTotal: data?.page.total };
  const orderTotals = sumQuantities(scope.rows);
  const explained = (metric: SumMetric, text: string) => {
    const explanation = buildSumExplanation(metric, scope);
    return <ExplainableValue local={explanation} context={`${explanation.label} ${text}`}>{text}</ExplainableValue>;
  };
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar OP, produto ou recurso" />}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Ordens no filtro" value={formatNumber(data?.page.total ?? 0)} />
        <MetricCard label="Quantidade planejada" value={formatNumber(orderTotals.planned)} valueNode={explained("planned", formatNumber(orderTotals.planned))} detail="Somatório das OPs do filtro" accent="primary" />
        <MetricCard label="Peças boas produzidas" value={formatNumber(orderTotals.good)} valueNode={explained("good", formatNumber(orderTotals.good))} detail={orderTotals.planned ? `${formatPercent(orderTotals.good / orderTotals.planned * 100)} do planejado (só boas)` : undefined} accent="success" />
        <MetricCard label="Saldo a produzir" value={formatNumber(orderTotals.balance)} valueNode={explained("balance", formatNumber(orderTotals.balance))} detail={`${formatNumber(orderTotals.attended)} atendidas (boas + refugo); retrabalho não reduz saldo`} accent={orderTotals.balance > 0 ? "warning" : "success"} />
      </div>
      <SectionCard title="Ordens de Produção" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
          columns={[
            // GE-09: OP fixa e Status logo ao lado, para não sumirem na rolagem;
            // a sequência acompanha a operação em vez de ocupar coluna própria.
            { key: "op", label: "OP", sticky: true, sortValue: (row) => row.op, render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "status", label: "Status", sortValue: (row) => row.status, render: (row) => <StatusBadge value={row.status} /> },
            { key: "product", label: "Produto", sortValue: (row) => row.produto, render: (row) => <span title={row.descricao ?? undefined}>{row.produto ?? "Não disponível"}</span> },
            { key: "operation", label: "Operação", sortValue: (row) => row.sequencia, render: (row) => row.operacao_atual ? (row.sequencia ? `${row.sequencia} · ${displayName(row.operacao_atual)}` : displayName(row.operacao_atual)) : "Não disponível" },
            { key: "resource", label: "Recurso", sortValue: (row) => row.recurso_real ?? row.recurso_planejado, render: (row) => row.recurso_real ?? row.recurso_planejado ?? "Não disponível" },
            { key: "priority", label: "Prioridade", sortValue: (row) => row.prioridade, render: (row) => displayName(row.prioridade) },
            { key: "planned", label: "Planejada", sortValue: (row) => row.quantidade_planejada, render: (row) => formatNumber(row.quantidade_planejada) },
            { key: "good", label: "Boa", sortValue: (row) => row.quantidade_boa, render: (row) => formatNumber(row.quantidade_boa) },
            { key: "scrap", label: "Refugo", sortValue: (row) => row.refugo, render: (row) => formatNumber(row.refugo) },
            { key: "attended", label: "Atendida", sortValue: (row) => row.quantidade_atendida, render: (row) => formatNumber(row.quantidade_atendida) },
            { key: "balance", label: "Saldo", sortValue: (row) => row.saldo_quantidade, render: (row) => formatNumber(row.saldo_quantidade) },
            // GE-10: a base do percentual fica no rótulo (atendida = boas + refugo).
            { key: "progress", label: "% atendida", sortValue: (row) => row.progresso_percentual, render: (row) => formatPercent(row.progresso_percentual) },
            { key: "next", label: "Próxima operação", render: (row) => displayName(row.proxima_operacao) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function ProductionCompletedPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<ProductionResponse>(`/api/v1/orders/production?${filters.query}`);
  const title = "Produção — Produção realizada";
  const subtitle = "Somente peças boas compõem a produção; perdas permanecem em grandezas separadas.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const sectors = data?.sectors ?? [];
  const productionAvailability = data?.production.availability ?? "dados_insuficientes";
  const hasQuantityRecords = productionAvailability !== "sem_registros";
  const quantityText = (value: number | null | undefined) => hasQuantityRecords ? formatNumber(value) : humanizeSystemState("sem_registros");
  const lossBase = Number(data?.production.good ?? 0) + Number(data?.production.scrap ?? 0);
  // Números do período: a explicação vem do servidor (mesmos filtros da tela).
  const serverExplained = (metric: string, label: string, text: string, enabled = hasQuantityRecords) => enabled
    ? <ExplainableValue metric={metric} filters={filters.filters} context={`${label} ${text}`}>{text}</ExplainableValue>
    : undefined;
  const goodText = quantityText(data?.production.good);
  const scrapText = quantityText(data?.production.scrap);
  const reworkText = quantityText(data?.production.rework);
  const showRate = hasQuantityRecords && lossBase > 0;
  const rateText = showRate ? formatPercent((data?.production.scrap ?? 0) / lossBase * 100) : humanizeSystemState("sem_registros");
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Produção boa" value={goodText} valueNode={serverExplained("qtd.boa", "Produção boa", goodText)} detail={data?.production.reason ?? undefined} availability={productionAvailability} accent="success" />
        <MetricCard label="Refugo" value={scrapText} valueNode={serverExplained("qtd.refugo", "Refugo", scrapText)} availability={productionAvailability} accent="danger" />
        <MetricCard label="Retrabalho" value={reworkText} valueNode={serverExplained("qtd.retrabalho", "Retrabalho", reworkText)} availability={productionAvailability} accent="warning" />
        <MetricCard
          label="Taxa de refugo"
          value={rateText}
          valueNode={serverExplained("qtd.taxa_refugo", "Taxa de refugo", rateText, showRate)}
          detail={showRate ? `${formatNumber(data?.production.resources)} recursos no período` : undefined}
          availability={showRate ? "disponivel" : "sem_registros"}
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
              { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
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
  const query = useApiQuery<PlanActualResponse>(`/api/v1/orders/planned-vs-actual?${filters.query}&page=1&page_size=${ROW_LIMIT}`);
  const title = "Produção — Planejado × Realizado";
  const subtitle = "Comparação somente leitura entre o plano corporativo e a execução registrada.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="production" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  const scope: ExplanationScope = { rows, filterTotal: query.data?.page.total };
  const comparison = sumQuantities(rows);
  const explained = (metric: SumMetric, text: string) => {
    const explanation = buildSumExplanation(metric, scope);
    return <ExplainableValue local={explanation} context={`${explanation.label} ${text}`}>{text}</ExplainableValue>;
  };
  const attendanceText = comparison.planned ? formatPercent(comparison.attended / comparison.planned * 100) : "Sem plano no filtro";
  const lossesText = formatNumber(comparison.scrap + comparison.rework);
  return (
    <PageFrame staleError={query.error} sectionId="production" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Quantidade planejada" value={formatNumber(comparison.planned)} valueNode={explained("planned", formatNumber(comparison.planned))} detail={`${formatNumber(query.data?.page.total ?? 0)} comparações no filtro`} accent="primary" />
        <MetricCard label="Realizado (boas)" value={formatNumber(comparison.good)} valueNode={explained("good", formatNumber(comparison.good))} accent="success" />
        <MetricCard label="Atendimento" value={attendanceText} valueNode={comparison.planned ? <ExplainableValue local={buildAttendanceExplanation(scope)} context={`Atendimento ${attendanceText}`}>{attendanceText}</ExplainableValue> : undefined} detail={`${formatNumber(comparison.attended)} boas + refugo · saldo ${formatNumber(comparison.balance)}`} availability={comparison.planned ? "disponivel" : "dados_insuficientes"} accent="teal" />
        <MetricCard label="Perdas no período" value={lossesText} valueNode={explained("losses", lossesText)} detail={`${formatNumber(comparison.scrap)} refugo · ${formatNumber(comparison.rework)} retrabalho`} accent={comparison.scrap + comparison.rework > 0 ? "danger" : "success"} />
      </div>
      <SectionCard title="Plano × Real por OP/operação" className="content-section section-card--table">
        <DataTable
          rows={rows}
          rowKey={(row, index) => row.apontamento_id ?? `${row.op}-${index}`}
          columns={[
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "operation", label: "Operação", render: (row) => displayName(row.operacao) },
            { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
            { key: "planned-resource", label: "Recurso planejado", render: (row) => displayName(row.recurso_planejado) },
            { key: "real-resource", label: "Recurso real", render: (row) => displayName(row.recurso_real) },
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
