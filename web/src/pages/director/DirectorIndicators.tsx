import { useNavigate } from "react-router-dom";
import { directorPaths } from "../../api/client";
import { MetricCard } from "../../components/MetricCard";
import { useManagementFilters } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { DirectorIndicator, DirectorIndicators as DirectorIndicatorsData, DirectorPeriodName } from "../../types/director";
import { formatDateTime, formatNumber, formatPieces } from "../../utils/format";
import { formatHoursValue } from "./directorFormat";

function indicatorText(item: DirectorIndicator) {
  if (item.estado === "erro") return "não foi possível ler";
  if (item.valor === null) return "sem registros";
  if (item.unidade === "pecas") return formatPieces(item.valor);
  if (item.unidade === "segundos") return formatHoursValue(item.valor / 3600);
  return `${formatNumber(item.valor, 1)}%`;
}

/** Até 6 números lidos da Auditoria; o clique abre a Auditoria no mesmo período. */
export function DirectorIndicators({ periodo }: { periodo: DirectorPeriodName }) {
  const query = useApiQuery<DirectorIndicatorsData>(directorPaths.indicators(periodo));
  const { filters, setFilters } = useManagementFilters();
  const navigate = useNavigate();
  const data = query.data;
  if (!data?.itens.length) return null;

  function openAudit(tipo: string) {
    if (!data) return;
    setFilters({
      ...filters,
      startDate: data.periodo.inicio.slice(0, 10),
      endDate: data.periodo.fim.slice(0, 10),
      sector: "", resource: "", op: "", operation: "", product: "", operator: "",
    });
    navigate(`/auditoria/analitica?tipo=${tipo}`);
  }

  return (
    <section className="content-section" aria-label="Indicadores da Auditoria">
      <div className="metric-grid metric-grid--six">
        {data.itens.map((item) => (
          <MetricCard
            key={item.chave}
            label={item.rotulo}
            value={indicatorText(item)}
            detail={`Auditoria tipo ${item.tipo}`}
            accent="primary"
            onClick={() => openAudit(item.tipo)}
            actionLabel="Abrir na Auditoria"
            ariaLabel={`${item.rotulo}: ${indicatorText(item)}. Abrir na Auditoria`}
          />
        ))}
      </div>
      <p className="director-note">Mesmos números da Auditoria Analítica, calculados até {formatDateTime(data.as_of)}.</p>
    </section>
  );
}
