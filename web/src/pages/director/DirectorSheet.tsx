import { directorPaths } from "../../api/client";
import { ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { Notice } from "../../components/Notice";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { DirectorCosts, DirectorPeriodName, DirectorSheet as DirectorSheetData } from "../../types/director";
import { formatNumber, formatPieces } from "../../utils/format";
import { DirectorExplainable } from "./DirectorExplainable";
import { costLine, costText, formatHoursValue } from "./directorFormat";

function sorted(values: Iterable<string>) {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b, "pt-BR"));
}

function missingDetail(complete: boolean, missing: number, fallback: string) {
  return complete ? fallback : `Valor parcial: faltam ${formatNumber(missing)} valor(es) da hora`;
}

export function DirectorSheet({ periodo, setor, recurso, onSetor, onRecurso }: {
  periodo: DirectorPeriodName;
  setor: string;
  recurso: string;
  onSetor: (value: string) => void;
  onRecurso: (value: string) => void;
}) {
  // Setores e recursos para os filtros saem do mesmo cadastro da seção Custos.
  const catalog = useApiQuery<DirectorCosts>(directorPaths.costs, { ignoreLiveTick: true });
  const query = useApiQuery<DirectorSheetData>(directorPaths.sheet(periodo, setor, recurso));
  const resources = catalog.data?.recursos ?? [];
  const sectors = sorted([...resources.flatMap((item) => (item.setor ? [item.setor] : [])), ...(setor ? [setor] : [])]);
  const resourceOptions = sorted([
    ...resources.filter((item) => !setor || item.setor === setor).map((item) => item.recurso),
    ...(recurso ? [recurso] : []),
  ]);
  const data = query.data;
  const filters = { setor: setor || undefined, recurso: recurso || undefined };
  // Cada número da ficha abre a conta com o mesmo período e os mesmos filtros da tela.
  const explain = (metric: string, context: string, text: string, extra: { motivo?: string } = {}) => (
    <DirectorExplainable context={`${context} ${text}`} target={{ metric, periodo, ...filters, ...extra }}>{text}</DirectorExplainable>
  );

  return (
    <>
      <div className="pause-form director-filters">
        <label>
          Setor
          <select value={setor} onChange={(event) => onSetor(event.target.value)}>
            <option value="">Todos os setores</option>
            {sectors.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <label>
          Recurso
          <select value={recurso} onChange={(event) => onRecurso(event.target.value)}>
            <option value="">Todos os recursos</option>
            {resourceOptions.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      </div>

      {!data && query.error ? <ErrorState error={query.error} onRetry={query.reload} /> : null}
      {!data && !query.error ? <LoadingState /> : null}
      {data ? (
        <>
          {/* A resposta pronta vem antes de qualquer número ou lista. */}
          <p className="director-sheet__text">{data.texto}</p>

          <div className="metric-grid metric-grid--five">
            <MetricCard label="Trabalhou" value={formatHoursValue(data.trabalhou_h)} valueNode={explain("dir.trabalhou", "Trabalhou", formatHoursValue(data.trabalhou_h))} detail={`de ${formatHoursValue(data.disponivel_h)} disponíveis no turno`} accent="success" />
            <MetricCard label="Produzido" value={formatPieces(data.produzido)} valueNode={explain("dir.produzido", "Produzido", formatPieces(data.produzido))} detail="Peças boas lançadas" accent="teal" />
            <MetricCard
              label="Parado"
              value={formatHoursValue(data.parado_h)}
              valueNode={explain("dir.horas_paradas", "Parado", formatHoursValue(data.parado_h))}
              detail={data.motivo_principal ? `Principal motivo: ${data.motivo_principal}` : "Só paradas que não estavam planejadas"}
              accent="warning"
            />
            <MetricCard
              label="Custo do trabalho"
              value={costText(data.custo_trabalho, data.custo_trabalho_completo)}
              valueNode={explain("dir.custo_trabalho", "Custo do trabalho", costText(data.custo_trabalho, data.custo_trabalho_completo))}
              detail={missingDetail(data.custo_trabalho_completo, data.custos_faltando_trabalho, "Horas trabalhadas × valor da hora")}
            />
            <MetricCard
              label="Custo das paradas"
              value={costText(data.custo_parada, data.custo_parada_completo)}
              valueNode={explain("dir.custo_parada", "Custo das paradas", costText(data.custo_parada, data.custo_parada_completo))}
              detail={missingDetail(data.custo_parada_completo, data.custos_faltando_parada, "Horas paradas × valor da hora")}
              accent="danger"
            />
          </div>
          {data.custo_completo ? null : (
            <Notice tone="stale" className="director-warning">
              Faltam custos de {formatNumber(data.custos_faltando)} recursos/pessoas — o valor real é maior.
            </Notice>
          )}

          <div className="director-sheet__details content-section">
            <SectionCard title="Paradas por motivo">
              {data.paradas_por_motivo.length ? (
                <ul className="director-list">
                  {data.paradas_por_motivo.map((item) => (
                    <li key={item.motivo}><span>{item.motivo}</span><strong>{explain("dir.parado_motivo", `Parado por ${item.motivo}`, formatHoursValue(item.horas), { motivo: item.motivo })}</strong></li>
                  ))}
                </ul>
              ) : (
                <p className="director-note">Nenhuma parada fora do planejado.</p>
              )}
            </SectionCard>
            <SectionCard title="Quem operou">
              {data.pessoas.length ? (
                <ul className="director-list">
                  {data.pessoas.map((person, index) => (
                    <li key={`${person.nome ?? "sem-nome"}-${index}`}>
                      <span>{person.nome ?? "Operador sem nome"}</span>
                      <span>
                        <strong>{formatHoursValue(person.horas)}</strong> · <small>{costLine(person.custo, person.custo_completo)}</small>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="director-note">Ninguém apontou trabalho neste período.</p>
              )}
            </SectionCard>
          </div>

          <SectionCard title="Tempo que não entra no custo" className="content-section">
            <ul className="director-list">
              <li><span>Sem demanda</span><strong>{formatHoursValue(data.sem_demanda_h)}</strong></li>
              <li><span>Fora do turno</span><strong>{formatHoursValue(data.fora_turno_h)}</strong></li>
            </ul>
            <p className="director-note">Recurso sem serviço ou fora do horário de trabalho não é contado como parada.</p>
          </SectionCard>
        </>
      ) : null}
    </>
  );
}
