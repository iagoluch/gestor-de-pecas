import { useRef } from "react";
import { Link } from "react-router-dom";
import type { InsightEvidence, KpiExplanation, ManagementException } from "../types/api";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { availabilityLabel, formatDateTime, formatHours, formatNumber, humanize } from "../utils/format";

function text(value: unknown, fallback = "Não disponível") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function impact(value: unknown, unit: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return "Não disponível";
  if (unit === "s") return formatHours(numeric);
  if (unit === "%" || unit === "p.p.") return `${formatNumber(numeric, 1)} ${unit}`;
  return `${formatNumber(numeric, 1)}${unit ? ` ${unit}` : ""}`;
}

function EvidenceList({ evidence }: { evidence: InsightEvidence[] }) {
  if (!evidence.length) return <p className="insight-drawer__empty">Nenhuma ocorrência operacional disponível neste filtro.</p>;
  return (
    <ul className="insight-evidence-list">
      {evidence.slice(0, 20).map((item, index) => (
        <li key={`${item.source}-${item.source_id ?? index}`}>
          <div>
            <strong>{humanize(item.kind)}</strong>
            <span>{text(item.resource)}{item.op ? ` • OP ${item.op}` : ""}{item.operation ? ` / ${item.operation}` : ""}</span>
            <small>
              {item.reason ? `${item.reason} • ` : ""}
              {item.occurred_at ? formatDateTime(item.occurred_at) : item.start ? formatDateTime(item.start) : "Horário não disponível"}
            </small>
          </div>
          <div className="insight-evidence-list__origin">
            {item.op ? <Link to={`/rastreabilidade/linha-do-tempo?op=${encodeURIComponent(item.op)}`}>Rastrear OP</Link> : null}
          </div>
        </li>
      ))}
    </ul>
  );
}

function KpiBody({ explanation }: { explanation: KpiExplanation }) {
  const metric = explanation.metric;
  const metricValue = metric.value === null
    ? availabilityLabel[metric.availability]
    : `${formatNumber(metric.value, 1)}${metric.unit ?? ""}`;
  return (
    <>
      <div className="insight-drawer__summary">
        <div><span>Resultado no filtro</span><strong>{metricValue}</strong></div>
        <div><span>Disponibilidade do dado</span><strong>{availabilityLabel[metric.availability]}</strong></div>
        <p>{explanation.limitation ?? metric.reason ?? "Sem limitação adicional registrada."}</p>
      </div>

      <section>
        <h3>Componentes do resultado</h3>
        <div className="insight-component-grid">
          {explanation.components.map((component, index) => (
            <div key={text(component.key, String(index))}>
              <span>{text(component.label ?? component.key)}</span>
              <strong>{impact(component.value, component.unit)}</strong>
              {component.availability ? <small>{humanize(text(component.availability))}</small> : null}
            </div>
          ))}
        </div>
      </section>

      {explanation.largest_impact ? (
        <section>
          <h3>Maior impacto identificável</h3>
          <div className="insight-highlight">
            <strong>{text(explanation.largest_impact.cause ?? explanation.largest_impact.label)}</strong>
            <span>{impact(explanation.largest_impact.impact_value ?? explanation.largest_impact.value, explanation.largest_impact.impact_unit ?? explanation.largest_impact.unit)}</span>
            {explanation.largest_impact.meaning ? <small>{text(explanation.largest_impact.meaning)}</small> : null}
          </div>
        </section>
      ) : null}

      {explanation.causes.length ? (
        <section>
          <h3>Causas e desvios</h3>
          <ol className="insight-ranking">
            {explanation.causes.slice(0, 8).map((cause, index) => (
              <li key={`${text(cause.cause)}-${index}`}>
                <span>{text(cause.cause)}</span>
                <strong>{impact(cause.impact_value, cause.impact_unit)}</strong>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {explanation.resources.length ? (
        <section>
          <h3>Recursos com maior impacto</h3>
          <ol className="insight-ranking">
            {explanation.resources.slice(0, 8).map((resource, index) => (
              <li key={`${text(resource.resource)}-${index}`}>
                <span>{text(resource.resource)}</span>
                <strong>{impact(resource.impact_value, resource.impact_unit)}</strong>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <section>
        <h3>Ocorrências relacionadas</h3>
        <EvidenceList evidence={explanation.evidence} />
      </section>
    </>
  );
}

function ExceptionBody({ exception }: { exception: ManagementException }) {
  return (
    <>
      <div className="insight-drawer__summary">
        <div><span>Prioridade</span><strong>{humanize(exception.severity)}</strong></div>
        <div><span>Impacto</span><strong>{impact(exception.impact_value, exception.impact_unit)}</strong></div>
        <p>{exception.summary}</p>
      </div>
      <section>
        <h3>Por que requer atenção</h3>
        <p className="insight-drawer__text">{exception.justification}</p>
      </section>
      <section>
        <h3>Contexto</h3>
        <dl className="insight-context-grid">
          <div><dt>Setor</dt><dd>{text(exception.sector)}</dd></div>
          <div><dt>Recurso</dt><dd>{text(exception.resource)}</dd></div>
          <div><dt>OP</dt><dd>{text(exception.op)}</dd></div>
          <div><dt>Operação</dt><dd>{text(exception.operation)}</dd></div>
          <div><dt>Causa</dt><dd>{text(exception.cause)}</dd></div>
          <div><dt>Desvio</dt><dd>{impact(exception.deviation, exception.unit)}</dd></div>
        </dl>
      </section>
      <section>
        <h3>Ocorrências relacionadas</h3>
        <EvidenceList evidence={exception.evidence} />
      </section>
    </>
  );
}

export function ManagementInsightDrawer({
  explanation,
  exception,
  onClose,
}: {
  explanation?: KpiExplanation | null;
  exception?: ManagementException | null;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const open = Boolean(explanation || exception);
  useDialogFocus(open, dialogRef, onClose, closeRef);
  if (!open) return null;
  const title = explanation ? `Entenda o ${explanation.label}` : exception?.title ?? "Detalhes da exceção";
  return (
    <div className="insight-drawer-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside ref={dialogRef} className="insight-drawer" role="dialog" aria-modal="true" aria-labelledby="insight-drawer-title">
        <header>
          <div>
            <small>{explanation ? "KPI explicável" : "Exceção gerencial"}</small>
            <h2 id="insight-drawer-title">{title}</h2>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Fechar explicação">×</button>
        </header>
        <div className="insight-drawer__body">
          {explanation ? <KpiBody explanation={explanation} /> : exception ? <ExceptionBody exception={exception} /> : null}
        </div>
      </aside>
    </div>
  );
}
