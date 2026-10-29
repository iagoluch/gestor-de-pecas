import { directorPaths } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { Notice } from "../../components/Notice";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { DirectorPanel as DirectorPanelData, DirectorPeriodName, DirectorSectorRank } from "../../types/director";
import { formatNumber, formatPieces } from "../../utils/format";
import { DirectorExplainable } from "./DirectorExplainable";
import { costLine, costText, EFFICIENCY_ABOVE_100_NOTICE, efficiencyText, efficiencyValue, formatHoursValue } from "./directorFormat";

export function DirectorPanel({ periodo, onOpenSector }: { periodo: DirectorPeriodName; onOpenSector: (setor: string) => void }) {
  const query = useApiQuery<DirectorPanelData>(directorPaths.panel(periodo));
  const data = query.data;
  if (!data) {
    if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
    return <LoadingState />;
  }
  const { cards } = data;
  return (
    <>
      <div className="metric-grid metric-grid--four">
        <MetricCard
          label="Produzido"
          value={formatPieces(cards.produzido)}
          valueNode={<DirectorExplainable context={`Produzido ${formatPieces(cards.produzido)}`} target={{ metric: "dir.produzido", periodo }}>{formatPieces(cards.produzido)}</DirectorExplainable>}
          detail="Peças boas lançadas no período"
          accent="success"
        />
        <MetricCard
          label="Horas paradas"
          value={formatHoursValue(cards.horas_paradas)}
          valueNode={<DirectorExplainable context={`Horas paradas ${formatHoursValue(cards.horas_paradas)}`} target={{ metric: "dir.horas_paradas", periodo }}>{formatHoursValue(cards.horas_paradas)}</DirectorExplainable>}
          detail="Só paradas que não estavam planejadas"
          accent="warning"
        />
        <MetricCard
          label="Custo das paradas"
          value={costText(cards.custo_parada, data.custo_completo)}
          valueNode={<DirectorExplainable context={`Custo das paradas ${costText(cards.custo_parada, data.custo_completo)}`} target={{ metric: "dir.custo_parada", periodo }}>{costText(cards.custo_parada, data.custo_completo)}</DirectorExplainable>}
          detail={data.custo_completo ? "Horas paradas × valor da hora" : "Valor parcial: faltam valores da hora em Custos"}
          accent="danger"
        />
        <MetricCard
          label="Eficiência"
          value={efficiencyText(cards.eficiencia_oee)}
          valueNode={hasEfficiency(cards.eficiencia_oee)
            ? <DirectorExplainable context={`Eficiência ${efficiencyText(cards.eficiencia_oee)}`} target={{ metric: "dir.eficiencia", periodo }}>{efficiencyText(cards.eficiencia_oee)}</DirectorExplainable>
            : undefined}
          detail="Quanto do tempo virou peça boa (o mesmo OEE da Visão Geral)"
          accent="purple"
        />
      </div>
      {data.aviso ? <Notice tone="stale" className="director-warning">{data.aviso}</Notice> : null}
      {(efficiencyValue(cards.eficiencia_oee) ?? 0) > 100 ? <Notice tone="stale" className="director-warning">{EFFICIENCY_ABOVE_100_NOTICE}</Notice> : null}

      <SectionCard title="Onde mais perdemos" className="content-section">
        {data.onde_perdemos.length ? (
          <ol className="director-losses">
            {data.onde_perdemos.map((item, index) => {
              const name = item.setor ?? "Sem setor";
              const hours = formatHoursValue(item.horas_paradas);
              const cost = costLine(item.custo, item.custo_completo);
              return (
                <li key={`${name}-${index}`} className="director-loss-row">
                  <button
                    type="button"
                    className="director-loss"
                    disabled={!item.setor}
                    onClick={() => item.setor && onOpenSector(item.setor)}
                    aria-label={`Ver a ficha do setor ${name}`}
                  >
                    <span className="director-loss__rank">{index + 1}º</span>
                    <span className="director-loss__body">
                      <strong>{name}</strong>
                      <span>{item.motivo_principal ? `Principal motivo: ${item.motivo_principal}` : "Motivo não informado"}</span>
                    </span>
                  </button>
                  <span className="director-loss__numbers">
                    {item.setor ? (
                      <>
                        <strong><DirectorExplainable context={`${name}: ${hours} paradas`} target={{ metric: "dir.horas_paradas", periodo, setor: item.setor }}>{hours}</DirectorExplainable></strong>
                        <span><DirectorExplainable context={`${name}: custo ${cost}`} target={{ metric: "dir.custo_setor", periodo, setor: item.setor }}>{cost}</DirectorExplainable></span>
                      </>
                    ) : (
                      <>
                        <strong>{hours}</strong>
                        <span>{cost}</span>
                      </>
                    )}
                  </span>
                </li>
              );
            })}
          </ol>
        ) : (
          <EmptyState title="Sem paradas no período" detail="Nenhuma parada fora do planejado foi registrada." />
        )}
      </SectionCard>

      <div className="director-highlights">
        <Highlight tone="good" title="Setor que melhor aproveitou o tempo" rank={data.melhor_setor} periodo={periodo} empty="Sem dados de eficiência por setor no período." />
        <Highlight
          tone="bad"
          title="Setor que mais desperdiçou tempo"
          rank={data.pior_setor}
          periodo={periodo}
          empty={data.melhor_setor ? "Só um setor teve dados no período." : "Sem dados de eficiência por setor no período."}
        />
      </div>
    </>
  );
}

function Highlight({ tone, title, rank, periodo, empty }: { tone: "good" | "bad"; title: string; rank: DirectorSectorRank | null; periodo: DirectorPeriodName; empty: string }) {
  return (
    <article className={`director-highlight director-highlight--${tone}`}>
      <span>{title}</span>
      {rank ? (
        <>
          <strong>{rank.nome ?? "Sem setor"}</strong>
          <small>
            Eficiência de{" "}
            {rank.nome ? (
              <DirectorExplainable context={`${rank.nome}: eficiência ${formatNumber(rank.oee, 1)}%`} target={{ metric: "dir.eficiencia", periodo, setor: rank.nome }}>
                {formatNumber(rank.oee, 1)}%
              </DirectorExplainable>
            ) : `${formatNumber(rank.oee, 1)}%`}
          </small>
        </>
      ) : (
        <small>{empty}</small>
      )}
    </article>
  );
}

/** Só abre a conta quando existe um percentual; "dados insuficientes" fica texto. */
function hasEfficiency(metric: DirectorPanelData["cards"]["eficiencia_oee"]) {
  if (typeof metric === "number") return true;
  return metric !== null && metric !== undefined && metric.value !== null && metric.value !== undefined;
}
