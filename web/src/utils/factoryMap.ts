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
  { id: "estoque-chapas", label: "ESTOQUE CHAPAS", x: 70, y: 192, w: 302, h: 92 },
  { id: "plasma", label: "PLASMA", x: 384, y: 192, w: 254, h: 92 },
  { id: "rebarbacao", label: "REBARBAÇÃO", x: 648, y: 192, w: 187, h: 92 },
  { id: "robo", label: "ROBÔ", x: 845, y: 192, w: 133, h: 92 },
  { id: "expedicao", label: "EXPEDIÇÃO", x: 989, y: 192, w: 237, h: 92 },
  { id: "almox", label: "ALMOX", x: 1237, y: 196, w: 145, h: 281 },
  { id: "destaque", label: "DESTAQUE", x: 70, y: 302, w: 147, h: 93 },
  { id: "laser", label: "LASER", x: 229, y: 302, w: 186, h: 93 },
  { id: "dobra", label: "DOBRA", x: 427, y: 302, w: 367, h: 93 },
  { id: "usinagem", label: "USINAGEM", x: 806, y: 303, w: 178, h: 92 },
  { id: "projetos", label: "PROJETOS / FERRAM.", x: 995, y: 303, w: 231, h: 92, fontSize: 18 },
  { id: "solda-aluminio-a", label: "SOLDA ALUM.", x: 70, y: 412, w: 154, h: 91, fontSize: 17 },
  { id: "solda-aluminio-b", label: "SOLDA DE ALUMÍNIO", x: 236, y: 412, w: 696, h: 91 },
  { id: "serras", label: "SERRAS", x: 943, y: 412, w: 282, h: 91 },
  { id: "prototipo", label: "PROTÓTIPO", x: 1237, y: 491, w: 145, h: 135, fontSize: 20 },
  { id: "estoque-tubos", label: "ESTOQUE DE TUBOS", x: 236, y: 526, w: 988, h: 87 },
  { id: "robo-solda", label: "ROBÔ DE SOLDA", x: 237, y: 632, w: 179, h: 87, fontSize: 18 },
  { id: "cab-secagem", label: "CAB. SECAGEM", x: 427, y: 632, w: 225, h: 87 },
  { id: "pintura", label: "PINTURA", x: 663, y: 632, w: 274, h: 87 },
  { id: "jateamento", label: "JATEAMENTO", x: 948, y: 632, w: 275, h: 87 },
  { id: "solda-aco", label: "SOLDA DE AÇO", x: 191, y: 742, w: 1187, h: 118 },
];

/** Traços do prédio: contorno, linha das docas, docas e banheiros. */
export const MAP_STRUCTURE = [
  { x: 48, y: 115, w: 1352, h: 785, strong: true },
  { x: 668, y: 108, w: 126, h: 67 },
  { x: 52, y: 610, w: 124, h: 295, shaded: true },
  { x: 290, y: 900, w: 82, h: 36 },
  { x: 1014, y: 900, w: 82, h: 36 },
] as const;
export const MAP_DOCK_LINE = { x1: 48, y1: 175, x2: 1400, y2: 175 } as const;

export type MapState =
  | "producao"
  | "setup"
  | "parada"
  | "parada_planejada"
  | "retrabalho"
  | "atividade_sem_op"
  | "fila"
  | "sem_demanda"
  | "fora_turno"
  | "desconhecido";

export const MAP_LEGEND: ReadonlyArray<{ state: MapState; label: string }> = [
  { state: "producao", label: "Produção" },
  { state: "setup", label: "Setup" },
  { state: "parada", label: "Parada não planejada" },
  { state: "parada_planejada", label: "Parada planejada" },
  { state: "retrabalho", label: "Retrabalho" },
  { state: "atividade_sem_op", label: "Atividade sem OP" },
  { state: "fila", label: "Fila (OP aguardando)" },
  { state: "sem_demanda", label: "Sem demanda" },
  { state: "fora_turno", label: "Fora de turno" },
];

export function mapState(resource: AndonResource): MapState {
  const { category, stop_classification: classification } = resource.state;
  if (category === "parada") return classification === "planejada" ? "parada_planejada" : "parada";
  return category;
}

export interface MapTile {
  key: string;
  label: string;
  title: string;
  state: MapState;
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
      x: area.x + 12 + col * (width + TILE_GAP),
      y: top + row * (height + TILE_GAP / 2),
      width,
      height,
      textLength: needed > width - 8 ? Math.max(10, width - 8) : undefined,
    };
  });
}
