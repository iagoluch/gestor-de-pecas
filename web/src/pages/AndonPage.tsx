import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useAuth } from "../auth/AuthContext";
import { AndonResourceDrawer } from "../components/AndonResourceDrawer";
import { EmptyState, ErrorState, LoadingState } from "../components/DataState";
import { useApiQuery } from "../hooks/useApiQuery";
import { useRealtimeStatus } from "../hooks/useRealtimeStatus";
import { useTvRotation } from "../hooks/useTvRotation";
import { assets } from "../config/assets";
import type { MetricValue } from "../types/api";
import type { AndonResource, AndonSnapshot } from "../types/andon";
import { formatDuration } from "../utils/format";

const ANDON_PANEL_ORDER = ["Corte", "Caldeiraria", "Solda", "Pintura"];
// Cada coluna administra a própria distribuição vertical: o painel de topo usa
// a altura exigida pelo conteúdo e o painel seguinte assume o restante. Isso
// substitui o antigo quadrante 2x2, que impunha alturas simétricas.
const ANDON_BOARD_COLUMNS: ReadonlyArray<readonly string[]> = [
  ["Corte", "Solda"],
  ["Caldeiraria", "Pintura"],
];
// Fallback para quando o painel chega do backend sem agrupamento próprio: cada
// recurso ganha o próprio quadro, como Dobra, Usinagem e Serra dentro da
// Caldeiraria. Desde a Wave 6F o painel "Solda" manda os cinco setores reais
// (Aço, Alumínio, Robô, Ferramentaria, Protótipo) em `groups`, e a divisão por
// recurso deixa de ser aplicada sozinha — exatamente como já estava previsto.
const ANDON_PER_RESOURCE_PANELS = ["Solda"];

function usesPerResourceGroups(sector: AndonSnapshot["sectors"][number]) {
  if (!ANDON_PER_RESOURCE_PANELS.includes(sector.name)) return false;
  const groups = sector.groups ?? [];
  return groups.length === 0 || (groups.length === 1 && groups[0].name === sector.name);
}
const PANEL_ICONS: Record<string, string> = {
  Corte: assets.operator.navigation.Corte,
  Caldeiraria: assets.operator.navigation.Dobra,
  Solda: assets.operator.navigation.Solda,
  Pintura: assets.operator.navigation.Pintura,
};

function sectorOrder(name: string) {
  const index = ANDON_PANEL_ORDER.indexOf(name);
  return index === -1 ? ANDON_PANEL_ORDER.length : index;
}

function boardColumns(sectors: AndonSnapshot["sectors"]) {
  const assigned = new Set<string>();
  const columns = ANDON_BOARD_COLUMNS.map((names) => names.flatMap((name) => {
    const sector = sectors.find((item) => item.name === name);
    if (!sector) return [];
    assigned.add(name);
    return [sector];
  }));
  sectors
    .filter((sector) => !assigned.has(sector.name))
    .forEach((sector, index) => columns[index % columns.length].push(sector));
  return columns.filter((column) => column.length > 0);
}

function metricText(metric: MetricValue | undefined) {
  if (!metric || metric.value === null || metric.value === undefined) return "—";
  return `${metric.value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}${metric.unit ?? "%"}`;
}

function useSnapshotClock(clock: AndonSnapshot["clock"] | undefined) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!clock?.running) return undefined;
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [clock?.now, clock?.running]);

  const now = useMemo(() => {
    const base = clock?.now ? new Date(clock.now) : new Date();
    if (Number.isNaN(base.getTime())) return new Date();
    return new Date(base.getTime() + elapsed * 1000);
  }, [clock?.now, elapsed]);
  return elapsed;
}

function MetricLine({ label, metric }: { label: string; metric: MetricValue }) {
  return (
    <div className="andon-card__metric" title={metric.reason ?? undefined}>
      <div><span>{label}</span><strong>{metricText(metric)}</strong></div>
    </div>
  );
}

function resourceKey(resource: AndonResource) {
  return `${resource.sector}\u0000${resource.code}`;
}

function stateSignature(resource: AndonResource) {
  return `${resource.state.category}\u0000${resource.state.started_at ?? ""}\u0000${resource.state.display_label ?? ""}`;
}

/** Marca o que mudou entre dois snapshots: recurso novo no Andon ou recurso que
 *  já estava e trocou de estado. A primeira carga não anima nada além da
 *  entrada natural dos cartões. */
function useResourceTransitions(snapshot: AndonSnapshot | null) {
  const [transitions, setTransitions] = useState<Record<string, "enter" | "update">>({});
  const previous = useRef<Map<string, string> | null>(null);

  useEffect(() => {
    if (!snapshot) return undefined;
    const current = new Map<string, string>();
    const changed: Record<string, "enter" | "update"> = {};
    for (const sector of snapshot.sectors) {
      for (const resource of sector.resources) {
        const key = resourceKey(resource);
        const signature = stateSignature(resource);
        current.set(key, signature);
        const before = previous.current?.get(key);
        if (previous.current === null) continue;
        if (before === undefined) changed[key] = "enter";
        else if (before !== signature) changed[key] = "update";
      }
    }
    previous.current = current;
    if (!Object.keys(changed).length) return undefined;
    setTransitions(changed);
    const timer = window.setTimeout(() => setTransitions({}), 1500);
    return () => window.clearTimeout(timer);
  }, [snapshot]);

  return transitions;
}

function ResourceCard({ resource, elapsed, transition, onOpen }: { resource: AndonResource; elapsed: number; transition?: "enter" | "update"; onOpen: (resource: AndonResource) => void }) {
  const operation = resource.operation;
  const duration = resource.state.duration_seconds;
  const liveDuration = duration === null || duration === undefined ? null : duration + elapsed;
  const oeeValue = resource.metrics.oee.value;
  const oeeStyle = {
    "--andon-oee": `${Math.min(100, Math.max(0, oeeValue ?? 0))}%`,
  } as CSSProperties;
  const operationalLabel = resource.state.category === "parada"
    ? resource.state.display_label ?? resource.state.reason ?? "Motivo não informado"
    : resource.state.display_label ?? resource.state.label;
  const hasOperation = Boolean(operation?.op || operation?.product || operation?.product_description);
  const activityDescription = resource.state.activity_description;
  return (
    <article className={`andon-card andon-card--${resource.state.category}`} data-state={resource.state.category} data-stop-classification={resource.state.stop_classification ?? undefined} data-sector={resource.panel ?? resource.sector} data-group={resource.group ?? undefined} data-active="true" data-transition={transition}>
      <header className="andon-card__header">
        <div className="andon-card__identity" title={`${resource.name} • ${resource.code}`}>
          <strong>{resource.name}</strong>
          {resource.code !== resource.name ? <span>{resource.code}</span> : null}
        </div>
        <div className="andon-card__state">
          <span><i aria-hidden="true" />{operationalLabel}</span>
          <strong>{liveDuration === null ? "—" : formatDuration(liveDuration)}</strong>
        </div>
      </header>

      <div className="andon-card__indicators">
        <button
          type="button"
          className="andon-card__oee"
          style={oeeStyle}
          title={`Ver indicadores e informações do OEE de ${resource.name}`}
          aria-label={`Ver indicadores de ${resource.name}`}
          aria-haspopup="dialog"
          onClick={() => onOpen(resource)}
        >
          <span>OEE</span>
          <strong>{metricText(resource.metrics.oee)}</strong>
        </button>
        <div className="andon-card__metrics">
          <MetricLine label="Disp." metric={resource.metrics.availability} />
          <MetricLine label="Perf." metric={resource.metrics.performance} />
          <MetricLine label="FTT" metric={resource.metrics.ftt} />
        </div>
      </div>

      {hasOperation ? (
        <div className="andon-card__operation">
          {operation?.op ? <div><span>OP</span><strong>{operation.op}{operation.operation !== null && operation.operation !== undefined ? ` • ${operation.operation}` : ""}</strong></div> : null}
          {operation?.product || operation?.product_description ? (
            <div title={operation.product_description ?? operation.product ?? undefined}>
              <span>Produto</span><strong>{operation.product_description ?? operation.product}</strong>
            </div>
          ) : null}
          {resource.active_operations > 1 ? <small>+ {resource.active_operations - 1} OP(s) simultânea(s)</small> : null}
        </div>
      ) : activityDescription && activityDescription !== operationalLabel ? (
        <div className="andon-card__activity" title={activityDescription}>{activityDescription}</div>
      ) : null}
    </article>
  );
}

function SectorPanel({ sector, elapsed, transitions, onOpen }: {
  sector: AndonSnapshot["sectors"][number];
  elapsed: number;
  transitions: Record<string, "enter" | "update">;
  onOpen: (resource: AndonResource) => void;
}) {
  const perResource = usesPerResourceGroups(sector);
  const groups = perResource
    ? sector.resources.map((resource) => ({ key: resourceKey(resource), name: resource.name, resources: [resource] }))
    : (sector.groups?.length
      ? sector.groups.map((group) => ({ key: group.name, name: group.name, resources: group.resources }))
      : [{ key: sector.name, name: sector.name, resources: sector.resources }]);
  const count = sector.resource_count ?? sector.resources.length;
  const density = count > 6 ? "high" : count > 3 ? "medium" : "normal";
  const maximumGroupLoad = Math.max(1, ...groups.map((group) => group.resources.length));
  const hideSingleGroupTitle = !perResource && groups.length === 1 && groups[0].name === sector.name;
  return (
    <section
      className="andon-sector-panel"
      data-panel={sector.name}
      data-density={density}
      data-groups={groups.length}
      data-group-flow={perResource ? "wrap" : "columns"}
      aria-labelledby={`andon-sector-${sector.name}`}
      style={{ "--andon-panel-rows": maximumGroupLoad } as CSSProperties}
    >
      <header className="andon-sector-panel__header">
        <div><img src={PANEL_ICONS[sector.name]} alt="" aria-hidden="true" /><h2 id={`andon-sector-${sector.name}`}>{sector.name}</h2></div>
        <strong>RECURSOS ATIVOS <span>({count})</span></strong>
      </header>
      {count === 0 ? (
        <div className="andon-sector-panel__empty">Nenhum recurso ativo</div>
      ) : (
        <div className="andon-sector-panel__groups" style={{ "--andon-group-count": groups.length } as CSSProperties}>
          {groups.map((group) => (
            <section
              className="andon-resource-group"
              key={group.key}
              aria-label={`${sector.name} — ${group.name}`}
              data-stack={group.resources.length}
            >
              {!hideSingleGroupTitle ? (
                <header className="andon-resource-group__header"><h3>{group.name}</h3><span>ATIVOS ({group.resources.length})</span></header>
              ) : null}
              <div className="andon-resource-group__cards" style={{ "--andon-resource-count": group.resources.length } as CSSProperties}>
                {group.resources.map((resource) => (
                  <ResourceCard
                    key={`${resource.sector}-${resource.code}-${resource.state.category}-${resource.state.started_at ?? ""}`}
                    resource={resource}
                    elapsed={elapsed}
                    transition={transitions[resourceKey(resource)]}
                    onOpen={onOpen}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

export function AndonPage() {
  const { user } = useAuth();
  const query = useApiQuery<AndonSnapshot>("/api/v1/andon", { ignoreLiveTick: true });
  const realtime = useRealtimeStatus();
  const elapsed = useSnapshotClock(query.data?.clock);
  const transitions = useResourceTransitions(query.data ?? null);
  const [selectedResourceKey, setSelectedResourceKey] = useState<string | null>(null);
  // O Andon continua sendo o Andon: a única adição da Wave 6D é entrar no ciclo
  // automático da TV, que troca de visão a cada 10 segundos no perfil dedicado.
  useTvRotation("/andon");
  const closeResource = useCallback(() => setSelectedResourceKey(null), []);
  const pageClass = `andon-page andon-page--single-view ${user?.role === "andon" ? "andon-page--tv" : "andon-page--manager"}`;

  useEffect(() => {
    if (realtime === "connected") return undefined;
    const fallback = window.setInterval(query.reload, 30_000);
    return () => window.clearInterval(fallback);
  }, [query.reload, realtime]);

  if (query.loading && !query.data) {
    return <main className={pageClass}><LoadingState label="Carregando Andon Geral…" /></main>;
  }
  if (query.error && !query.data) {
    return <main className={pageClass}><ErrorState error={query.error} onRetry={query.reload} /></main>;
  }
  if (!query.data) {
    return <main className={pageClass}><EmptyState title="Nenhum recurso disponível para o Andon." /></main>;
  }

  const data = query.data;
  const sectors = [...data.sectors].sort((left, right) => {
    const rank = sectorOrder(left.name) - sectorOrder(right.name);
    return rank || left.name.localeCompare(right.name, "pt-BR");
  });
  const resources = sectors.flatMap((sector) => sector.resources);
  const columns = boardColumns(sectors);
  const boardStyle = { "--andon-column-count": columns.length } as CSSProperties;
  const selectedResource = resources.find((resource) => resourceKey(resource) === selectedResourceKey) ?? null;
  return (
    <main className={pageClass} data-simulation={data.simulation_only ? "true" : undefined}>
      <h1 className="visually-hidden">Andon Geral</h1>
      <div className="andon-content">
        {query.error ? <div className="andon-stale" role="alert">Atualização temporariamente indisponível. O último snapshot válido permanece visível.</div> : null}
        <section className="andon-board-section" aria-labelledby="andon-resources-title">
          <h2 className="visually-hidden" id="andon-resources-title">Recursos ativos por setor</h2>
          {sectors.length ? (
            <div className="andon-board" style={boardStyle}>
              {columns.map((column, index) => (
                <div
                  className="andon-board__column"
                  key={column.map((item) => item.name).join("|") || index}
                  data-column={index === 0 ? "left" : "right"}
                  data-panels={column.length}
                >
                  {column.map((item) => (
                    <SectorPanel key={item.name} sector={item} elapsed={elapsed} transitions={transitions} onOpen={(resource) => setSelectedResourceKey(resourceKey(resource))} />
                  ))}
                </div>
              ))}
            </div>
          ) : <div className="andon-empty"><EmptyState title="Nenhum recurso ativo no Andon." /></div>}
        </section>
      </div>
      <AndonResourceDrawer
        resource={selectedResource}
        elapsed={elapsed}
        simulationOnly={data.simulation_only}
        onClose={closeResource}
      />
    </main>
  );
}
