import { useEffect, useRef } from "react";
import type { MetricValue } from "../types/api";
import type { AndonResource } from "../types/andon";
import { availabilityLabel, formatDateTime, formatDuration } from "../utils/format";

function metricText(metric: MetricValue) {
  if (metric.value === null || metric.value === undefined) return "Não disponível";
  return `${metric.value.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}${metric.unit ?? "%"}`;
}

function quantityText(value: number | null | undefined) {
  return value === null || value === undefined ? "Não disponível" : value.toLocaleString("pt-BR");
}

function DetailMetric({ label, metric, featured = false }: { label: string; metric: MetricValue; featured?: boolean }) {
  return (
    <div className={`andon-detail__metric ${featured ? "andon-detail__metric--featured" : ""}`} data-availability={metric.availability}>
      <span>{label}</span>
      <strong>{metricText(metric)}</strong>
      <small>{availabilityLabel[metric.availability]}</small>
      {metric.reason ? <p>{metric.reason}</p> : null}
    </div>
  );
}

export function AndonResourceDrawer({
  resource,
  elapsed,
  simulationOnly,
  onClose,
}: {
  resource: AndonResource | null;
  elapsed: number;
  simulationOnly: boolean;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!resource) return undefined;
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, resource]);

  if (!resource) return null;
  const operation = resource.operation;
  const duration = resource.state.duration_seconds;
  const liveDuration = duration === null || duration === undefined ? null : duration + elapsed;
  const stateLabel = resource.state.category === "parada"
    ? resource.state.display_label ?? resource.state.reason ?? "Motivo não informado"
    : resource.state.display_label ?? resource.state.label;
  const hasOperation = Boolean(operation?.op || operation?.product || operation?.product_description);
  const titleId = `andon-detail-${resource.sector}-${resource.code}`.replace(/[^a-zA-Z0-9_-]/g, "-");

  return (
    <div className="insight-drawer-backdrop andon-detail-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside className="insight-drawer andon-detail-drawer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <div>
            <small>Detalhes do recurso • {resource.sector}</small>
            <h2 id={titleId}>Indicadores de {resource.name}</h2>
          </div>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Fechar indicadores">×</button>
        </header>

        <div className="insight-drawer__body">
          {simulationOnly ? (
            <div className="andon-detail__simulation" role="note">
              Dados fictícios de pré-visualização. Estes valores não são persistidos como dados produtivos.
            </div>
          ) : null}

          <section className="andon-detail__state" data-state={resource.state.category}>
            <div>
              <span>Estado atual</span>
              <strong><i aria-hidden="true" />{stateLabel}</strong>
            </div>
            <div>
              <span>Tempo no estado</span>
              <strong>{liveDuration === null ? "Não disponível" : formatDuration(liveDuration)}</strong>
            </div>
            <div>
              <span>Início</span>
              <strong>{formatDateTime(resource.state.started_at)}</strong>
            </div>
            {resource.state.category !== "parada" && resource.state.reason ? <p><strong>Informação:</strong> {resource.state.reason}</p> : null}
          </section>

          <section>
            <h3>OEE e componentes</h3>
            <div className="andon-detail__metrics">
              <DetailMetric label="OEE" metric={resource.metrics.oee} featured />
              <DetailMetric label="Disponibilidade" metric={resource.metrics.availability} />
              <DetailMetric label="Performance" metric={resource.metrics.performance} />
              <DetailMetric label="FTT" metric={resource.metrics.ftt} />
            </div>
          </section>

          {hasOperation ? <section>
            <h3>Ordem e produção</h3>
            <dl className="andon-detail__operation">
              {operation?.op ? <div><dt>OP</dt><dd>{operation.op}</dd></div> : null}
              {operation?.operation !== null && operation?.operation !== undefined ? <div><dt>Operação</dt><dd>{operation.operation}</dd></div> : null}
              {operation?.product || operation?.product_description ? <div><dt>Produto</dt><dd>{operation.product_description ?? operation.product}</dd></div> : null}
              <div><dt>Operador</dt><dd>{operation?.operator ?? "Não disponível"}</dd></div>
              <div><dt>Quantidade boa</dt><dd>{quantityText(operation?.good_quantity)}</dd></div>
              <div><dt>Quantidade prevista</dt><dd>{quantityText(operation?.planned_quantity)}</dd></div>
              <div><dt>Refugo</dt><dd>{quantityText(operation?.scrap_quantity)}</dd></div>
              <div><dt>Retrabalho</dt><dd>{quantityText(operation?.rework_quantity)}</dd></div>
              <div><dt>OPs ativas no recurso</dt><dd>{resource.active_operations.toLocaleString("pt-BR")}</dd></div>
            </dl>
          </section> : null}
        </div>
      </aside>
    </div>
  );
}
