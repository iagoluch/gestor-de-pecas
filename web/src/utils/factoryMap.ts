import type { AndonResource, AndonSnapshot } from "../types/andon";

/**
 * Planta da fábrica para a TV do Andon. As posições e formas seguem a planta baixa
 * da manufatura (viewBox 1430x830 a partir de 10,100); só o desenho muda.
 * Cada recurso do snapshot vira uma pastilha dentro da sua área, colorida pelo
 * estado atual. Áreas sem recurso apontável (estoques, expedição…) ficam tracejadas.
 */
export const MAP_VIEWBOX = "10 100 1430 830";

export interface MapArea {
  id: string;
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
  fontSize?: number;
}

export const MAP_AREAS: ReadonlyArray<MapArea> = [
  { id: "estoque-chapas", label: "ESTOQUE CHAPAS", x: 70, y: 192, w: 306, h: 92 },
  { id: "plasma", label: "PLASMA", x: 400, y: 192, w: 248, h: 92 },
  { id: "rebarbacao", label: "REBARBAÇÃO", x: 672, y: 192, w: 178, h: 92, fontSize: 22 },
  { id: "robo", label: "ROBÔ", x: 874, y: 192, w: 128, h: 92 },
  { id: "expedicao", label: "EXPEDIÇÃO", x: 1026, y: 192, w: 164, h: 92, fontSize: 22 },
  { id: "almox", label: "ALMOX", x: 1223, y: 196, w: 159, h: 281 },
  { id: "destaque", label: "DESTAQUE", x: 70, y: 302, w: 161, h: 93 },
  { id: "laser", label: "LASER", x: 255, y: 302, w: 160, h: 93 },
  { id: "dobra", label: "DOBRA", x: 439, y: 302, w: 342, h: 93 },
  { id: "usinagem", label: "USINAGEM", x: 805, y: 303, w: 160, h: 92 },
  { id: "projetos", label: "PROJETOS / FERRAM.", x: 989, y: 303, w: 201, h: 92, fontSize: 18 },
  { id: "solda-aluminio-a", label: "SOLDA ALUM.", x: 70, y: 412, w: 156, h: 91, fontSize: 17 },
  { id: "solda-aluminio-b", label: "SOLDA DE ALUMÍNIO", x: 250, y: 412, w: 660, h: 91 },
  { id: "serras", label: "SERRAS", x: 934, y: 412, w: 256, h: 91 },
  { id: "prototipo", label: "PROTÓTIPO", x: 1240, y: 491, w: 142, h: 135, fontSize: 20 },
  { id: "estoque-tubos", label: "ESTOQUE DE TUBOS", x: 248, y: 526, w: 942, h: 87 },
  { id: "robo-solda", label: "ROBÔ DE SOLDA", x: 250, y: 632, w: 170, h: 87, fontSize: 18 },
  { id: "cab-secagem", label: "CAB. SECAGEM", x: 444, y: 632, w: 200, h: 87 },
  { id: "pintura", label: "PINTURA", x: 668, y: 632, w: 247, h: 87 },
  { id: "jateamento", label: "JATEAMENTO", x: 939, y: 632, w: 225, h: 87 },
  { id: "solda-aco", label: "SOLDA DE AÇO", x: 191, y: 742, w: 1187, h: 118 },
];

export interface StructureBox {
  x: number;
  y: number;
  w: number;
  h: number;
  /** Parede do prédio (traço grosso e escuro). */
  strong?: boolean;
  /** Detalhe (porta, doca, baia): traço fino. */
  thin?: boolean;
  shaded?: boolean;
}

/** Esquema do prédio como na planta da manufatura: anexo das docas, corpo, baias, banheiros, docas e portas. */
const DOCK_BAYS: ReadonlyArray<[number, number]> = [[319, 57], [455, 37], [556, 55], [614, 53], [848, 37], [923, 37], [978, 101], [1135, 79]];
const BOTTOM_DOCKS: ReadonlyArray<number> = [315, 1011];
export const MAP_STRUCTURE: ReadonlyArray<StructureBox> = [
  { x: 82, y: 115, w: 1284, h: 60, strong: true },
  { x: 48, y: 175, w: 1352, h: 725, strong: true },
  { x: 680, y: 106, w: 115, h: 9, thin: true },
  ...DOCK_BAYS.map(([x, w]): StructureBox => ({ x, y: 141, w, h: 34, thin: true })),
  { x: 52, y: 626, w: 124, h: 274, shaded: true, thin: true },
  ...BOTTOM_DOCKS.flatMap((x): StructureBox[] => [
    { x, y: 900, w: 76, h: 34, strong: true },
    { x: x + 12, y: 900, w: 52, h: 20, thin: true },
  ]),
  ...[262, 392].map((y): StructureBox => ({ x: 40, y, w: 8, h: 34, thin: true })),
  ...[236, 398, 534].map((y): StructureBox => ({ x: 1400, y, w: 8, h: 34, thin: true })),
];

/** Divisórias dos banheiros (baias à esquerda, escada à direita), traço fino. */
export const MAP_RESTROOM_LINES: ReadonlyArray<{ x1: number; y1: number; x2: number; y2: number }> = [
  ...[1, 2, 3, 4, 5, 6].map((i) => ({ x1: 52, y1: 626 + i * 39, x2: 128, y2: 626 + i * 39 })),
  { x1: 128, y1: 626, x2: 128, y2: 900 },
  ...[0, 1, 2, 3, 4].map((i) => ({ x1: 140, y1: 846 + i * 11, x2: 172, y2: 846 + i * 11 })),
];

export type MapState =
  | "producao"
  | "setup"
  | "parada"
  | "parada_planejada"
  | "retrabalho"
  | "atividade_sem_op"
  | "sem_demanda";

export const MAP_LEGEND: ReadonlyArray<{ state: MapState; label: string }> = [
  { state: "producao", label: "Produção" },
  { state: "setup", label: "Setup" },
  { state: "parada", label: "Parada não planejada" },
  { state: "parada_planejada", label: "Parada planejada" },
  { state: "retrabalho", label: "Retrabalho" },
  { state: "atividade_sem_op", label: "Atividade sem OP" },
  { state: "sem_demanda", label: "Sem demanda" },
];

export function mapState(resource: AndonResource): MapState {
  const { category, stop_classification: classification } = resource.state;
  if (category === "parada") return classification === "planejada" ? "parada_planejada" : "parada";
  // Recurso ocioso (fila, fora de turno, sem estado) é um só: sem demanda. A planta não distingue ociosidades.
  if (category === "fila" || category === "fora_turno" || category === "desconhecido") return "sem_demanda";
  return category;
}

export interface MapTile {
  key: string;
  label: string;
  title: string;
  state: MapState;
  resource: AndonResource;
}

/** Máximo de estações de Solda de Alumínio no bloco menor; o excedente vai ao bloco grande. */
export const ALUMINIUM_SMALL_BLOCK = 1;

// Jateamento e secagem têm bloco próprio. No catálogo, ESTUFA é só o código do recurso "SECAGEM PINTURA":
// vale o nome. Uma "estufa" que não se chame secagem fica no bloco PINTURA.
const BLAST_PATTERN = /jato|jateamento/;
const DRYING_PATTERN = /secagem/;

// Grupo (Andon) → área. O grupo Robô da Solda ocupa o bloco ROBÔ (entre Rebarbação e Expedição); o bloco
// ROBÔ DE SOLDA, mais abaixo, fica sem recurso até haver um apontável nele.
const GROUP_AREAS: Record<string, Record<string, string>> = {
  corte: { laser: "laser", plasma: "plasma", destaque: "destaque" },
  caldeiraria: { dobra: "dobra", dobras: "dobra", usinagem: "usinagem", serra: "serras", serras: "serras" },
  solda: {
    aco: "solda-aco",
    robo: "robo",
    ferramentaria: "projetos",
    prototipo: "prototipo",
  },
};

function plain(text: string | null | undefined): string {
  return String(text ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

function tileLabel(resource: AndonResource, numbered: boolean): string {
  const trailing = /(\d+)\s*$/.exec(resource.name);
  return numbered && trailing ? trailing[1] : resource.code;
}

export interface FactoryMapModel {
  tiles: Record<string, MapTile[]>;
  /** Recursos do snapshot que nenhuma área da planta recebeu — nunca somem em silêncio. */
  unplaced: number;
  total: number;
}

export function buildFactoryMap(sectors: AndonSnapshot["sectors"]): FactoryMapModel {
  const tiles: Record<string, MapTile[]> = {};
  const aluminium: AndonResource[] = [];
  const steel: AndonResource[] = [];
  let unplaced = 0;
  let total = 0;
  const place = (areaId: string, resource: AndonResource, numbered = false) => {
    const state = mapState(resource);
    (tiles[areaId] ??= []).push({
      key: `${resource.sector}-${resource.code}`,
      label: tileLabel(resource, numbered),
      title: `${resource.name} — ${resource.state.display_label || resource.state.label}`,
      state,
      resource,
    });
  };
  sectors.forEach((sector) => {
    const sectorKey = plain(sector.name);
    sector.resources.forEach((resource) => {
      total += 1;
      const group = plain(resource.group);
      if (sectorKey === "solda" && group === "aluminio") {
        aluminium.push(resource);
        return;
      }
      if (sectorKey === "solda" && group === "aco") {
        steel.push(resource);
        return;
      }
      if (sectorKey === "pintura") {
        const text = plain(`${resource.code} ${resource.name}`);
        place(BLAST_PATTERN.test(text) ? "jateamento" : DRYING_PATTERN.test(text) ? "cab-secagem" : "pintura", resource);
        return;
      }
      const areaId = GROUP_AREAS[sectorKey]?.[group];
      if (areaId) place(areaId, resource);
      else unplaced += 1;
    });
  });
  // Estações em ordem numérica (1, 2, … 10), qualquer que seja a ordem em que o snapshot as entrega.
  const byStation = (a: AndonResource, b: AndonResource) => a.name.localeCompare(b.name, "pt-BR", { numeric: true });
  steel.sort(byStation).forEach((resource) => place("solda-aco", resource, true));
  aluminium.sort(byStation).forEach((resource, index) =>
    place(index < ALUMINIUM_SMALL_BLOCK ? "solda-aluminio-a" : "solda-aluminio-b", resource, true));
  return { tiles, unplaced, total };
}

const TILE_GAP = 6;
const TILE_MAX_WIDTH = 78;
// Abaixo disso o código não é legível numa linha; a área passa a usar 2 linhas de pastilhas.
const TILE_MIN_WIDTH = 50;
const TILE_FLOOR_WIDTH = 22;
const CHAR_WIDTH = 10;

export interface TileBox {
  x: number;
  y: number;
  width: number;
  height: number;
  /** Largura a impor ao texto quando o código não cabe na pastilha; senão `undefined`. */
  textLength?: number;
}

/**
 * Geometria das pastilhas de uma área: encolhem para caber; se ficariam estreitas demais,
 * passam a 2 linhas. ponytail: com mais pastilhas que 2 linhas comportam, a largura cai até
 * TILE_FLOOR_WIDTH (texto espremido) — subir para 3 linhas se algum setor passar disso.
 */
export function tileLayout(area: MapArea, labels: ReadonlyArray<string>): TileBox[] {
  const count = labels.length;
  if (!count) return [];
  const inner = area.w - 24;
  const fit = (perRow: number) => (inner - TILE_GAP * (perRow - 1)) / perRow;
  let rows = 1;
  let perRow = count;
  if (fit(count) < TILE_MIN_WIDTH && count > 1) {
    rows = 2;
    perRow = Math.ceil(count / 2);
  }
  const width = Math.max(TILE_FLOOR_WIDTH, Math.min(TILE_MAX_WIDTH, fit(perRow)));
  const room = area.h - 52;
  const height = rows === 1 ? Math.min(46, room) : (Math.min(46, room) - TILE_GAP / 2) / 2;
  const top = area.y + area.h - 10 - (rows === 1 ? height : Math.min(46, room));
  return labels.map((label, index) => {
    const row = Math.floor(index / perRow);
    const col = index % perRow;
    const needed = label.length * CHAR_WIDTH * (rows === 1 ? 1 : 0.85);
    return {
      x: area.x + (area.w - (perRow * width + (perRow - 1) * TILE_GAP)) / 2 + col * (width + TILE_GAP),
      y: top + row * (height + TILE_GAP / 2),
      width,
      height,
      textLength: needed > width - 8 ? Math.max(10, width - 8) : undefined,
    };
  });
}
