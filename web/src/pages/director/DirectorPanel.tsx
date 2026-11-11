import { directorPaths } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { Notice } from "../../components/Notice";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { DirectorPanel as DirectorPanelData, DirectorPeriodName, DirectorSectorRank } from "../../types/director";
import { formatNumber } from "../../utils/format";
import { DirectorExplainable } from "./DirectorExplainable";
import { DirectorIndicators } from "./DirectorIndicators";
import { costLine, costText, EFFICIENCY_ABOVE_100_NOTICE, efficiencyValue, formatHoursValue } from "./directorFormat";

export function DirectorPanel({ periodo, onOpenSector }: { periodo: DirectorPeriodName; onOpenSector: (setor: string) => void }) {
  const query = useApiQuery<DirectorPanelData>(directorPaths.panel(periodo));
  const data = query.data;
  if (!data) {
    if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
    return <LoadingState />;
  }
  const { cards } = data;
  // Produzido, Horas paradas e Eficiência repetiam Peças boas, Horas paradas não
  // planejadas e OEE dos indicadores acima; fica só o que existe só aqui: o custo em R$.
  // Melhor setor com 0% não diz nada: vira "sem dados".
  const best = data.melhor_setor && data.melhor_setor.oee > 0 ? data.melhor_setor : null;
  return (
    <>
      <DirectorIndicators periodo={periodo} />
      <div className="metric-grid">
        <MetricCard
          label="Custo das paradas"
          value={costText(cards.custo_parada, data.custo_completo)}
          valueNode={<DirectorExplainable context={`Custo das paradas ${costText(cards.custo_parada, data.custo_completo)}`} target={{ metric: "dir.custo_parada", periodo }}>{costText(cards.custo_parada, data.custo_completo)}</DirectorExplainable>}
          detail={data.custo_completo ? "Horas paradas × valor da hora" : "Valor parcial: faltam valores da hora em Custos"}
          accent="danger"
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
        <Highlight tone="good" title="Setor que melhor aproveitou o tempo" rank={best} periodo={periodo} empty="Sem dados de eficiência por setor no período." />
        <Highlight
          tone="bad"
          title="Setor que mais desperdiçou tempo"
          rank={best ? data.pior_setor : null}
          periodo={periodo}
          empty={best ? "Só um setor teve dados no período." : "Sem dados de eficiência por setor no período."}
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
          {rank.oee > 100 ? <small className="director-highlight__warning">Acima de 100%: confira o tempo padrão deste setor.</small> : null}
        </>
      ) : (
        <small>{empty}</small>
      )}
    </article>
  );
}
