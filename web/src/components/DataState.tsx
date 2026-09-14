import type { ReactNode } from "react";
import type { ApiError } from "../api/client";
import { systemStateLabelOrNull, systemStateSentence } from "../utils/systemState";

export function LoadingState({ label = "Carregando dados…" }: { label?: string }) {
  return (
    <div className="state-box" role="status" aria-live="polite">
      <span className="loading-dot" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="state-box state-box--error" role="alert">
      <strong>Não foi possível carregar os dados</strong>
      <span>{error.message}</span>
      {error.requestId ? <small>Referência: {error.requestId}</small> : null}
      {onRetry ? <button type="button" onClick={onRetry}>Tentar novamente</button> : null}
    </div>
  );
}

/**
 * Estado vazio humano. Quando a superfície conhece o estado técnico do backend
 * (`state`), título e detalhe vêm da camada central de humanização: a tela não
 * mostra o identificador nem inventa zero, `N/A`, `null` ou nome de enum.
 */
export function EmptyState({ title, detail, state }: { title?: string; detail?: ReactNode; state?: string | null }) {
  // Sem título e sem detalhe, o estado vazio assume o significado mais comum
  // ("nenhum registro no período") e continua explicando em linguagem humana,
  // em vez de mostrar só um rótulo seco.
  const effectiveState = state ?? (title || detail ? null : "sem_registros");
  const resolved = effectiveState ? systemStateLabelOrNull(effectiveState) : null;
  const body = detail ?? (effectiveState ? systemStateSentence(effectiveState) : null);
  return (
    <div className="state-box state-box--empty">
      <strong>{title ?? resolved ?? "Sem registros"}</strong>
      {body ? <span>{body}</span> : null}
    </div>
  );
}

