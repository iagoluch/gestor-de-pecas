import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { directorPaths } from "../../api/client";
import { LoadingState } from "../../components/DataState";
import { ExplanationDrawer } from "../../components/ExplanationDrawer";
import { ValueExplanationBody } from "../../components/ValueExplanationPanel";
import { useApiQuery } from "../../hooks/useApiQuery";
import { isValueExplanation, type ExplanationResponse } from "../../types/valueExplanation";
import type { DirectorPeriodName } from "../../types/director";

export interface DirectorExplainTarget {
  metric: string;
  periodo: DirectorPeriodName;
  setor?: string;
  recurso?: string;
  pessoa?: string;
  motivo?: string;
}

function DirectorExplanationPanel({ target, onClose }: { target: DirectorExplainTarget; onClose: () => void }) {
  const { metric, periodo, setor, recurso, pessoa, motivo } = target;
  // A conta é um retrato do momento em que foi aberta: não refaz sozinha a cada atualização ao vivo.
  const query = useApiQuery<ExplanationResponse>(directorPaths.explain(metric, periodo, { setor, recurso, pessoa, motivo }), { ignoreLiveTick: true });
  const response = query.data;
  return (
    <ExplanationDrawer title={response?.label ?? "Explicação"} onClose={onClose} testId="director-explanation-panel">
      {query.loading ? <LoadingState label="Carregando explicação…" /> : null}
      {!query.loading && query.error && !response ? (
        <div className="state-box state-box--error" role="alert">
          <strong>
            {query.error.status === 403 ? "Você não tem acesso a esta explicação." : "Não foi possível carregar a explicação agora."}
          </strong>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}
      {response && isValueExplanation(response) ? <ValueExplanationBody explanation={response} /> : null}
    </ExplanationDrawer>
  );
}

/**
 * Número da Diretoria que abre "de onde vem": valores em R$ só saem da rota `/diretoria/explicacao`
 * (mesma porta de acesso da aba), nunca da rota de gestão.
 */
export function DirectorExplainable({ children, context, target, className }: {
  children: ReactNode;
  /** Frase curta para o leitor de tela: "Custo das paradas R$ 2.460,00". */
  context: string;
  target: DirectorExplainTarget;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className={`metric-link explainable-value${className ? ` ${className}` : ""}`}
        aria-label={`Ver de onde vem este número: ${context}`}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      {open ? createPortal(<DirectorExplanationPanel target={target} onClose={() => setOpen(false)} />, document.body) : null}
    </>
  );
}
