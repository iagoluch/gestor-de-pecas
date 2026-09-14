import type { Availability } from "../types/api";
import { systemStateSentence } from "../utils/systemState";

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
}: MetricCardProps) {
  // `data-availability` continua sendo o estado técnico (é gancho de estilo).
  // O texto que o usuário lê vem da camada central de humanização.
  const stateHint = availability === "disponivel" ? undefined : systemStateSentence(availability);
  const content = (
    <>
      <div className="metric-card__topline">
        <span>{label}</span>
        {delta ? <small>{delta}</small> : actionLabel ? <small className="metric-card__action">{actionLabel}</small> : null}
      </div>
      <strong className="metric-card__value">{value}</strong>
      {detail ? <span className="metric-card__detail">{detail}</span> : null}
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
