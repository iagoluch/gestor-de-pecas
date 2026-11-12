import type { ReactNode } from "react";
import type { Availability } from "../types/api";
import { systemStateSentence } from "../utils/systemState";

const BACKEND_NOISE_PATTERNS = [
  /exce[çc][aã]o corporativa/i,
  /f[oó]rmula oficial/i,
  /fonte can[oô]nica/i,
  /diferen[çc]a:/i,
  /n[aã]o ser[aá] inventado/i,
  /pipeline/i,
  /contrato confirmado/i,
];

function filterBackendNoise(text: string): string {
  for (const pattern of BACKEND_NOISE_PATTERNS) {
    if (pattern.test(text)) return "";
  }
  return text;
}

interface MetricCardProps {
  label: string;
  value: string;
  detail?: string;
  accent?: "primary" | "success" | "warning" | "danger" | "teal" | "purple";
  delta?: string;
  availability?: Availability;
  onClick?: () => void;
  actionLabel?: string;
  ariaLabel?: string;
  /** Variação contra o período anterior (já formatada pelo chamador; `up` só pinta verde/vermelho). */
  trend?: { text: string; up: boolean };
  spark?: ReactNode;
  /** Substitui o texto do valor (ex.: `ExplainableValue`). Só vale em cartão sem `onClick`, para não aninhar botões. */
  valueNode?: ReactNode;
}

export function MetricCard({
  label,
  value,
  detail,
  accent = "primary",
  delta,
  availability = "disponivel",
  onClick,
  actionLabel,
  ariaLabel,
  trend,
  spark,
  valueNode,
}: MetricCardProps) {
  // `data-availability` continua sendo o estado técnico (é gancho de estilo).
  // O texto que o usuário lê vem da camada central de humanização.
  const stateHint = availability === "disponivel" ? undefined : filterBackendNoise(systemStateSentence(availability) ?? "");
  const content = (
    <>
      <div className={`metric-card__topline${delta || actionLabel ? "" : " metric-card__topline--single"}`}>
        <span>{label}</span>
        {delta ? <small>{delta}</small> : actionLabel ? <small className="metric-card__action">{actionLabel}</small> : null}
      </div>
      <strong className="metric-card__value">{onClick ? value : valueNode ?? value}</strong>
      {trend ? <span className={`metric-card__trend metric-card__trend--${trend.up ? "up" : "down"}`}>{trend.up ? "▲" : "▼"} {trend.text}</span> : null}
      {detail ? <span className="metric-card__detail">{filterBackendNoise(detail)}</span> : null}
      {spark}
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        className={`metric-card metric-card--${accent} metric-card--interactive`}
        data-availability={availability}
        title={stateHint}
        onClick={onClick}
        aria-label={ariaLabel ?? `${label}: ${value}. Ver explicação`}
      >
        {content}
      </button>
    );
  }
  return <article className={`metric-card metric-card--${accent}`} data-availability={availability} title={stateHint}>{content}</article>;
}
