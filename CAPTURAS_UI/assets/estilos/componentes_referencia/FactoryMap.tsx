import { useMemo, useState } from "react";
import type { MouseEvent } from "react";
import type { MetricValue } from "../types/api";
import type { AndonResource, AndonSnapshot } from "../types/andon";
import {
  MAP_AREAS,
  MAP_LEGEND,
  MAP_RESTROOM_LINES,
  MAP_STRUCTURE,
  MAP_VIEWBOX,
  buildFactoryMap,
  tileLayout,
} from "../utils/factoryMap";
import { formatDuration } from "../utils/format";

function metricText(metric: MetricValue | undefined) {
  if (!metric || metric.value === null || metric.value === undefined) return "—";
  return `${metric.value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}${metric.unit ?? "%"}`;
}

function qty(value: number | null | undefined) {
  return value === null || value === undefined ? "—" : value.toLocaleString("pt-BR");
}

/** Cartão do hover (só na visão gerencial): estado, indicadores e o que está apontado no recurso. */
function MapTileCard({ resource, x, y, flip }: { resource: AndonResource; x: number; y: number; flip: boolean }) {
  const { state, metrics, operation, cut, ops_ativas: ops } = resource;
  const headline = state.display_label || state.label;
  const reasonText = state.reason || state.activity_description;
  const detail = reasonText && reasonText !== headline ? reasonText : null;
  const extraOps = ops && ops.length > 1 ? ops : null;
  return (
    <aside className="andon-map__card" style={{ top: y, ...(flip ? { right: x } : { left: x }) }} role="tooltip">
      <h3>{resource.name} <small>{resource.code}</small></h3>
      <p className="andon-map__card-state">
        {headline}
        {state.duration_seconds != null ? ` · ${formatDuration(state.duration_seconds)}` : ""}
      </p>
      {detail ? <p className="andon-map__card-detail">{detail}</p> : null}
      <dl className="andon-map__card-metrics">
        <div><dt>OEE</dt><dd>{metricText(metrics.oee)}</dd></div>
        <div><dt>Disp.</dt><dd>{metricText(metrics.availability)}</dd></div>
        <div><dt>Perf.</dt><dd>{metricText(metrics.performance)}</dd></div>
        <div><dt>FTT</dt><dd>{metricText(metrics.ftt)}</dd></div>
      </dl>
      {operation ? (
        <dl className="andon-map__card-op">
          {operation.op ? <div><dt>OP</dt><dd>{operation.op}</dd></div> : null}
          {operation.product ? <div><dt>Produto</dt><dd>{operation.product_description || operation.product}</dd></div> : null}
          {operation.operation_description || operation.operation ? <div><dt>Operação</dt><dd>{operation.operation_description || operation.operation}</dd></div> : null}
          {operation.operator ? <div><dt>Operador</dt><dd>{operation.operator}</dd></div> : null}
          {operation.planned_quantity != null || operation.good_quantity != null ? (
            <div><dt>Boas / plan.</dt><dd>{qty(operation.good_quantity)} / {qty(operation.planned_quantity)}</dd></div>
          ) : null}
        </dl>
      ) : null}
      {cut && (cut.task || cut.plan) ? (
        <dl className="andon-map__card-op">
          {cut.task ? <div><dt>Tarefa</dt><dd>{cut.task}</dd></div> : null}
          {cut.plan ? <div><dt>Plano</dt><dd>{cut.plan}</dd></div> : null}
        </dl>
      ) : null}
      {extraOps ? <p className="andon-map__card-detail">{extraOps.length} OPs ativas: {extraOps.map((o) => o.op).join(", ")}</p> : null}
      {!operation && !extraOps && !cut ? <p className="andon-map__card-detail">Nada apontado agora.</p> : null}
    </aside>
  );
}

/**
 * Planta da fábrica: cada recurso é uma pastilha colorida pelo estado dentro da sua área.
 * `interactive` (gestão): passar o mouse numa pastilha abre o cartão com OEE e o apontamento; a TV não usa.
 */
export function FactoryMap({ sectors, interactive = false }: { sectors: AndonSnapshot["sectors"]; interactive?: boolean }) {
  const model = useMemo(() => buildFactoryMap(sectors), [sectors]);
  const [hover, setHover] = useState<{ key: string; x: number; y: number; flip: boolean } | null>(null);
  const hovered = hover ? Object.values(model.tiles).flat().find((tile) => tile.key === hover.key) : undefined;
  const track = (key: string) => (event: MouseEvent<SVGGElement>) => {
    const box = event.currentTarget.ownerSVGElement?.parentElement?.getBoundingClientRect();
    if (!box) return;
    const x = event.clientX - box.left;
    const flip = x > box.width / 2;
    setHover({ key, x: flip ? box.width - x + 14 : x + 14, y: Math.min(event.clientY - box.top + 14, box.height - 40), flip });
  };
  return (
    <div className="andon-map">
      <header className="andon-map__header">
        <h2>Mapa da fábrica</h2>
        <span>{model.total - model.unplaced} de {model.total} recursos na planta</span>
      </header>
      <svg className="andon-map__plan" viewBox={MAP_VIEWBOX} preserveAspectRatio="xMidYMid meet" role="img" aria-label="Planta da fábrica com o estado de cada recurso">
        <defs>
          <pattern id="andon-map-hatch" width="12" height="12" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="12" height="12" className="andon-map__hatch-bg" />
            <line x1="0" y1="0" x2="0" y2="12" className="andon-map__hatch-line" />
          </pattern>
        </defs>
        {MAP_STRUCTURE.map((box) => (
          <rect
            key={`${box.x}-${box.y}`}
            className={`andon-map__structure${box.strong ? " andon-map__structure--strong" : ""}${box.thin ? " andon-map__structure--thin" : ""}${box.shaded ? " andon-map__structure--shaded" : ""}`}
            x={box.x} y={box.y} width={box.w} height={box.h}
          />
        ))}
        {MAP_RESTROOM_LINES.map((line) => (
          <line key={`${line.x1}-${line.y1}`} className="andon-map__structure andon-map__structure--thin" x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2} />
        ))}
        {MAP_AREAS.map((area) => {
          const tiles = model.tiles[area.id] ?? [];
          const boxes = tileLayout(area, tiles.map((tile) => tile.label));
          const labelY = tiles.length ? area.y + (area.h > 200 ? 58 : 28) : area.y + area.h / 2 + 8;
          return (
            <g key={area.id} data-area={area.id}>
              <rect
                className={`andon-map__area${tiles.length ? "" : " andon-map__area--idle"}`}
                x={area.x} y={area.y} width={area.w} height={area.h} rx={3}
              />
              <text className="andon-map__label" x={area.x + area.w / 2} y={labelY} textAnchor="middle" style={area.fontSize ? { fontSize: area.fontSize } : undefined}>
                {area.label}
              </text>
              {tiles.map((tile, index) => (
                <g
                  key={tile.key}
                  className={`andon-map__tile andon-map__tile--${tile.state}${interactive ? " andon-map__tile--hover" : ""}`}
                  {...(interactive ? { onMouseEnter: track(tile.key), onMouseMove: track(tile.key), onMouseLeave: () => setHover(null) } : {})}
                >
                  {interactive ? null : <title>{tile.title}</title>}
                  <rect x={boxes[index].x} y={boxes[index].y} width={boxes[index].width} height={boxes[index].height} rx={5} />
                  <text
                    x={boxes[index].x + boxes[index].width / 2}
                    y={boxes[index].y + boxes[index].height / 2 + (boxes[index].height < 30 ? 4.5 : 5)}
                    textAnchor="middle"
                    textLength={boxes[index].textLength}
                    lengthAdjust="spacingAndGlyphs"
                    style={boxes[index].height < 30 ? { fontSize: 13 } : undefined}
                  >{tile.label}</text>
                </g>
              ))}
            </g>
          );
        })}
      </svg>
      {interactive && hover && hovered ? <MapTileCard resource={hovered.resource} x={hover.x} y={hover.y} flip={hover.flip} /> : null}
      <footer className="andon-map__legend">
        {MAP_LEGEND.map((item) => (
          <span className="andon-map__legend-item" key={item.state}>
            <i className={`andon-map__swatch andon-map__swatch--${item.state}`} />
            {item.label}
          </span>
        ))}
        <span className="andon-map__legend-item">
          <i className="andon-map__swatch andon-map__swatch--idle" />
          Área sem apontamento
        </span>
        {model.unplaced ? <strong className="andon-map__unplaced">{model.unplaced} recurso(s) fora da planta</strong> : null}
      </footer>
    </div>
  );
}
