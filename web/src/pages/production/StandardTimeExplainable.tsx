import { useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { LoadingState } from "../../components/DataState";
import { ExplanationDrawer } from "../../components/ExplanationDrawer";
import { ValueExplanationBody } from "../../components/ValueExplanationPanel";
import { useApiQuery } from "../../hooks/useApiQuery";
import { isValueExplanation, type ExplanationResponse } from "../../types/valueExplanation";

export interface StandardTimeExplainTarget {
  /** `std.protheus`, `std.manual`, `std.estimado`, `std.fonte` ou `std.recalculo`. */
  metric: string;
  /** Chave da linha; o `std.recalculo` explica a tela inteira e não precisa dela. */
  produto?: string;
  operacao?: string;
  recurso?: string;
}

function explainUrl({ metric, produto, operacao, recurso }: StandardTimeExplainTarget) {
  const params = new URLSearchParams({ metric });
  if (produto) params.set("produto", produto);
  if (operacao) params.set("operacao", operacao);
  if (recurso) params.set("recurso", recurso);
  return `/api/v1/management/explicacao?${params.toString()}`;
}

function StandardTimeExplanationPanel({ target, onClose }: { target: StandardTimeExplainTarget; onClose: () => void }) {
  // A conta é um retrato do momento em que foi aberta: não refaz sozinha a cada atualização ao vivo.
  const query = useApiQuery<ExplanationResponse>(explainUrl(target), { ignoreLiveTick: true });
  const response = query.data;
  return (
    <ExplanationDrawer title={response?.label ?? "Explicação"} onClose={onClose} testId="standard-time-explanation-panel">
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
 * Número da tela Tempo padrão que abre "de onde vem": a chave da linha (produto, operação, recurso)
 * vai direto na rota de explicação, sem depender dos filtros de período das Análises.
 */
export function StandardTimeExplainable({ children, context, target }: {
  children: ReactNode;
  /** Frase curta para o leitor de tela: "Tempo Protheus 12,00 s". */
  context: string;
  target: StandardTimeExplainTarget;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        className="metric-link explainable-value"
        aria-label={`Ver de onde vem este número: ${context}`}
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
      >
        {children}
      </button>
      {open ? createPortal(<StandardTimeExplanationPanel target={target} onClose={() => setOpen(false)} />, document.body) : null}
    </>
  );
}
