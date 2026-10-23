import { BarList } from "../../components/BarList";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { QualityResponse, SegmentSummary, StandardRow } from "../../types/management";
import { formatHours, formatNumber } from "../../utils/format";

const TOP = 8;

/**
 * Aba Melhoria Contínua: onde a fábrica mais perde, em três listas ordenadas
 * (paradas, refugo, desvio do tempo padrão). Só reaproveita as consultas das
 * Análises; não calcula nada novo e não pede nada ao operador.
 */
export function ImprovementPage() {
  const filters = useManagementFilters();
  const downtimes = useApiQuery<SegmentSummary>(`/api/v1/analytics/downtimes?${filters.query}`);
  const quality = useApiQuery<QualityResponse>(`/api/v1/analytics/quality?${filters.query}`);
  const standard = useApiQuery<{ items: StandardRow[] }>(`/api/v1/analytics/standard-vs-actual?${filters.query}`);
  const title = "Melhoria Contínua";
  const subtitle = "Onde a fábrica mais perde no período: paradas, refugo e tempo acima do padrão.";
  const loading = downtimes.loading || quality.loading || standard.loading;
  if (loading) return <PageFrame sectionId="melhoria" title={title} subtitle={subtitle}><LoadingState /></PageFrame>;
  if (downtimes.error && quality.error && standard.error) return <PageFrame sectionId="melhoria" title={title} subtitle={subtitle}><ErrorState error={downtimes.error} onRetry={() => { downtimes.reload(); quality.reload(); standard.reload(); }} /></PageFrame>;

  const stops = (downtimes.data?.by_reason ?? [])
    .map((row) => {
      const seconds = Number(row.seconds ?? row.segundos ?? 0);
      return { label: String(row.motivo ?? "Não informado"), value: seconds, detail: formatHours(seconds) };
    })
    .sort((a, b) => b.value - a.value).slice(0, TOP);
  const scrap = (quality.data?.scrap_reasons ?? [])
    .map((row) => ({ label: String(row.motivo ?? row.razao ?? "Não informado"), value: Number(row.quantidade ?? row.count ?? 0) }))
    .sort((a, b) => b.value - a.value).slice(0, TOP);
  // Só o que passou do padrão: quem está dentro do tempo não é oportunidade.
  const slow = (standard.data?.items ?? [])
    .filter((row) => Number(row.desvio_segundos ?? 0) > 0)
    .sort((a, b) => Number(b.desvio_segundos) - Number(a.desvio_segundos)).slice(0, TOP)
    .map((row) => ({
      label: `${row.op ?? "—"} · op ${row.operacao ?? "—"} · ${row.produto ?? "sem produto"}`,
      value: Number(row.desvio_segundos),
      detail: `+${formatHours(Number(row.desvio_segundos))}`,
    }));

  return (
    <PageFrame staleError={downtimes.error ?? quality.error ?? standard.error} sectionId="melhoria" title={title} subtitle={subtitle}>
      <SectionCard title="Maiores causas de parada (tempo parado)">
        {stops.length ? <BarList data={stops} /> : <EmptyState title="Sem paradas no período" />}
      </SectionCard>
      <SectionCard title={`Maiores motivos de refugo (${formatNumber(quality.data?.totals.refugo)} peças no período)`}>
        {scrap.length ? <BarList data={scrap} unit=" pç" /> : <EmptyState title="Sem refugo no período" />}
      </SectionCard>
      <SectionCard title="Operações que passaram do tempo padrão (mais acima primeiro)">
        {slow.length ? <BarList data={slow} /> : <EmptyState title="Nenhuma operação acima do padrão" />}
      </SectionCard>
    </PageFrame>
  );
}
