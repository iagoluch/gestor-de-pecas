/**
 * Ícones das ações do operador: vetor com a cor do próprio botão
 * (currentColor), no lugar dos PNGs com fundo opaco colado.
 */
import type { ReactNode } from "react";

export type OperatorAction = "start" | "stop" | "finish" | "setup" | "rework";

const PATHS: Record<OperatorAction, ReactNode> = {
  start: <path d="M8 5.14v13.72a1 1 0 0 0 1.52.85l10.9-6.86a1 1 0 0 0 0-1.7L9.52 4.29A1 1 0 0 0 8 5.14z" fill="currentColor" />,
  stop: <><circle cx="12" cy="12" r="9.5" /><path d="M9.5 8.5v7M14.5 8.5v7" /></>,
  finish: <><circle cx="12" cy="12" r="9.5" /><path d="m7.8 12.3 2.9 2.9 5.5-6" /></>,
  setup: <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />,
  rework: <><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></>,
};

export function OperatorActionIcon({ name }: { name: OperatorAction }) {
  return (
    <svg className="operator-action__icon" data-icon={name} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.25} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}
