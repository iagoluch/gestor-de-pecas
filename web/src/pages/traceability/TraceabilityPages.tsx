import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import { ExplainableValue } from "../../components/ExplainableValue";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { divergentEvent, ResourceDivergenceBadge, routeResourceLabel } from "../../components/ResourceDivergenceBadge";
import { SearchInput } from "../../components/SearchInput";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import type { FilterField } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { InspectionWaiver, PagedNestings, TraceabilityResponse, TracePiece } from "../../types/management";
import { displayName, displayText, formatDateTime, formatDuration, formatNumber, formatPercent, formatPercentOneDecimal, formatSignedDuration, humanize } from "../../utils/format";

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

const PIECE_RESULT: Record<TracePiece["resultado"], { label: string; tone: string }> = {
  APROVADA: { label: "Aprovada", tone: "success" },
  RETRABALHO: { label: "Retrabalho", tone: "warning" },
  REFUGO: { label: "Refugo", tone: "danger" },
};

function PieceResultBadge({ value }: { value: TracePiece["resultado"] }) {
  const { label, tone } = PIECE_RESULT[value] ?? { label: humanize(value), tone: "neutral" };
  return <span className={`status-badge status-badge--${tone}`}>{label}</span>;
}

function InspectedPiecesSection({ pieces }: { pieces: TracePiece[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const pieceKey = (row: TracePiece) => `${row.inspecao_id}-${row.numero_peca}`;
  const piece = pieces.find((row) => pieceKey(row) === selected);
  return (
    <SectionCard title="Peças inspecionadas" className="content-section section-card--table">
      {pieces.length === 0 ? <EmptyState title="Nenhuma peça inspecionada" detail="Esta OP não tem inspeção registrada pela Qualidade." /> : (
        <>
          <DataTable
            rows={pieces}
            rowKey={pieceKey}
            columns={[
              { key: "number", label: "Peça nº", sortValue: (row) => row.numero_peca, render: (row) => formatNumber(row.numero_peca) },
              { key: "result", label: "Resultado", render: (row) => <PieceResultBadge value={row.resultado} /> },
              { key: "operator", label: "Operador", render: (row) => displayName(row.operador) },
              { key: "date", label: "Data/hora", sortValue: (row) => row.registrada_em, render: (row) => formatDateTime(row.registrada_em) },
              { key: "outside", label: "Cotas fora do padrão", sortValue: (row) => row.total_cotas_nao_conformes, render: (row) => formatNumber(row.total_cotas_nao_conformes) },
              { key: "rnc", label: "RNC", render: (row) => row.rnc_id ? (row.rnc_codigo ?? `RNC ${row.rnc_id}`) : "—" },
              {
                key: "cotas",
                label: "Cotas",
                render: (row) => (
                  <button
                    type="button"
                    className="button"
                    aria-expanded={selected === pieceKey(row)}
                    onClick={() => setSelected((current) => current === pieceKey(row) ? null : pieceKey(row))}
                  >
                    {selected === pieceKey(row) ? "Ocultar cotas" : "Ver cotas"}
                  </button>
                ),
              },
            ]}
          />
          {piece ? (
            <div className="trace-piece-cotas">
              <h3>{`Cotas da peça ${formatNumber(piece.numero_peca)}`}</h3>
              <DataTable
                rows={piece.cotas}
                rowKey={(_, index) => index}
                emptyTitle="Nenhuma cota medida nesta peça"
                columns={[
                  { key: "description", label: "Cota", render: (row) => displayText(row.descricao) },
                  { key: "standard", label: "Padrão", render: (row) => [row.padrao, row.unidade].filter(Boolean).join(" ") || "—" },
                  { key: "measured", label: "Medido", render: (row) => displayText(row.medida) },
                  {
                    key: "status",
                    label: "Situação",
                    render: (row) => row.status === "NAO_CONFORME"
                      ? <span className="status-badge status-badge--danger">Não conforme</span>
                      : <span className="status-badge status-badge--success">Conforme</span>,
                  },
                ]}
              />
            </div>
          ) : null}
        </>
      )}
    </SectionCard>
  );
}

/**
 * Dispensa de inspeção registrada pela Qualidade. O selo só aparece quando o
 * backend informa a dispensa; motivo, autorizador, crachá e data são os que
 * foram gravados — campo ausente fica "—", nunca é preenchido aqui.
 */
function InspectionWaiverNotice({ waivers }: { waivers: InspectionWaiver[] }) {
  return (
    <SectionCard title="Inspeção dispensada" className="content-section section-card--table">
      <div role="status" style={{ padding: "12px 16px 4px" }}>
        <span className="status-badge status-badge--warning">Inspeção dispensada</span>
        <p className="chart-note">
          {waivers.length > 1
            ? `${formatNumber(waivers.length)} inspeções desta OP foram dispensadas, sem medição de peças.`
            : "A inspeção desta OP foi dispensada, sem medição de peças."}
        </p>
      </div>
      {waivers.length ? (
        <DataTable
          rows={waivers}
          rowKey={(row, index) => row.inspecao_id ?? index}
          columns={[
            { key: "operation", label: "Operação", render: (row) => displayName(row.operacao == null ? null : String(row.operacao), "—") },
            { key: "resource", label: "Recurso", render: (row) => displayName(row.recurso, "—") },
            { key: "quantity", label: "Quantidade", render: (row) => row.quantidade == null ? "—" : formatNumber(row.quantidade) },
            { key: "reason", label: "Motivo", render: (row) => displayText(row.motivo, "—") },
            { key: "by", label: "Autorizado por", render: (row) => displayName(row.autorizado_por, "—") },
            { key: "badge", label: "Crachá", render: (row) => row.cracha || "—" },
            { key: "date", label: "Data", sortValue: (row) => row.dispensada_em, render: (row) => row.dispensada_em ? formatDateTime(row.dispensada_em) : "—" },
          ]}
        />
      ) : null}
    </SectionCard>
  );
}

export function TraceabilityOrderPage() {
  const { search, setSearch, op } = useOrderSelection();
  const query = useApiQuery<TraceabilityResponse>(op ? `/api/v1/traceability/orders/${encodeURIComponent(op)}` : null);
  const title = "Rastreabilidade — OP / Produto";
  const subtitle = "Drill-down da OP até operação, recurso, quantidades, referências de origem e linha do tempo dos eventos.";
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
    <PageFrame staleError={query.error} sectionId="traceability" title={title} subtitle={subtitle} filters={false} actions={<OrderSearch value={search} onChange={setSearch} />}>
      {!op ? <EmptyState title="Informe uma OP" detail="A rastreabilidade mostra por onde a OP passou, com quantidades e eventos." /> : query.error && !query.data ? <ErrorState error={query.error} onRetry={query.reload} /> : (
        <>
          <div className="metric-grid metric-grid--four">
            <MetricCard label="Situação atual" value={String(query.data?.operations?.[(query.data?.operations.length ?? 1) - 1]?.status ?? "Não disponível")} detail={`OP ${query.data?.op ?? op}`} accent="primary" />
            <MetricCard label="Peças boas" value={formatNumber(trace.good)} detail={`${formatNumber(query.data?.operations.length ?? 0)} operação(ões) percorrida(s)`} accent="success" />
            <MetricCard label="Perdas" value={formatNumber(trace.scrap + trace.rework)} detail={`${formatNumber(trace.scrap)} refugo · ${formatNumber(trace.rework)} retrabalho`} accent={trace.scrap + trace.rework > 0 ? "danger" : "teal"} />
            <MetricCard label="Eventos registrados" value={formatNumber(query.data?.timeline.length ?? 0)} detail={`${formatNumber(query.data?.cutting_nestings.length ?? 0)} nesting(s) de Corte vinculado(s)`} accent="purple" />
          </div>
          {query.data?.inspection_waived || query.data?.inspection_waivers?.length ? <InspectionWaiverNotice waivers={query.data?.inspection_waivers ?? []} /> : null}
          <SectionCard title="Operações e produto" className="content-section section-card--table">
            <DataTable
              rows={query.data?.operations ?? []}
              rowKey={(row, index) => row.apontamento_id ?? index}
              columns={[
                { key: "operation", label: "Operação", render: (row) => displayName(row.operacao) },
                { key: "description", label: "Descrição", render: (row) => displayText(row.descricao_operacao) },
                { key: "product", label: "Produto", render: (row) => row.produto ?? "Não disponível" },
                { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
                { key: "resource", label: "Recurso real", render: (row) => displayName(row.recurso_real) },
                {
                  key: "divergence",
                  label: "Recurso divergente",
                  render: (row) => {
                    const event = divergentEvent(row.eventos);
                    if (!event) return "—";
                    return <ResourceDivergenceBadge planned={routeResourceLabel(event) || row.recurso_previsto} actual={event.recurso_apontado || row.recurso_real} />;
                  },
                },
                { key: "operator", label: "Operador", render: (row) => row.operador_inicio ?? row.operador_fim ?? "Não disponível" },
                { key: "good", label: "Boas", render: (row) => formatNumber(row.quantidade_boa) },
                { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
                { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
                { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
                { key: "source", label: "Origem", render: (row) => `Apontamento ${row.apontamento_id ?? "não disponível"}` },
              ]}
            />
          </SectionCard>
          {(query.data?.cutting_nestings ?? []).length ? (
            <SectionCard title="Nestings de Corte da OP" className="content-section section-card--table">
              <DataTable
                rows={query.data?.cutting_nestings ?? []}
                rowKey={(row, index) => row.apontamento_id ?? `${row.plano_hash}-${index}`}
                columns={[
                  { key: "task", label: "Tarefa / lote", render: (row) => row.tarefa ?? "Não disponível" },
                  { key: "program", label: "Programa", render: (row) => row.programa ?? "Não disponível" },
                  { key: "nesting", label: "Nesting", render: (row) => row.nesting ?? "Não disponível" },
                  { key: "machine", label: "Máquina", render: (row) => row.maquina ?? "Não disponível" },
                  { key: "utilization", label: "Aproveitamento", sortValue: (row) => row.aproveitamento_percentual ?? -1, render: (row) => formatPercentOneDecimal(row.aproveitamento_percentual) },
                ]}
              />
            </SectionCard>
          ) : null}
          <InspectedPiecesSection pieces={query.data?.pieces ?? []} />
          <SectionCard title={`Linha do tempo da OP ${op} — eventos em ordem cronológica`} className="content-section section-card--table">
            <DataTable
              rows={query.data?.timeline ?? []}
              rowKey={(row, index) => `${row.source}-${row.record_id ?? index}-${row.type}`}
              columns={[
                { key: "timestamp", label: "Data e hora", render: (row) => formatDateTime(row.timestamp) },
                { key: "resource", label: "Máquina / recurso", render: (row) => displayName(row.resource) },
                { key: "op", label: "OP", render: () => op },
                { key: "operation", label: "Operação", render: (row) => displayName(row.operation) },
                { key: "event", label: "Evento", render: (row) => humanize(row.type) },
                { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status ?? row.type} /> },
                { key: "operator", label: "Operador", render: (row) => row.operator ?? "Não disponível" },
                { key: "quantity", label: "Quantidade", render: (row) => formatNumber(row.quantity) },
                { key: "reason", label: "Motivo / detalhe", render: (row) => displayName(row.reason) },
                { key: "origin", label: "Registro original", render: (row) => displayName(row.source, "Fonte não disponível") },
              ]}
            />
          </SectionCard>
        </>
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
  if (query.error && !query.data) return <PageFrame sectionId="traceability" title={title} subtitle={subtitle} filterFields={NESTING_FILTER_FIELDS} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar tarefa, material ou nesting" />}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  // Soma do filtro inteiro (vem do servidor); sem ela, cai na soma da página carregada.
  const nesting = data?.totals
    ? { previsto: data.totals.previsto_segundos, real: data.totals.real_segundos }
    : (data?.items ?? []).reduce(
      (acc, row) => ({
        previsto: acc.previsto + Number(row.previsto_segundos ?? 0),
        real: acc.real + Number(row.real_segundos ?? 0),
      }),
      { previsto: 0, real: 0 },
    );
  // A explicação refaz a conta sobre o filtro de período e máquina, sem a busca por texto:
  // com a busca ativa (ou dados recarregando) os cartões continuam texto simples, para o número clicado ser sempre o explicado.
  const explainFilters = { ...filters.filters, sector: "", op: "", operation: "", product: "", operator: "" };
  const explain = (metric: string, label: string, text: string): ReactNode => (
    search.trim() || deferred || query.loading ? text : <ExplainableValue metric={metric} filters={explainFilters} context={`${label} ${text}`}>{text}</ExplainableValue>
  );
  const desvioText = nesting.previsto > 0 ? formatPercent((nesting.real - nesting.previsto) / nesting.previsto * 100) : "Sem previsto no filtro";
  const utilization = data?.aproveitamento;
  return (
    <PageFrame staleError={query.error} sectionId="traceability" title={title} subtitle={subtitle} filterFields={NESTING_FILTER_FIELDS} actions={<SearchInput value={search} onChange={setSearch} placeholder="Buscar tarefa, material ou nesting" />}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Nestings no filtro" value={formatNumber(data?.count ?? 0)} valueNode={explain("cut.nestings", "Nestings no filtro", formatNumber(data?.count ?? 0))} />
        <MetricCard label="Tempo previsto" value={formatDuration(nesting.previsto)} valueNode={explain("cut.previsto", "Tempo previsto", formatDuration(nesting.previsto))} accent="primary" />
        <MetricCard label="Tempo realizado" value={formatDuration(nesting.real)} valueNode={explain("cut.realizado", "Tempo realizado", formatDuration(nesting.real))} accent="success" />
        <MetricCard
          label="Desvio do previsto"
          value={desvioText}
          valueNode={nesting.previsto > 0 ? explain("cut.desvio", "Desvio do previsto", desvioText) : undefined}
          detail={nesting.previsto > 0 ? formatSignedDuration(nesting.real - nesting.previsto) : undefined}
          availability={nesting.previsto > 0 ? "disponivel" : "dados_insuficientes"}
          accent={nesting.real > nesting.previsto ? "danger" : "teal"}
        />
      </div>
      {utilization ? (
        <SectionCard title="Aproveitamento da chapa" className="content-section">
          <div className="metric-grid metric-grid--four" role="group" aria-label="Aproveitamento da chapa">
            <MetricCard label="Aproveitamento médio" value={formatPercentOneDecimal(utilization.aproveitamento_medio_percentual)} detail={utilization.aproveitamento_medio_percentual == null ? "Sem nesting com dado no filtro" : undefined} accent="success" />
            <MetricCard label="Nestings com dado" value={formatNumber(utilization.nestings_com_dado)} detail={`de ${formatNumber(utilization.nestings)} no filtro`} accent="primary" />
            <MetricCard label="Nestings sem dado" value={formatNumber(utilization.nestings_sem_dado)} detail="Não entram na média" accent={utilization.nestings_sem_dado > 0 ? "warning" : "teal"} />
          </div>
          <p className="chart-note" style={{ padding: "8px 16px 10px" }}>{utilization.regra}</p>
        </SectionCard>
      ) : null}
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
            { key: "utilization", label: "Aproveitamento", sortValue: (row) => row.aproveitamento_percentual ?? -1, render: (row) => formatPercentOneDecimal(row.aproveitamento_percentual) },
            { key: "operator", label: "Operador", render: (row) => row.operador_inicio ?? row.operador_fim ?? "Não disponível" },
            { key: "ops", label: "OPs relacionadas", render: (row) => row.ops_relacionadas?.length ? row.ops_relacionadas.map((op) => <Link key={op} className="inline-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(op)}`}>{op}</Link>) : "Não disponível" },
            { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
          ]}
        />
      </SectionCard>
      {utilization?.por_tarefa?.length ? (
        <SectionCard title="Aproveitamento por tarefa" className="content-section section-card--table">
          <DataTable
            rows={utilization.por_tarefa}
            rowKey={(row, index) => row.tarefa ?? index}
            columns={[
              { key: "task", label: "Tarefa / lote", render: (row) => row.tarefa ?? "Não disponível" },
              { key: "nestings", label: "Nestings", sortValue: (row) => row.nestings, render: (row) => formatNumber(row.nestings) },
              { key: "withData", label: "Com dado", sortValue: (row) => row.nestings_com_dado, render: (row) => formatNumber(row.nestings_com_dado) },
              { key: "utilization", label: "Aproveitamento médio", sortValue: (row) => row.aproveitamento_medio_percentual ?? -1, render: (row) => formatPercentOneDecimal(row.aproveitamento_medio_percentual) },
            ]}
          />
        </SectionCard>
      ) : null}
    </PageFrame>
  );
}
