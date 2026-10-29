import { Link, useParams } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { AreaQueuePanel } from "./AreaQueuePanel";
import { isProducing, isStopped } from "../operations/operationsExplanations";
import { resourceCountNode } from "../operations/OperationsPages";
import type { ResourceRow } from "../../types/management";
import { displayName, formatDateTime, formatDuration, formatNumber, formatResourceName } from "../../utils/format";

interface ResourcePage {
  items: ResourceRow[];
}

const norm = (value?: string | null) => String(value ?? "").trim().toLocaleLowerCase("pt-BR");

/**
 * Uma área da fábrica (Serra, Solda…): os recursos dos setores dela, no dia
 * corrente. A lista de áreas e quem enxerga qual vêm da sessão (`user.areas`,
 * `app/core/areas.py`); quem abre a URL de uma área que não é sua vê o aviso.
 */
export function AreaPage() {
  const { areaId } = useParams();
  const { user } = useAuth();
  const filters = useManagementFilters();
  const area = user?.areas?.find((item) => item.id === areaId);
  const query = useApiQuery<ResourcePage>(
    area ? `/api/v1/operations/resources?${filters.dailyQuery}&page=1&page_size=200` : null,
  );
  if (!area) {
    return (
      <div className="page-wrap">
        <section className="page-panel">
          <EmptyState title="Área indisponível para a sua conta" detail="Esta área não faz parte do seu setor. Peça a um administrador se precisar de acesso." />
        </section>
      </div>
    );
  }
  const title = `Área — ${area.label}`;
  const subtitle = `Recursos de ${area.setores.join(", ")} no dia corrente: estado, OP, operador e duração.`;
  if (query.loading) return <PageFrame sectionId={`area-${area.id}`} title={title} subtitle={subtitle} period={false} filters={false}><LoadingState /></PageFrame>;
  if (query.error && !query.data) return <PageFrame sectionId={`area-${area.id}`} title={title} subtitle={subtitle} period={false} filters={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  const setores = area.setores.map(norm);
  const rows = (query.data?.items ?? []).filter((row) => setores.includes(norm(row.setor)));
  const producing = rows.filter(isProducing).length;
  const stopped = rows.filter(isStopped).length;
  const activeOps = rows.reduce((total, row) => total + row.quantidade_ops_ativas, 0);
  const scopeNote = `Recursos dos setores da área ${area.label}: ${area.setores.join(", ")}.`;
  return (
    <PageFrame staleError={query.error} sectionId={`area-${area.id}`} title={title} subtitle={subtitle} period={false} filters={false}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Recursos da área" value={formatNumber(rows.length)} />
        <MetricCard label="Em produção agora" value={`${formatNumber(producing)} de ${formatNumber(rows.length)}`} valueNode={resourceCountNode("producing", rows, producing, `${formatNumber(producing)} de ${formatNumber(rows.length)}`, scopeNote)} accent="success" />
        <MetricCard label="Parados" value={formatNumber(stopped)} valueNode={resourceCountNode("stopped", rows, stopped, formatNumber(stopped), scopeNote)} detail={stopped ? "Verifique o motivo na tabela" : "Nenhuma parada aberta"} accent={stopped ? "danger" : "success"} />
        <MetricCard label="OPs em execução" value={formatNumber(activeOps)} valueNode={resourceCountNode("activeOps", rows, activeOps, formatNumber(activeOps), scopeNote)} accent="primary" />
      </div>
      <SectionCard title="Recursos" className="content-section section-card--table">
        <DataTable
          rows={rows}
          rowKey={(row) => row.estado_recurso_id ?? `${row.setor}-${row.recurso}`}
          columns={[
            { key: "resource", label: "Recurso", render: (row) => <strong>{formatResourceName(row.recurso_nome ?? row.recurso)}</strong> },
            { key: "sector", label: "Setor", render: (row) => displayName(row.setor) },
            { key: "state", label: "Estado", render: (row) => <StatusBadge value={row.categoria ?? row.codigo_status} /> },
            { key: "op", label: "OP", render: (row) => row.ops_ativas[0]?.op ? <Link className="table-link" to={`/rastreabilidade/op-produto?op=${encodeURIComponent(row.ops_ativas[0].op!)}`}>{row.ops_ativas[0].op}</Link> : "Não disponível" },
            { key: "product", label: "Produto", render: (row) => row.ops_ativas[0]?.produto ?? "Não disponível" },
            { key: "operator", label: "Operador", render: (row) => row.ops_ativas[0]?.operador_inicio ?? "Não disponível" },
            { key: "start", label: "Início", render: (row) => formatDateTime(row.inicio) },
            { key: "duration", label: "Duração", render: (row) => formatDuration(row.duracao_segundos) },
            { key: "reason", label: "Motivo", render: (row) => displayName(row.motivo) },
          ]}
        />
      </SectionCard>
      {user?.queue_areas?.includes(area.id) && <AreaQueuePanel key={area.id} areaId={area.id} />}
    </PageFrame>
  );
}
