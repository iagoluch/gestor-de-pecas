import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { OverviewFilters } from "../types/explanation";
import type { ValueExplanation } from "../types/valueExplanation";
import { MetricExplanationPanel } from "./MetricExplanationPanel";
import { LocalExplanationPanel } from "./ValueExplanationPanel";
import "../styles/metric-explanation.css";

type ExplainableValueProps = {
  children: ReactNode;
  /** Qual número é este (ex.: "Refugo, 12"): vira o complemento do aria-label. */
  context?: string;
} & (
  | { metric: string; filters: OverviewFilters; local?: undefined }
  | { local: ValueExplanation; metric?: undefined; filters?: undefined }
);

/**
 * Número clicável discreto que abre o painel "de onde vem este número".
 * Com `metric` + `filters` o painel busca a explicação no servidor; com `local`
 * mostra uma explicação já montada no navegador (soma das linhas da tela).
 * O painel vai para o `body`, para não herdar transformações/recortes do cartão.
 */
export function ExplainableValue(props: ExplainableValueProps) {
  const { children, context } = props;
  const ariaLabel = context ? `Ver de onde vem este número: ${context}` : "Ver de onde vem este número";
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  const panel = open
    ? props.local
      ? <LocalExplanationPanel explanation={props.local} onClose={close} />
      : <MetricExplanationPanel metric={props.metric} filters={props.filters} onClose={close} />
    : null;
  return (
    <>
      <button type="button" className="metric-link explainable-value" aria-label={ariaLabel} aria-haspopup="dialog" onClick={() => setOpen(true)}>
        {children}
      </button>
      {panel ? createPortal(panel, document.body) : null}
    </>
  );
}
