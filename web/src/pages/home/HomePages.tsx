import { Link } from "react-router-dom";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { SectorSummary } from "../../types/api";
import type { IssueRow } from "../../types/management";
import { formatHours, formatNumber, humanize } from "../../utils/format";

interface SectorResponse {
  items: SectorSummary[];
  highlights: Array<{ key: string; label: string; sector: string; value: number; unit: "peças" | "s" }>;
  count: number;
  data_quality: Record<string, unknown>;
}

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
 * dados: por isso vive numa seção própria, ao lado da auditoria, com o
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

function LoadingPage({ title, subtitle }: { title: string; subtitle: string }) {
  return <PageFrame sectionId="home" title={title} subtitle={subtitle}><LoadingState /></PageFrame>;
}

export function HomeSectorsPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<SectorResponse>(`/api/v1/management/sectors?${filters.query}`);
  const title = "Management View — Setores";
  const subtitle = "Comparação operacional por setor.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="home" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const rows = query.data?.items ?? [];
  return (
    <PageFrame staleError={query.error} sectionId="home" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        {(query.data?.highlights ?? []).map((highlight, index) => (
          <MetricCard
            key={highlight.key}
            label={highlight.label}
            value={highlight.unit === "s" ? formatHours(highlight.value) : `${formatNumber(highlight.value)} peças`}
            detail={highlight.sector}
            accent={(["success", "warning", "primary", "teal"] as const)[index % 4]}
          />
        ))}
      </div>
      {!rows.length ? <EmptyState title="Sem registros para o filtro selecionado" /> : null}
      <SectionCard title="Setores — execução real" className="content-section">
        <DataTable
          rows={rows}
          rowKey={(row) => row.setor}
          columns={[
            { key: "sector", label: "Setor", render: (row) => <Link className="table-link" to={`/consulta-operacional/recursos?setor=${encodeURIComponent(row.setor)}`}>{row.setor}</Link> },
            { key: "good", label: "Produção boa", render: (row) => formatNumber(row.producao_boa) },
            { key: "scrap", label: "Refugo", render: (row) => formatNumber(row.refugo) },
            { key: "rework", label: "Retrabalho", render: (row) => formatNumber(row.retrabalho) },
            { key: "ops", label: "OPs", render: (row) => row.ops },
            { key: "production", label: "Produção", render: (row) => formatHours(row.tempo_producao_segundos) },
            { key: "setup", label: "Setup", render: (row) => formatHours(row.tempo_setup_segundos) },
            { key: "downtime", label: "Paradas", render: (row) => formatHours(row.tempo_parada_segundos) },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}

export function HomeAlertsPage() {
  const filters = useManagementFilters();
  const query = useApiQuery<AlertsResponse>(`/api/v1/management/alerts?${filters.query}`);
  const internos = useApiQuery<InternalAlertsResponse>("/api/v1/management/internal-alerts");
  const title = "Management View — Alertas";
  const subtitle = "Desvios e inconsistências que exigem atenção, sem inventar confiança estatística.";
  if (query.loading) return <LoadingPage title={title} subtitle={subtitle} />;
  if (query.error && !query.data) return <PageFrame sectionId="home" title={title} subtitle={subtitle}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const data = query.data;
  if (!data) return <PageFrame sectionId="home" title={title} subtitle={subtitle}><EmptyState /></PageFrame>;
  return (
    <PageFrame staleError={query.error} sectionId="home" title={title} subtitle={subtitle}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Críticos" value={formatNumber(data.by_severity.critical ?? 0)} accent="danger" />
        <MetricCard label="Erros" value={formatNumber(data.by_severity.error ?? 0)} accent="danger" />
        <MetricCard label="Atenções" value={formatNumber(data.by_severity.warning ?? 0)} accent="warning" />
        <MetricCard label="Total" value={formatNumber(data.count)} accent="primary" detail={data.reliability_reason} />
      </div>
      <SectionCard title="Alertas do período" className="content-section">
        <DataTable
          rows={data.items}
          rowKey={(row, index) => row.id ?? `${row.type}-${index}`}
          columns={[
            { key: "type", label: "Tipo", render: (row) => humanize(row.type ?? row.tipo) },
            { key: "message", label: "Ocorrência / motivo", render: (row) => row.message ?? row.mensagem ?? "Não informado" },
            { key: "sector", label: "Setor", render: (row) => row.sector ?? "Não disponível" },
            { key: "resource", label: "Recurso / máquina", render: (row) => row.resource ?? "Não disponível" },
            { key: "duration", label: "Duração / impacto", render: (row) => typeof row.seconds === "number" ? formatHours(row.seconds) : "Não mensurado" },
            { key: "situation", label: "Situação", render: (row) => <StatusBadge value={row.severity ?? row.severidade} /> },
          ]}
        />
      </SectionCard>
      <SectionCard
        title="Alertas internos — notificação pendente"
        className="content-section section-card--table"
      >
        {(internos.data?.items ?? []).length ? (
          <DataTable
            rows={internos.data?.items ?? []}
            rowKey={(row) => row.id}
            columns={[
              { key: "tipo", label: "Tipo", render: (row) => humanize(row.tipo) },
              { key: "op", label: "OP", render: (row) => row.codigo_op ?? "—" },
              { key: "setor", label: "Setor", render: (row) => row.tipo_setor ?? "—" },
              { key: "recurso", label: "Recurso", render: (row) => row.codigo_recurso ?? "—" },
              { key: "quantidade", label: "Qtd.", render: (row) => (row.quantidade == null ? "—" : formatNumber(row.quantidade)) },
              { key: "destinatario", label: "Destinatário", render: (row) => humanize(row.destinatario) },
              { key: "mensagem", label: "Ocorrência", render: (row) => row.titulo },
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
    </PageFrame>
  );
}
