import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { ExplainableValue } from "../../components/ExplainableValue";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import type { FilterField } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { AuditResponse, IssueRow, PagedInspectionWaivers } from "../../types/management";
import { displayName, displayText, formatDateTime, formatHours, formatNumber, humanize } from "../../utils/format";

interface AlertsResponse {
  items: IssueRow[];
  count: number;
  by_severity: Record<string, number>;
  reliability_percentage: number | null;
  reliability_reason: string;
}

/**
 * Alerta interno é um fato industrial que precisa chegar a alguém (PCP,
 * supervisão, responsável pelo retrabalho). Ele não é uma inconsistência de
 * dados: por isso tem bloco próprio, ao lado da auditoria, com o
 * destinatário e o estado da notificação visíveis.
 */
interface InternalAlert {
  id: number;
  tipo: string;
  severidade: string;
  destinatario: string;
  canal_previsto: string;
  status_notificacao: string;
  codigo_op?: string | null;
  numero_operacao?: string | null;
  tipo_setor?: string | null;
  codigo_recurso?: string | null;
  titulo: string;
  mensagem: string;
  quantidade?: number | null;
  criado_em?: string | null;
}

interface InternalAlertsResponse {
  items: InternalAlert[];
  count: number;
  pending: number;
}

interface ReliabilityResponse {
  periodo: Record<string, string | null>;
  records_analyzed: number;
  resource_states_analyzed: number;
  rateio_sessions_analyzed: number;
  by_severity: Record<string, number>;
  reliability_percentage: number | null;
  reliability_reason: string;
  physical_state_source: string;
}

function LoadingPage({ title, subtitle }: { title: string; subtitle: string }) {
  return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><LoadingState /></PageFrame>;
}

export interface EventsPage<T, S> {
  items: T[];
  summary: S;
  page: { page: number; page_size: number; total: number };
}

export interface StatusEvent {
  id: number;
  recurso?: string | null;
  /** Nome líquido do recurso (catálogo); `recurso` é o código. */
  recurso_nome?: string | null;
  setor?: string | null;
  codigo_status?: string | null;
  descricao?: string | null;
  categoria: string;
  classificacao?: "planejada" | "nao_planejada" | null;
  inicio?: string | null;
  fim?: string | null;
  em_aberto: boolean;
  duracao_segundos?: number | null;
  operador?: string | null;
  motivo?: string | null;
  comentario?: string | null;
  op?: string | null;
  operacao?: string | null;
}

export interface ProductionEvent {
  apontamento_id?: number | null;
  op?: string | null;
  tarefa?: string | null;
  plano?: string | null;
  produto?: string | null;
  operacao?: string | null;
  setor?: string | null;
  recurso?: string | null;
  colaborador?: string | null;
  atividade?: string | null;
  inicio?: string | null;
  fim?: string | null;
  tempo_real_segundos?: number | null;
  tempo_padrao_segundos?: number | null;
  quantidade_boa?: number | null;
  quantidade_refugo?: number | null;
  quantidade_retrabalho?: number | null;
  inconsistencia?: string | null;
}

export const opLink = (op?: string | null) => (op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(op)}`}>{op}</Link> : "—");
export const qty = (value?: number | null) => (value == null ? "—" : formatNumber(value));

/** Parada recebe a classificação central (planejada / não planejada); o resto mostra a categoria física. */
export function statusClassLabel(row: Pick<StatusEvent, "categoria" | "classificacao">) {
  if (row.categoria === "parada" && row.classificacao) {
    return row.classificacao === "planejada" ? "Parada planejada" : "Parada não planejada";
  }
  return humanize(row.categoria);
}

/** Chave da classificação, igual à do filtro; dá a cor da linha (ver .status-row no CSS). */
export function statusClassKey(row: Pick<StatusEvent, "categoria" | "classificacao">) {
  return row.categoria === "parada" && row.classificacao ? `parada_${row.classificacao}` : row.categoria;
}

/** Nome da classe do status (mesma chave que o servidor usa no filtro). */
export function statusClassName(classe: string) {
  if (classe === "parada_planejada") return "Parada planejada";
  if (classe === "parada_nao_planejada") return "Parada não planejada";
  return humanize(classe);
}


// Colunas das telas de eventos: a Auditoria analítica (tipos 01 e 02) usa as mesmas,
// então nenhuma coluna diverge entre a tela antiga e a nova.
export const STATUS_COLUMNS: TableColumn<StatusEvent>[] = [
  { key: "op", label: "OP", render: (row) => opLink(row.op) },
  { key: "resource", label: "Recurso", render: (row) => displayName(row.recurso_nome ?? row.recurso) },
  { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
  { key: "code", label: "Código", render: (row) => row.codigo_status ?? "—" },
  { key: "status", label: "Status", render: (row) => displayText(row.descricao, humanize(row.categoria)) },
  { key: "class", label: "Classificação", render: (row) => statusClassLabel(row) },
  { key: "start", label: "Início", sortValue: (row) => row.inicio, render: (row) => formatDateTime(row.inicio) },
  { key: "end", label: "Fim", sortValue: (row) => row.fim, render: (row) => (row.em_aberto ? "Em aberto" : formatDateTime(row.fim)) },
  { key: "duration", label: "Duração no período", sortValue: (row) => row.duracao_segundos, render: (row) => formatHours(row.duracao_segundos) },
  { key: "operator", label: "Colaborador", render: (row) => displayName(row.operador) },
  { key: "reason", label: "Motivo / observação", render: (row) => displayText([row.motivo, row.comentario].filter(Boolean).join(" — ") || null) },
];

export const statusRowClass = (row: StatusEvent) => `status-row status-row--${statusClassKey(row)}`;

export const PRODUCTION_COLUMNS: TableColumn<ProductionEvent>[] = [
  { key: "op", label: "OP", render: (row) => (row.tarefa ? `Tarefa ${row.tarefa}${row.plano ? ` · Plano ${row.plano}` : ""}` : opLink(row.op)) },
  { key: "product", label: "Produto", render: (row) => displayText(row.produto, "—") },
  { key: "operation", label: "Operação", render: (row) => displayName(row.operacao) },
  { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
  { key: "resource", label: "Recurso", render: (row) => displayName(row.recurso) },
  { key: "operator", label: "Colaborador", render: (row) => displayName(row.colaborador) },
  { key: "activity", label: "Atividade", render: (row) => (row.inconsistencia === "quantidade_sem_evento" ? <span className="status-badge status-badge--warning">Quantidade sem evento</span> : humanize(row.atividade)) },
  { key: "start", label: "Início", sortValue: (row) => row.inicio, render: (row) => formatDateTime(row.inicio) },
  { key: "end", label: "Fim", sortValue: (row) => row.fim, render: (row) => (row.inicio && !row.fim ? "Em andamento" : formatDateTime(row.fim)) },
  { key: "real", label: "Tempo real", sortValue: (row) => row.tempo_real_segundos, render: (row) => formatHours(row.tempo_real_segundos) },
  { key: "standard", label: "Tempo padrão", sortValue: (row) => row.tempo_padrao_segundos, render: (row) => (row.tempo_padrao_segundos == null ? "—" : `${formatHours(row.tempo_padrao_segundos)} ${row.tarefa ? "por plano" : "por peça"}`) },
  { key: "good", label: "Boas", render: (row) => qty(row.quantidade_boa) },
  { key: "scrap", label: "Refugo", render: (row) => qty(row.quantidade_refugo) },
  { key: "rework", label: "Retrabalho", render: (row) => qty(row.quantidade_retrabalho) },
];

export const productionRowKey = (row: ProductionEvent, index: number) => `${row.apontamento_id ?? row.tarefa ?? "q"}-${row.atividade ?? ""}-${row.inicio ?? ""}-${index}`;

export const STATUS_PAGE_SIZE = 100;
const EMPTY_STATUS_FILTERS = { recurso: "", status: "", classe: "", op: "", aberto: "" };

interface StatusEventsResponse extends EventsPage<StatusEvent, { eventos: number; recursos: number; paradas_nao_planejadas: number; em_aberto: number }> {
  opcoes?: { recursos: Array<{ codigo: string; nome: string }>; status: string[]; classes: string[] };
}

export type PickOption = { value: string; label: string };

export function toOptions(values: string[] = [], name: (value: string) => string = (value) => value): PickOption[] {
  return values.map((value) => ({ value, label: name(value) }));
}

/**
 * Campo de escolha onde dá para digitar: a lista de sugestões filtra enquanto
 * digita. Vale a opção igual ao texto ou, senão, a primeira que contém o texto;
 * texto vazio volta para "Todos"; texto sem nenhuma opção volta ao valor atual.
 */
export function SearchPick({ label, value, options, onPick }: {
  label: string;
  value: string;
  options: PickOption[];
  onPick: (value: string) => void;
}) {
  const listId = useId();
  const current = options.find((option) => option.value === value)?.label ?? value;
  const [text, setText] = useState(current);
  const [shown, setShown] = useState(current);
  if (shown !== current) {
    setShown(current);
    setText(current);
  }
  const find = (typed: string, exact: boolean) => {
    const wanted = typed.trim().toLocaleLowerCase("pt-BR");
    return options.find((option) => option.label.toLocaleLowerCase("pt-BR") === wanted)
      ?? (exact ? undefined : options.find((option) => option.label.toLocaleLowerCase("pt-BR").includes(wanted)));
  };
  const commit = () => {
    if (!text.trim()) { if (value) onPick(""); return; }
    const match = find(text, false);
    if (match) { setText(match.label); if (match.value !== value) onPick(match.value); }
    else setText(current);
  };
  return (
    <label>{label}
      <input
        list={listId}
        value={text}
        placeholder="Todos"
        onChange={(event) => {
          setText(event.target.value);
          // Escolha clicada na lista chega com o texto exato da opção.
          const match = find(event.target.value, true);
          if (match && match.value !== value) onPick(match.value);
        }}
        onBlur={commit}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commit(); } }}
      />
      <datalist id={listId}>
        {options.map((option) => <option key={option.value} value={option.label} />)}
      </datalist>
    </label>
  );
}

export function AuditStatusEventsPage() {
  const filters = useManagementFilters();
  const [table, setTable] = useState(EMPTY_STATUS_FILTERS);
  const [opDraft, setOpDraft] = useState("");
  const [page, setPage] = useState(1);
  // Mudou período/setor/etc.: a página antiga pode nem existir mais; volta à 1.
  const [pagedQuery, setPagedQuery] = useState(filters.query);
  if (pagedQuery !== filters.query) {
    setPagedQuery(filters.query);
    setPage(1);
  }
  const params = new URLSearchParams({ page: String(page), page_size: String(STATUS_PAGE_SIZE) });
  if (table.recurso) params.set("evento_recurso", table.recurso);
  if (table.status) params.set("evento_status", table.status);
  if (table.classe) params.set("evento_classe", table.classe);
  if (table.op) params.set("evento_op", table.op);
  if (table.aberto) params.set("em_aberto", "true");
  const query = useApiQuery<StatusEventsResponse>(`/api/v1/audit/status-events?${filters.query}&${params}`);
  // Trocar um filtro muda o endereço da consulta e zera `query.data`; a tela
  // segue mostrando o último resultado até o novo chegar, sem piscar nem
  // desmontar os campos de filtro enquanto a pessoa digita.
  const [kept, setKept] = useState<StatusEventsResponse | null>(null);
  if (query.data && query.data !== kept) setKept(query.data);
  const data = query.data ?? kept;
  const title = "Auditoria — Eventos de Status";
  const subtitle = "Em que condição cada recurso esteve e por quanto tempo, produzindo ou parado.";
  const frame = { sectionId: "audit" as const, title, subtitle, filterFields: ["sector", "product", "operator"] as FilterField[] };
  if (!data && !query.error) return <PageFrame {...frame}><LoadingState /></PageFrame>;
  if (query.error && !data) return <PageFrame {...frame}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const summary = data?.summary;
  const options = data?.opcoes;
  const total = data?.page.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / STATUS_PAGE_SIZE));
  const change = (patch: Partial<typeof EMPTY_STATUS_FILTERS>) => { setTable((current) => ({ ...current, ...patch })); setPage(1); };
  const commitOp = () => { if (opDraft.trim() !== table.op) change({ op: opDraft.trim() }); };
  const clearTable = () => { setOpDraft(""); change(EMPTY_STATUS_FILTERS); };
  const extraFilters = (
    <>
      <label>OP
        <input
          value={opDraft}
          onChange={(event) => setOpDraft(event.target.value)}
          onBlur={commitOp}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commitOp(); } }}
          placeholder="Todas"
        />
      </label>
      <SearchPick label="Recurso" value={table.recurso} options={(options?.recursos ?? []).map((item) => ({ value: item.codigo, label: item.nome }))} onPick={(value) => change({ recurso: value })} />
      <SearchPick label="Status" value={table.status} options={toOptions(options?.status)} onPick={(value) => change({ status: value })} />
      <SearchPick label="Classificação" value={table.classe} options={toOptions(options?.classes, statusClassName)} onPick={(value) => change({ classe: value })} />
      <label>Situação
        <select value={table.aberto} onChange={(event) => change({ aberto: event.target.value })}>
          <option value="">Todos</option>
          <option value="1">Só em aberto</option>
        </select>
      </label>
    </>
  );
  return (
    <PageFrame staleError={query.error} {...frame} extraFilters={extraFilters} onClearFilters={clearTable}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Eventos de status" value={formatNumber(summary?.eventos ?? 0)} />
        <MetricCard label="Recursos" value={formatNumber(summary?.recursos ?? 0)} accent="teal" />
        <MetricCard label="Paradas não planejadas" value={formatNumber(summary?.paradas_nao_planejadas ?? 0)} accent="danger" />
        <MetricCard label="Em aberto" value={formatNumber(summary?.em_aberto ?? 0)} detail="Status que ainda não terminou" accent="warning" />
      </div>
      <SectionCard title="Eventos de status do período" className="content-section section-card--table">
        <DataTable
          rows={data?.items ?? []}
          rowKey={(row) => row.id}
          rowClassName={statusRowClass}
          columns={STATUS_COLUMNS}
        />
        {total > STATUS_PAGE_SIZE ? (
          <div className="filter-bar__row" role="navigation" aria-label="Páginas dos eventos">
            <button type="button" className="filter-bar__reset" disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button>
            <span>
              {formatNumber((page - 1) * STATUS_PAGE_SIZE + 1)}–{formatNumber(Math.min(page * STATUS_PAGE_SIZE, total))} de {formatNumber(total)}
            </span>
            <button type="button" className="filter-bar__reset" disabled={page >= pages} onClick={() => setPage(page + 1)}>Próxima</button>
          </div>
        ) : null}
      </SectionCard>
    </PageFrame>
  );
}

export function AuditProductionEventsPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<EventsPage<ProductionEvent, { eventos: number; quantidade_boa: number; quantidade_refugo: number; quantidade_retrabalho: number; quantidade_sem_evento: number }>>(`/api/v1/audit/production-events?${filters.query}&page=1&page_size=200`);
  const title = "Auditoria — Eventos de Produção";
  const subtitle = "O que foi executado: OP, produto, operação, recurso e colaborador, com tempo real e quantidades.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const summary = query.data?.summary;
  const orphans = summary?.quantidade_sem_evento ?? 0;
  return (
    <PageFrame staleError={query.error} sectionId="audit" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Eventos de produção" value={formatNumber(summary?.eventos ?? 0)} detail={orphans ? `${formatNumber(orphans)} quantidade(s) sem evento` : undefined} />
        <MetricCard label="Peças boas" value={formatNumber(summary?.quantidade_boa ?? 0)} accent="success" />
        <MetricCard label="Refugo" value={formatNumber(summary?.quantidade_refugo ?? 0)} accent="danger" />
        <MetricCard label="Retrabalho" value={formatNumber(summary?.quantidade_retrabalho ?? 0)} accent="warning" />
      </div>
      <SectionCard title="Eventos de produção do período" className="content-section section-card--table">
        <DataTable
          rows={query.data?.items ?? []}
          rowKey={productionRowKey}
          columns={PRODUCTION_COLUMNS}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function AuditAlertsIssuesPage() {
  const filters = useManagementFilters();
  const alertsQuery = useApiQuery<AlertsResponse>(`/api/v1/management/alerts?${filters.query}`);
  const internos = useApiQuery<InternalAlertsResponse>("/api/v1/management/internal-alerts");
  const query = useApiQuery<AuditResponse>(`/api/v1/audit?${filters.query}&page=1&page_size=200`);
  const waivers = useApiQuery<PagedInspectionWaivers>(`/api/v1/traceability/inspection-waivers?${filters.query}&page=1&page_size=200`);
  const title = "Auditoria — Alertas e inconsistências";
  const subtitle = "Desvios do período, alertas internos e conflitos ou lacunas preservados como evidência, sem reescrever histórico nem inventar confiança estatística.";
  if (alertsQuery.loading || query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  const failed = alertsQuery.error && !alertsQuery.data ? alertsQuery.error : query.error && !query.data ? query.error : null;
  if (failed) {
    return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><ErrorState error={failed} onRetry={() => { alertsQuery.reload(); query.reload(); }} /></PageFrame>;
  }
  const alerts = alertsQuery.data;
  const data = query.data;
  const auditNode = (metric: string, label: string, value: number | undefined) => (
    typeof value === "number" && value > 0 ? (
      <ExplainableValue metric={metric} filters={filters.filters} context={`${label} ${formatNumber(value)}`}>{formatNumber(value)}</ExplainableValue>
    ) : undefined
  );
  return (
    <PageFrame
      staleError={alertsQuery.error ?? query.error}
      sectionId="audit"
      title={title}
      subtitle={subtitle}
      summary={(
        <SectionCard title="Alertas — resumo do período" className="content-section">
          <div className="metric-grid metric-grid--four" role="group" aria-label="Resumo dos alertas">
            <MetricCard label="Críticos" value={formatNumber(alerts?.by_severity.critico ?? 0)} valueNode={auditNode("qld.auditoria.critico", "Alertas críticos", alerts?.by_severity.critico)} accent="danger" />
            <MetricCard label="Erros" value={formatNumber(alerts?.by_severity.erro ?? 0)} valueNode={auditNode("qld.auditoria.erro", "Alertas com erro", alerts?.by_severity.erro)} accent="danger" />
            <MetricCard label="Atenções" value={formatNumber(alerts?.by_severity.aviso ?? 0)} valueNode={auditNode("qld.auditoria.aviso", "Alertas de atenção", alerts?.by_severity.aviso)} accent="warning" />
            <MetricCard label="Total" value={formatNumber(alerts?.count ?? 0)} valueNode={auditNode("qld.auditoria.total", "Total de alertas", alerts?.count)} accent="primary" detail={alerts?.reliability_reason} />
          </div>
        </SectionCard>
      )}
    >
      <SectionCard title="Alertas do período" className="content-section">
        <DataTable
          rows={alerts?.items ?? []}
          rowKey={(row, index) => row.id ?? `${row.type}-${index}`}
          columns={[
            { key: "type", label: "Tipo", render: (row) => humanize(row.type ?? row.tipo) },
            { key: "message", label: "Ocorrência / motivo", render: (row) => displayText(row.message ?? row.mensagem, "Não informado") },
            { key: "sector", label: "Setor", render: (row) => displayName(row.sector) },
            { key: "resource", label: "Recurso / máquina", render: (row) => displayName(row.resource) },
            { key: "duration", label: "Duração / impacto", render: (row) => typeof row.seconds === "number" ? formatHours(row.seconds) : "Não mensurado" },
            { key: "situation", label: "Situação", render: (row) => <StatusBadge value={row.severity ?? row.severidade} /> },
          ]}
        />
      </SectionCard>
      <SectionCard title="Alertas internos — notificação pendente" className="content-section section-card--table">
        {internos.loading && !internos.data ? <LoadingState /> : internos.error && !internos.data ? <ErrorState error={internos.error} onRetry={internos.reload} /> : (internos.data?.items ?? []).length ? (
          <DataTable
            rows={internos.data?.items ?? []}
            rowKey={(row) => row.id}
            columns={[
              { key: "tipo", label: "Tipo", render: (row) => humanize(row.tipo) },
              { key: "op", label: "OP", render: (row) => row.codigo_op ?? "—" },
              { key: "setor", label: "Setor", render: (row) => displayName(row.tipo_setor, "—") },
              { key: "recurso", label: "Recurso", render: (row) => row.codigo_recurso ?? "—" },
              { key: "quantidade", label: "Qtd.", render: (row) => (row.quantidade == null ? "—" : formatNumber(row.quantidade)) },
              { key: "destinatario", label: "Destinatário", render: (row) => humanize(row.destinatario) },
              { key: "mensagem", label: "Ocorrência", render: (row) => displayText(row.titulo) },
              { key: "situacao", label: "Notificação", render: (row) => <StatusBadge value={row.status_notificacao} /> },
            ]}
          />
        ) : (
          <EmptyState
            title="Nenhum alerta interno registrado"
            detail="Retrabalho, refugo e necessidade de reposição aparecem aqui assim que acontecem."
          />
        )}
      </SectionCard>
      <SectionCard title="Inspeções dispensadas no período" className="content-section section-card--table">
        {waivers.error && !waivers.data ? (
          <ErrorState error={waivers.error} onRetry={waivers.reload} />
        ) : waivers.loading && !waivers.data ? (
          <LoadingState />
        ) : (waivers.data?.items ?? []).length ? (
          <DataTable
            rows={waivers.data?.items ?? []}
            rowKey={(row, index) => row.inspecao_id ?? index}
            columns={[
              { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "—" },
              { key: "operation", label: "Operação", render: (row) => displayName(row.operacao == null ? null : String(row.operacao), "—") },
              { key: "resource", label: "Recurso", render: (row) => displayName(row.recurso, "—") },
              { key: "sector", label: "Setor", render: (row) => displayName(row.setor, "—") },
              { key: "product", label: "Produto", render: (row) => displayText(row.produto, "—") },
              { key: "quantity", label: "Qtd.", sortValue: (row) => row.quantidade, render: (row) => (row.quantidade == null ? "—" : formatNumber(row.quantidade)) },
              { key: "reason", label: "Motivo", render: (row) => displayText(row.motivo, "—") },
              { key: "by", label: "Autorizado por", render: (row) => displayName(row.autorizado_por, "—") },
              { key: "badge", label: "Crachá", render: (row) => row.cracha || "—" },
              { key: "date", label: "Data", sortValue: (row) => row.dispensada_em, render: (row) => (row.dispensada_em ? formatDateTime(row.dispensada_em) : "—") },
            ]}
          />
        ) : (
          <EmptyState
            title="Nenhuma inspeção dispensada no período"
            detail="Quando a Qualidade dispensar uma inspeção, o motivo, quem autorizou e o crachá aparecem aqui."
          />
        )}
      </SectionCard>
      <SectionCard title="Inconsistências — resumo do período" className="content-section">
        <div className="metric-grid metric-grid--four" role="group" aria-label="Resumo das inconsistências">
          <MetricCard label="Críticas" value={formatNumber(data?.by_severity.critico ?? 0)} valueNode={auditNode("qld.auditoria.critico", "Inconsistências críticas", data?.by_severity.critico)} accent="danger" />
          <MetricCard label="Erros" value={formatNumber(data?.by_severity.erro ?? 0)} valueNode={auditNode("qld.auditoria.erro", "Inconsistências com erro", data?.by_severity.erro)} accent="danger" />
          <MetricCard label="Atenções" value={formatNumber(data?.by_severity.aviso ?? 0)} valueNode={auditNode("qld.auditoria.aviso", "Inconsistências de atenção", data?.by_severity.aviso)} accent="warning" />
          <MetricCard label="Total" value={formatNumber(data?.count ?? 0)} valueNode={auditNode("qld.auditoria.total", "Total de inconsistências", data?.count)} />
        </div>
      </SectionCard>
      <SectionCard title="Inconsistências detectadas" className="content-section section-card--table">
        <DataTable
          rows={data?.issues ?? []}
          rowKey={(row, index) => row.id ?? `${row.type}-${index}`}
          columns={[
            { key: "severity", label: "Severidade", render: (row) => <StatusBadge value={row.severity ?? row.severidade} /> },
            { key: "type", label: "Tipo", render: (row) => humanize(row.type ?? row.tipo) },
            { key: "message", label: "Descrição", render: (row) => displayText(row.message ?? row.mensagem) },
            { key: "sector", label: "Setor", render: (row) => displayName(row.sector) },
            { key: "resource", label: "Recurso", render: (row) => displayName(row.resource) },
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "—" },
            { key: "start", label: "Início", render: (row) => formatDateTime(row.start) },
            { key: "source", label: "Fonte", render: (row) => displayName(row.source) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function AuditReliabilityPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<ReliabilityResponse>(`/api/v1/audit/reliability?${filters.query}`);
  const title = "Auditoria — Confiabilidade dos dados";
  const subtitle = "Qualidade das fontes e cobertura observada, sem percentual inventado.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  return (
    <PageFrame staleError={query.error} sectionId="audit" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Registros analisados" value={formatNumber(data?.records_analyzed)} />
        <MetricCard label="Estados físicos" value={formatNumber(data?.resource_states_analyzed)} accent="success" />
        <MetricCard label="Sessões de rateio" value={formatNumber(data?.rateio_sessions_analyzed)} accent="teal" />
        <MetricCard label="Confiabilidade" value={data?.reliability_percentage === null ? "Não configurada" : `${formatNumber(data?.reliability_percentage, 1)}%`} detail={data?.reliability_reason} accent="warning" availability={data?.reliability_percentage === null ? "nao_configurado" : "disponivel"} />
      </div>
      <div className="two-column-grid content-section">
        <SectionCard title="Cobertura do período">
          <div className="quality-summary">
            <div><span>Apontamentos analisados</span><strong>{formatNumber(data?.records_analyzed)}</strong></div>
            <div><span>Estados físicos de recurso</span><strong>{formatNumber(data?.resource_states_analyzed)}</strong></div>
            <div><span>Sessões de rateio</span><strong>{formatNumber(data?.rateio_sessions_analyzed)}</strong></div>
            <div><span>Inconsistências abertas</span><strong>{formatNumber(Object.values(data?.by_severity ?? {}).reduce((total, value) => total + Number(value ?? 0), 0))}</strong></div>
          </div>
        </SectionCard>
        <SectionCard title="Distribuição das inconsistências">
          {Object.keys(data?.by_severity ?? {}).length ? (
            <DataTable
              rows={Object.entries(data?.by_severity ?? {})}
              rowKey={(row) => row[0]}
              columns={[
                { key: "severity", label: "Severidade", render: (row) => <StatusBadge value={row[0]} /> },
                { key: "count", label: "Ocorrências", render: (row) => formatNumber(row[1]) },
              ]}
            />
          ) : <EmptyState />}
        </SectionCard>
      </div>
    </PageFrame>
  );
}

