import type { PropsWithChildren, ReactNode } from "react";

export function OperatorDialog({
  title,
  context,
  children,
  onCancel,
  size = "standard",
}: PropsWithChildren<{ title: string; context?: ReactNode; onCancel: () => void; size?: "compact" | "standard" | "wide" }>) {
  return (
    <div className="operator-dialog-backdrop" role="presentation">
      <section className={`operator-dialog operator-dialog--${size}`} role="dialog" aria-modal="true" aria-labelledby="operator-dialog-title">
        <header>
          <h2 id="operator-dialog-title">{title}</h2>
          <button type="button" aria-label="Fechar" onClick={onCancel}>×</button>
        </header>
        {context ? <div className="operator-dialog__context">{context}</div> : null}
        <div className="operator-dialog__body">{children}</div>
      </section>
    </div>
  );
}
