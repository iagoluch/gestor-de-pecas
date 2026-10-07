import { useMemo } from "react";
import type { AndonSnapshot } from "../types/andon";
import {
  MAP_AREAS,
  MAP_DOCK_LINE,
  MAP_LEGEND,
  MAP_STRUCTURE,
  MAP_VIEWBOX,
  buildFactoryMap,
  tileLayout,
} from "../utils/factoryMap";

/** Planta da fábrica na TV: cada recurso é uma pastilha colorida pelo estado dentro da sua área. */
export function FactoryMap({ sectors }: { sectors: AndonSnapshot["sectors"] }) {
  const model = useMemo(() => buildFactoryMap(sectors), [sectors]);
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
            className={`andon-map__structure${"strong" in box ? " andon-map__structure--strong" : ""}${"shaded" in box ? " andon-map__structure--shaded" : ""}`}
            x={box.x} y={box.y} width={box.w} height={box.h}
          />
        ))}
        <line className="andon-map__structure" x1={MAP_DOCK_LINE.x1} y1={MAP_DOCK_LINE.y1} x2={MAP_DOCK_LINE.x2} y2={MAP_DOCK_LINE.y2} />
        {MAP_AREAS.map((area) => {
          const tiles = model.tiles[area.id] ?? [];
          const boxes = tileLayout(area, tiles.map((tile) => tile.label));
          const labelY = area.y + (area.h > 200 ? 58 : 28);
          return (
            <g key={area.id} data-area={area.id}>
              <rect
                className={`andon-map__area${tiles.length ? "" : " andon-map__area--idle"}`}
                x={area.x} y={area.y} width={area.w} height={area.h} rx={6}
              />
              <text className="andon-map__label" x={area.x + 12} y={labelY} style={area.fontSize ? { fontSize: area.fontSize } : undefined}>
                {area.label}
              </text>
              {tiles.map((tile, index) => (
                <g key={tile.key} className={`andon-map__tile andon-map__tile--${tile.state}`}>
                  <title>{tile.title}</title>
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
