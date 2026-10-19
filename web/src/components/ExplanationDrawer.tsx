import { useId, useRef, type ReactNode } from "react";
import { useDialogFocus } from "../hooks/useDialogFocus";
import "../styles/metric-explanation.css";

/** Hora do cálculo (HH:MM). O backend manda horário local sem fuso; com fuso, converte. */
export function clockTime(iso: string) {
  const naive = /T(\d{2}):(\d{2})/.exec(iso);
  if (naive && !/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) return `${naive[1]}:${naive[2]}`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return naive ? `${naive[1]}:${naive[2]}` : iso;
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

export function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * Casca do painel lateral "de onde vem este número" (fundo, cabeçalho, foco,
 * fechar). Compartilhada pelo painel de servidor e pelo local, para os dois
 * abrirem e fecharem igual.
 */
export function ExplanationDrawer({ title, onClose, children, footer, testId = "metric-explanation-panel" }: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  testId?: string;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const titleId = useId();
  useDialogFocus(panelRef, true, onClose);
  return (
    <div
      className="insight-drawer-backdrop"
      role="presentation"
      data-testid={testId}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside ref={panelRef} className="insight-drawer metric-explanation" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <div>
            <small>De onde vem este número</small>
            <h2 id={titleId}>{title}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar explicação">×</button>
        </header>
        <div className="insight-drawer__body metric-explanation__body">{children}</div>
        {footer}
      </aside>
    </div>
  );
}
