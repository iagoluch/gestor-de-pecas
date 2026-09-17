import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SearchInput } from "../../components/SearchInput";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import type { FilterField } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { PagedNestings, TraceabilityResponse } from "../../types/management";
import { formatDateTime, formatDuration, formatNumber, formatPercent, formatSignedDuration, humanize } from "../../utils/format";

function useOrderSelection() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("op") ?? "");
  const deferred = useDebouncedValue(search.trim(), 350);

  useEffect(() => {
    const current = params.get("op") ?? "";
    if (deferred === current) return;
    const next = new URLSearchParams(params);
    if (deferred) next.set("op", deferred);
    else next.delete("op");
    setParams(next, { replace: true });
  }, [deferred, params, setParams]);

  return { search, setSearch, op: params.get("op")?.trim() ?? "" };
}

function OrderSearch({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <SearchInput value={value} onChange={onChange} placeholder="Buscar OP" />;
}

function TraceLoading({ title, subtitle, search, setSearch }: {
  title: string;
  subtitle: string;
  search: string;
  setSearch: (value: string) => void;
}) {
  return <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filters={false} actions={<OrderSearch value={search} onChange={setSearch} />}><LoadingState /></PageFrame>;
}

export function TraceabilityOrderPage() {
  const { search, setSearch, op } = useOrderSelection();
  const query = useApiQuery<TraceabilityResponse>(op ? `/api/v1/traceability/orders/${encodeURIComponent(op)}` : null);
  const title = "Rastreabilidade — OP / Produto";
  const subtitle = "Drill-down da OP até operação, recurso, quantidades e referências de origem.";
  const trace = (query.data?.operations ?? []).reduce(
    (acc, row) => ({
      good: acc.good + Number(row.quantidade_boa ?? 0),
      scrap: acc.scrap + Number(row.refugo ?? 0),
      rework: acc.rework + Number(row.retrabalho ?? 0),
    }),
    { good: 0, scrap: 0, rework: 0 },
  );
  if (query.loading) return <TraceLoading title={title} subtitle={subtitle} search={search} setSearch={setSearch} />;
  return (
    <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filters={false} actions={<OrderSearch value={search} onChange={setSearch} />}>
      {!op ? <EmptyState title="Informe uma OP" detail="A rastreabilidade mostra por onde a OP passou, com quantidades e eventos." /> : query.error ? <ErrorState error={query.error} onRetry={query.reload} /> : (
        <>
          <div className="metric-grid metric-grid--four">
            <MetricCard label="Situação atual" value={String(query.data?.operations?.[(query.data?.operations.length ?? 1) - 1]?.status ?? "Não disponível")} detail={`OP ${query.data?.op ?? op}`} accent="primary" />
            <MetricCard label="Peças boas" value={formatNumber(trace.good)} detail={`${formatNumber(query.data?.operations.length ?? 0)} operação(ões) percorrida(s)`} accent="success" />
            <MetricCard label="Perdas" value={formatNumber(trace.scrap + trace.rework)} detail={`${formatNumber(trace.scrap)} refugo · ${formatNumber(trace.rework)} retrabalho`} accent={trace.scrap + trace.rework > 0 ? "danger" : "teal"} />
            <MetricCard label="Eventos registrados" value={formatNumber(query.data?.timeline.length ?? 0)} detail={`${formatNumber(query.data?.cutting_nestings.length ?? 0)} nesting(s) de Corte vinculado(s)`} accent="purple" />
          </div>
          <SectionCard title="Operações e produto" className="content-section section-card--table">
            <DataTable
              rows={query.data?.operations ?? []}
              rowKey={(row, index) => row.apontamento_id ?? index}
              columns={[
                { key: "operation", label: "Operação", render: (row) => row.operacao ?? "Não disponível" },
                { key: "description", label: "Descrição", render: (row) => row.descricao_operacao ?? "Não disponível" },
                { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
                { key: "sector", label: "Setor", render: (row) => row.setor ?? "Não disponível" },
                { key: "resource", label: "Recurso real", render: (row) => row.recurso_real ?? "Não disponível" },
                { key: "operator", label: "Operador", render: () => "Ver linha do tempo" },
                { key: "good", label: "Boas", render: (row) => formatNumber(row.quantidade_boa) },
                { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
                { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
                { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
                { key: "source", label: "Origem", render: (row) => `Apontamento ${row.apontamento_id ?? "não disponível"}` },
              ]}
            />
          </SectionCard>
          <div className="drilldown-actions">
            <Link to={`/rastreabilidade/linha-do-tempo?op=${encodeURIComponent(op)}`}>Abrir linha do tempo completa</Link>
          </div>
        </>
      )}
    </PageFrame>
  );
}

export function TraceabilityTimelinePage() {
  const { search, setSearch, op } = useOrderSelection();
  const query = useApiQuery<TraceabilityResponse>(op ? `/api/v1/traceability/orders/${encodeURIComponent(op)}` : null);
  const title = "Rastreabilidade — Linha do Tempo";
  const subtitle = "Máquina → OP → operação → evento → operador → registro original, em ordem cronológica.";
  if (query.loading) return <TraceLoading title={title} subtitle={subtitle} search={search} setSearch={setSearch} />;
  return (
    <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filters={false} actions={<OrderSearch value={search} onChange={setSearch} />}>
      {!op ? <EmptyState title="Informe uma OP" detail="A linha do tempo não combina registros de OPs diferentes." /> : query.error ? <ErrorState error={query.error} onRetry={query.reload} /> : (
        <SectionCard title={`Eventos cronológicos da OP ${op}`} className="section-card--table">
          <DataTable
            rows={query.data?.timeline ?? []}
            rowKey={(row, index) => `${row.source}-${row.record_id ?? index}-${row.type}`}
            columns={[
              { key: "timestamp", label: "Data e hora", render: (row) => formatDateTime(row.timestamp) },
              { key: "resource", label: "Máquina / recurso", render: (row) => row.resource ?? "Não disponível" },
              { key: "op", label: "OP", render: () => op },
              { key: "operation", label: "Operação", render: (row) => row.operation ?? "Não disponível" },
              { key: "event", label: "Evento", render: (row) => humanize(row.type) },
              { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status ?? row.type} /> },
              { key: "operator", label: "Operador", render: (row) => row.operator ?? "Não disponível" },
              { key: "quantity", label: "Quantidade", render: (row) => formatNumber(row.quantity) },
              { key: "reason", label: "Motivo / detalhe", render: (row) => row.reason ?? "Não disponível" },
              { key: "origin", label: "Registro original", render: (row) => `${row.source ?? "Fonte não disponível"} #${row.record_id ?? "—"}` },
            ]}
          />
        </SectionCard>
      )}
    </PageFrame>
  );
}

/**
 * A fonte de nestings é a do Corte: ela só recorta com segurança por período e
 * máquina (`listar_tempos_nesting_corte`). Enviar setor/OP/operação/produto/
 * operador não filtra — o serviço devolve lista vazia —, então a tela declara
 * apenas os campos aplicáveis e monta a query com os mesmos campos.
 */
const NESTING_FILTER_FIELDS: FilterField[] = ["resource"];

export function TraceabilityNestingPage() {
  const filters = useManagementFilters();
  const [search, setSearch] = useState("");
  const deferred = useDebouncedValue(search.trim(), 350);
  const query = useApiQuery<PagedNestings>(`/api/v1/traceability/nestings?${filters.queryFor(NESTING_FILTER_FIELDS)}&page=1&page_size=200${deferred ? `&search=${encodeURIComponent(deferred)}` : ""}`);
  const title = "Rastreabilidade — Lote / Material / Nesting";
  const subtitle = "Cada nesting preserva tempo total e tempo dentro do período filtrado como grandezas distintas.";
  if (query.loading && !query.data) return <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filterFields={NESTING_FILTER_FIELDS} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar tarefa, material ou nesting" />}><LoadingState /></PageFrame>;
  if (query.error) return <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filterFields={NESTING_FILTER_FIELDS}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  const nesting = (data?.items ?? []).reduce(
    (acc, row) => ({
      previsto: acc.previsto + Number(row.previsto_segundos ?? 0),
      real: acc.real + Number(row.real_segundos ?? 0),
    }),
    { previsto: 0, real: 0 },
  );
  return (
    <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filterFields={NESTING_FILTER_FIELDS} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar tarefa, material ou nesting" />}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Nestings no filtro" value={formatNumber(data?.count ?? 0)} />
        <MetricCard label="Tempo previsto" value={formatDuration(nesting.previsto)} accent="primary" />
        <MetricCard label="Tempo realizado" value={formatDuration(nesting.real)} accent="success" />
        <MetricCard
          label="Desvio do previsto"
          value={nesting.previsto > 0 ? formatPercent((nesting.real - nesting.previsto) / nesting.previsto * 100) : "Sem previsto no filtro"}
          detail={nesting.previsto > 0 ? formatSignedDuration(nesting.real - nesting.previsto) : undefined}
          availability={nesting.previsto > 0 ? "disponivel" : "dados_insuficientes"}
          accent={nesting.real > nesting.previsto ? "danger" : "teal"}
        />
      </div>
      <SectionCard title="Lotes, materiais e nestings" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row, index) => row.apontamento_id ?? `${row.plano_hash}-${index}`}
          columns={[
            { key: "task", label: "Tarefa / lote", render: (row) => row.tarefa ?? "Não disponível" },
            { key: "program", label: "Programa", render: (row) => row.programa ?? "Não disponível" },
            { key: "nesting", label: "Nesting", render: (row) => row.nesting ?? "Não disponível" },
            { key: "machine", label: "Máquina", render: (row) => row.maquina ?? "Não disponível" },
            { key: "material", label: "Material", render: (row) => row.material ?? "Não disponível" },
            { key: "thickness", label: "Espessura", render: (row) => row.espessura === null || row.espessura === undefined ? "Não disponível" : `${formatNumber(row.espessura, 2)} mm` },
            { key: "planned", label: "Tempo previsto", render: (row) => formatDuration(row.previsto_segundos) },
            { key: "total", label: "Tempo total", render: (row) => formatDuration(row.real_segundos) },
            { key: "period", label: "Tempo no período", render: (row) => formatDuration(row.real_periodo_segundos) },
            { key: "deviation", label: "Desvio", render: (row) => `${formatSignedDuration(row.desvio_segundos)} (${formatPercent(row.desvio_percentual)})` },
            { key: "operator", label: "Operador", render: (row) => row.operador_inicio ?? row.operador_fim ?? "Não disponível" },
            { key: "ops", label: "OPs relacionadas", render: (row) => row.ops_relacionadas?.length ? row.ops_relacionadas.map((op) => <Link key={op} className="inline-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(op)}`}>{op}</Link>) : "Não disponível" },
            { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}
