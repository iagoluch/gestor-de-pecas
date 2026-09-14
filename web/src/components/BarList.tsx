import { formatNumber } from "../utils/format";

export interface BarDatum {
  label: string;
  value: number;
  detail?: string;
}

export function BarList({ data, unit = "" }: { data: BarDatum[]; unit?: string }) {
  const maximum = Math.max(...data.map((item) => item.value), 0);
  return (
    <div className="bar-list">
      {data.map((item) => (
        <div className="bar-list__row" key={item.label}>
          <span title={item.label}>{item.label}</span>
          <div><i style={{ width: maximum > 0 ? `${item.value / maximum * 100}%` : "0%" }} /></div>
          <strong>{item.detail ?? `${formatNumber(item.value, 1)}${unit}`}</strong>
        </div>
      ))}
    </div>
  );
}

