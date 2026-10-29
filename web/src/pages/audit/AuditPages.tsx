import { Link } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { ExplainableValue } from "../../components/ExplainableValue";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { ResourceDivergenceBadge } from "../../components/ResourceDivergenceBadge";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { AuditResponse, IssueRow, PagedInspectionWaivers, PagedOrders } from "../../types/management";
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

export function AuditAppointmentsPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<PagedOrders>(`/api/v1/audit/appointments?${filters.query}&page=1&page_size=200`);
  const title = "Auditoria — Apontamentos";
  const subtitle = "Registros operacionais e referências de origem para conferência.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  // Auditoria responde quem/quando/o quê. A contagem abaixo apenas resume as
  // linhas já entregues pelo backend; nenhum indicador é recalculado aqui.
  const resumo = {
    finalizados: rows.filter((row) => String(row.status ?? "") === "Finalizado").length,
    recursos: new Set(rows.map((row) => row.recurso_real).filter(Boolean)).size,
    operadores: new Set(rows.map((row) => row.operador_inicio).filter(Boolean)).size,
  };
  return (
    <PageFrame staleError={query.error} sectionId="audit" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Apontamentos" value={formatNumber(query.data?.page.total ?? 0)} />
        <MetricCard label="Finalizados" value={formatNumber(resumo.finalizados)} detail={rows.length ? `${formatNumber(rows.length - resumo.finalizados)} ainda em aberto` : undefined} accent="success" />
        <MetricCard label="Recursos envolvidos" value={formatNumber(resumo.recursos)} accent="teal" />
        <MetricCard label="Operadores envolvidos" value={formatNumber(resumo.operadores)} detail="Quem registrou no período" accent="purple" />
      </div>
      <SectionCard title="Apontamentos do período" className="content-section section-card--table">
        <DataTable
          rows={rows}
          rowKey={(row, index) => row.apontamento_id ?? index}
          columns={[
            { key: "id", label: "ID", render: (row) => row.apontamento_id ?? "Não disponível" },
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "operation", label: "Operação", render: (row) => displayName(row.operacao_atual) },
            { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
            { key: "resource", label: "Recurso", render: (row) => displayName(row.recurso_real) },
            { key: "divergence", label: "Recurso divergente", render: (row) => row.recurso_divergente ? <ResourceDivergenceBadge planned={row.recurso_planejado} actual={row.recurso_apontado || row.recurso_real} /> : "—" },
            { key: "operator", label: "Operador", render: (row) => row.operador_inicio ?? row.operador_fim ?? "Não disponível" },
            { key: "status", label: "Status", render: (row) => <StatusBadge value={row.status} /> },
            { key: "good", label: "Boas", render: (row) => formatNumber(row.quantidade_boa) },
            { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
            { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
            { key: "start", label: "Início", render: (row) => formatDateTime(row.inicio_real) },
            { key: "end", label: "Fim", render: (row) => formatDateTime(row.fim_real) },
          ]}
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
    <PageFrame staleError={alertsQuery.error ?? query.error} sectionId="audit" title={title} subtitle={subtitle}>
      <SectionCard title="Alertas — resumo do período" className="content-section">
        <div className="metric-grid metric-grid--four" role="group" aria-label="Resumo dos alertas">
          <MetricCard label="Críticos" value={formatNumber(alerts?.by_severity.critico ?? 0)} valueNode={auditNode("qld.auditoria.critico", "Alertas críticos", alerts?.by_severity.critico)} accent="danger" />
          <MetricCard label="Erros" value={formatNumber(alerts?.by_severity.erro ?? 0)} valueNode={auditNode("qld.auditoria.erro", "Alertas com erro", alerts?.by_severity.erro)} accent="danger" />
          <MetricCard label="Atenções" value={formatNumber(alerts?.by_severity.aviso ?? 0)} valueNode={auditNode("qld.auditoria.aviso", "Alertas de atenção", alerts?.by_severity.aviso)} accent="warning" />
          <MetricCard label="Total" value={formatNumber(alerts?.count ?? 0)} valueNode={auditNode("qld.auditoria.total", "Total de alertas", alerts?.count)} accent="primary" detail={alerts?.reliability_reason} />
        </div>
      </SectionCard>
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
        {(internos.data?.items ?? []).length ? (
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
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
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

