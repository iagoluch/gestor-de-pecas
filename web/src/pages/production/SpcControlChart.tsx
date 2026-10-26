import { formatNumber } from "../../utils/format";
import type { SpcLimites, SpcSinal } from "../../types/qualitySpc";

/**
 * Carta de controle em SVG. Só desenha o que a API devolveu: valor do ponto,
 * limites POR PONTO (linha escalonada quando o tamanho do subgrupo muda) e os
 * sinais já marcados em `fora_de_controle`. Nenhum limite ou sinal é calculado aqui.
 */
export interface SpcChartPoint {
  key: string | number;
  label: number;
  value: number | null;
  limits: SpcLimites | null;
  signals: SpcSinal[];
  tip: string;
}

const W = 720;
const H = 210;
const PL = 58;
const PR = 44;
const PT = 12;
const PB = 26;
const TICKS = 4;

const RULE_TEXT: Record<string, string> = {
  fora_dos_limites: "fora dos limites",
  sete_do_mesmo_lado: "7 pontos seguidos do mesmo lado",
};

export function signalText(signals: SpcSinal[]) {
  return signals.map((signal) => RULE_TEXT[signal.regra] ?? signal.regra).join(" e ");
}

/** Caminho em degraus: um trecho horizontal por ponto, na altura do limite daquele ponto. */
function stepPath(segments: Array<{ x: number; y: number }>, half: number) {
  return segments
    .map((item, index) => `${index === 0 ? "M" : "L"}${(item.x - half).toFixed(1)} ${item.y.toFixed(1)}L${(item.x + half).toFixed(1)} ${item.y.toFixed(1)}`)
    .join("");
}

export function SpcControlChart({ title, points, digits = 3, unit = "" }: {
  title: string;
  points: SpcChartPoint[];
  digits?: number;
  unit?: string;
}) {
  const count = points.length;
  const numbers: number[] = [];
  for (const point of points) {
    if (point.value !== null) numbers.push(point.value);
    if (point.limits) numbers.push(point.limits.lcl, point.limits.centro, point.limits.ucl);
  }
  if (!count || !numbers.length) return null;

  let min = Math.min(...numbers);
  let max = Math.max(...numbers);
  if (max === min) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.08;
  min -= pad;
  max += pad;

  const plotW = W - PL - PR;
  const plotH = H - PT - PB;
  const slot = plotW / count;
  const half = slot / 2;
  const x = (index: number) => PL + (index + 0.5) * slot;
  const y = (value: number) => PT + (1 - (value - min) / (max - min)) * plotH;

  const withLimits = points.map((point, index) => ({ point, index })).filter((item) => item.point.limits);
  const limitLine = (pick: (limits: SpcLimites) => number) =>
    stepPath(withLimits.map((item) => ({ x: x(item.index), y: y(pick(item.point.limits!)) })), half);
  const last = withLimits.length ? withLimits[withLimits.length - 1] : null;

  const dataPoints = points.map((point, index) => ({ point, index })).filter((item) => item.point.value !== null);
  const line = dataPoints.map((item, order) => `${order ? "L" : "M"}${x(item.index).toFixed(1)} ${y(item.point.value!).toFixed(1)}`).join("");

  const ticks = Array.from({ length: TICKS + 1 }, (_, index) => min + ((max - min) * index) / TICKS);
  const labelEvery = Math.max(1, Math.ceil(count / 12));
  const flagged = points.filter((point) => point.signals.length).length;

  return (
    <figure className="spc-chart">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${count} ponto(s), ${flagged} com sinal`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={PL} x2={W - PR} y1={y(tick)} y2={y(tick)} className="spc-chart__grid" />
            <text x={PL - 6} y={y(tick) + 4} textAnchor="end" className="spc-chart__axis">{formatNumber(tick, digits)}</text>
          </g>
        ))}
        {withLimits.length ? (
          <>
            <path d={limitLine((limits) => limits.ucl)} className="spc-chart__limit spc-chart__limit--control" data-limit="ucl" />
            <path d={limitLine((limits) => limits.centro)} className="spc-chart__limit spc-chart__limit--center" data-limit="centro" />
            <path d={limitLine((limits) => limits.lcl)} className="spc-chart__limit spc-chart__limit--control" data-limit="lcl" />
            {last ? (
              <>
                <text x={W - PR + 4} y={y(last.point.limits!.ucl) + 4} className="spc-chart__tag">LSC</text>
                <text x={W - PR + 4} y={y(last.point.limits!.centro) + 4} className="spc-chart__tag">LC</text>
                <text x={W - PR + 4} y={y(last.point.limits!.lcl) + 4} className="spc-chart__tag">LIC</text>
              </>
            ) : null}
          </>
        ) : null}
        <path d={line} className="spc-chart__line" />
        {dataPoints.map(({ point, index }) => {
          const cx = x(index);
          const cy = y(point.value!);
          const outside = point.signals.some((signal) => signal.regra === "fora_dos_limites");
          const run = !outside && point.signals.length > 0;
          return (
            <g key={point.key}>
              {outside ? <circle cx={cx} cy={cy} r={5.5} className="spc-chart__dot spc-chart__dot--outside" />
                : run ? <rect x={cx - 4.5} y={cy - 4.5} width={9} height={9} transform={`rotate(45 ${cx} ${cy})`} className="spc-chart__dot spc-chart__dot--run" />
                  : <circle cx={cx} cy={cy} r={3} className="spc-chart__dot" />}
              <title>{point.tip}{unit ? ` ${unit}` : ""}</title>
            </g>
          );
        })}
        {points.map((point, index) => (index % labelEvery === 0 ? (
          <text key={point.key} x={x(index)} y={H - 8} textAnchor="middle" className="spc-chart__axis">{point.label}</text>
        ) : null))}
      </svg>
    </figure>
  );
}
