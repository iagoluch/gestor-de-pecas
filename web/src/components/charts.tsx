import { useId } from "react";

/** Gráficos SVG do visual do protótipo. Só desenham o que recebem — nenhum cálculo de métrica aqui. */

export function Sparkline({ values, color = "var(--primary)" }: { values: Array<number | null>; color?: string }) {
  const points = values.map((value, index) => ({ value, index })).filter((item): item is { value: number; index: number } => item.value !== null);
  if (points.length < 2) return null;
  const w = 200;
  const h = 54;
  const max = Math.max(...points.map((item) => item.value));
  const min = Math.min(...points.map((item) => item.value));
  const step = w / Math.max(values.length - 1, 1);
  const path = points
    .map((item, position) => `${position ? "L" : "M"}${(item.index * step).toFixed(1)} ${(h - 6 - ((item.value - min) / (max - min || 1)) * (h - 14)).toFixed(1)}`)
    .join("");
  const first = points[0].index * step;
  const last = points[points.length - 1].index * step;
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={`${path}L${last.toFixed(1)} ${h}L${first.toFixed(1)} ${h}Z`} fill={color} opacity=".13" />
      <path d={path} pathLength={1} className="chart-line" stroke={color} style={{ strokeWidth: 2.4 }} />
    </svg>
  );
}

export interface LineSeries {
  name: string;
  color: string;
  values: Array<number | null>;
  dashed?: boolean;
}

export function LineChart({ series, labels, height = 230, unit = "" }: { series: LineSeries[]; labels: string[]; height?: number; unit?: string }) {
  const w = 720;
  const pl = 36;
  const pb = 26;
  const pt = 10;
  const all = series.flatMap((item) => item.values.filter((value): value is number => value !== null));
  if (all.length === 0) return null;
  const max = Math.max(...all, 1) * 1.08;
  const min = Math.min(0, ...all);
  const count = labels.length;
  const stepX = (w - pl) / Math.max(count - 1, 1);
  const y = (value: number) => pt + (height - pt - pb) * (1 - (value - min) / (max - min || 1));
  const every = Math.ceil(count / 8);
  return (
    <svg className="chart" viewBox={`0 0 ${w} ${height}`} role="img" aria-label={series.map((item) => item.name).join(" e ")}>
      {[0, 1, 2, 3, 4].map((i) => {
        const gy = pt + ((height - pt - pb) * i) / 4;
        return (
          <g key={i}>
            <line className="chart-grid" x1={pl} x2={w} y1={gy} y2={gy} />
            <text x={0} y={gy + 4}>{Math.round(max - ((max - min) * i) / 4)}</text>
          </g>
        );
      })}
      {labels.map((label, i) => (i % every === 0 ? <text key={i} x={pl + i * stepX} y={height - 4} textAnchor="middle">{label}</text> : null))}
      {series.map((item) => {
        const points = item.values.map((value, i) => (value === null ? null : ([pl + i * stepX, y(value), value] as const))).filter((p): p is readonly [number, number, number] => p !== null);
        if (points.length === 0) return null;
        const d = points.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join("");
        return (
          <g key={item.name}>
            <path className="chart-area" d={`${d}L${points[points.length - 1][0].toFixed(1)} ${height - pb}L${points[0][0].toFixed(1)} ${height - pb}Z`} fill={item.color} />
            <path className={`chart-line ${item.dashed ? "chart-line--dashed" : ""}`} pathLength={1} d={d} stroke={item.color} />
            {points.map((p, i) => (i % 2 === 0 || points.length < 10 ? (
              <circle key={i} cx={p[0]} cy={p[1]} r={3.6} fill="var(--surface)" stroke={item.color} strokeWidth={2.2}>
                <title>{`${item.name}: ${p[2].toLocaleString("pt-BR")}${unit}`}</title>
              </circle>
            ) : null))}
          </g>
        );
      })}
    </svg>
  );
}

export interface StackPart {
  name: string;
  value: number;
  color: string;
  text: string;
  /** Complemento discreto abaixo do valor (ex.: "média 0,4 h"). */
  hint?: string;
  /** Aparece na legenda, mas fica fora da barra e do total (ex.: calendário, parada planejada). */
  outside?: boolean;
}

/** Barra empilhada + legenda. `text` já vem formatado (ex.: "12,4 h"); cada linha mostra também a participação em %. */
export function StackBar({ parts }: { parts: StackPart[] }) {
  const total = parts.reduce((sum, part) => sum + (part.outside ? 0 : part.value), 0);
  const id = useId();
  if (total <= 0) return null;
  return (
    <>
      <div className="stack" role="img" aria-labelledby={id}>
        {parts.filter((part) => part.value > 0 && !part.outside).map((part) => (
          <i key={part.name} style={{ "--w": `${(part.value / total) * 100}%`, "--c": part.color } as React.CSSProperties} title={part.name} />
        ))}
      </div>
      <div className="legend" id={id}>
        {parts.map((part) => (
          <span key={part.name} className={part.value > 0 ? undefined : "legend__zero"}>
            <i style={{ "--c": part.color } as React.CSSProperties} />
            <em>{part.name}</em>
            <small>{part.value > 0 && !part.outside ? `${((part.value / total) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}%` : "—"}</small>
            <b>{part.text}</b>
            {part.hint ? <small className="legend__hint">{part.hint}</small> : null}
          </span>
        ))}
      </div>
    </>
  );
}
