import { Link } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { AuditResponse, PagedOrders } from "../../types/management";
import { formatDateTime, formatNumber, humanize } from "../../utils/format";

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
            { key: "operation", label: "Operação", render: (row) => row.operacao_atual ?? "Não disponível" },
            { key: "sector", label: "Setor", render: (row) => row.setor ?? "Não disponível" },
            { key: "resource", label: "Recurso", render: (row) => row.recurso_real ?? "Não disponível" },
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

export function AuditIssuesPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<AuditResponse>(`/api/v1/audit?${filters.query}&page=1&page_size=200`);
  const title = "Auditoria — Inconsistências";
  const subtitle = "Conflitos e lacunas preservados como evidência, sem reescrever histórico.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="audit" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  return (
    <PageFrame staleError={query.error} sectionId="audit" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Críticas" value={formatNumber(data?.by_severity.critical ?? 0)} accent="danger" />
        <MetricCard label="Erros" value={formatNumber(data?.by_severity.error ?? 0)} accent="danger" />
        <MetricCard label="Atenções" value={formatNumber(data?.by_severity.warning ?? 0)} accent="warning" />
        <MetricCard label="Total" value={formatNumber(data?.count ?? 0)} />
      </div>
      <SectionCard title="Inconsistências detectadas" className="content-section section-card--table">
        <DataTable
          rows={data?.issues ?? []}
          rowKey={(row, index) => row.id ?? `${row.type}-${index}`}
          columns={[
            { key: "severity", label: "Severidade", render: (row) => <StatusBadge value={row.severity ?? row.severidade} /> },
            { key: "type", label: "Tipo", render: (row) => humanize(row.type ?? row.tipo) },
            { key: "message", label: "Descrição", render: (row) => row.message ?? row.mensagem ?? "Não disponível" },
            { key: "sector", label: "Setor", render: (row) => row.sector ?? "Não disponível" },
            { key: "resource", label: "Recurso", render: (row) => row.resource ?? "Não disponível" },
            { key: "op", label: "OP", render: (row) => row.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.op)}`}>{row.op}</Link> : "Não disponível" },
            { key: "start", label: "Início", render: (row) => formatDateTime(row.start) },
            { key: "source", label: "Fonte", render: (row) => row.source ?? "Não disponível" },
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

