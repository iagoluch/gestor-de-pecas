import { useId, useRef, type PropsWithChildren, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../hooks/useDialogFocus";

export function OperatorDialog({
  title,
  context,
  children,
  onCancel,
  size = "standard",
  kicker,
  tone,
}: PropsWithChildren<{ title: string; context?: ReactNode; onCancel: () => void; size?: "compact" | "standard" | "wide"; kicker?: string; tone?: "setup" | "stop" }>) {
  const sectionRef = useRef<HTMLElement>(null);
  const titleId = useId();
  useDialogFocus(sectionRef, true, onCancel);

  // Portal no body: o diálogo aberto por último fica por cima (ex.: "Descartar alterações?"
  // sobre "Editar pausa"), já que todos os backdrops dividem o mesmo z-index.
  return createPortal(
    <div className="operator-dialog-backdrop" role="presentation">
      <section ref={sectionRef} tabIndex={-1} className={`operator-dialog operator-dialog--${size}${tone ? ` operator-dialog--${tone}` : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <div className="operator-dialog__heading">{kicker ? <small>{kicker}</small> : null}<h2 id={titleId}>{title}</h2></div>
          <button type="button" aria-label="Fechar" onClick={onCancel}>×</button>
        </header>
        {context ? <div className="operator-dialog__context">{context}</div> : null}
        <div className="operator-dialog__body">{children}</div>
      </section>
    </div>,
    document.body,
  );
}
