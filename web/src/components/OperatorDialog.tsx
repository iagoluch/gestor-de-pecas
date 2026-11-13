import { useId, useRef, type KeyboardEvent, type PropsWithChildren, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDialogFocus } from "../hooks/useDialogFocus";

// Onde o Enter já tem papel próprio e não deve confirmar o diálogo.
const ENTER_OWNERS = "textarea, select, a[href], [contenteditable='true'], [role='combobox']";

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
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useDialogFocus(sectionRef, true, onCancel);

  // Enter confirma: aciona o botão principal da última barra de ações. Campos
  // que já tratam o Enter (crachá, leitor) chamam preventDefault e ficam de
  // fora; botão com data-enter="off" (apagar, desativar) exige clique.
  const confirmOnEnter = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Enter" || event.defaultPrevented || event.repeat || event.shiftKey || event.ctrlKey || event.altKey || event.metaKey || event.nativeEvent.isComposing) return;
    const section = sectionRef.current;
    const target = event.target as HTMLElement;
    if (!section || !section.contains(target)) return; // diálogo empilhado responde por si
    if (target.closest(ENTER_OWNERS)) return;
    // Botão focado: o Enter clica nele, exceto o × e uma opção já escolhida
    // (motivo, operação): aí o Enter segue para a confirmação.
    const chosen = ["aria-selected", "aria-pressed", "aria-checked"].some((name) => target.getAttribute(name) === "true");
    if (target instanceof HTMLButtonElement && target !== closeRef.current && !chosen) return;
    if (target instanceof HTMLInputElement && target.form) return; // formulário já envia sozinho
    const bars = section.querySelectorAll(".operator-dialog__actions");
    const buttons = bars[bars.length - 1]?.querySelectorAll<HTMLButtonElement>("button");
    const primary = buttons?.[buttons.length - 1];
    if (!primary) return;
    // Travado ou de risco: o Enter não faz nada (nem cai no Cancelar/×).
    event.preventDefault();
    if (!primary.disabled && primary.dataset.enter !== "off") primary.click();
  };

  // Portal no body: o diálogo aberto por último fica por cima (ex.: "Descartar alterações?"
  // sobre "Editar pausa"), já que todos os backdrops dividem o mesmo z-index.
  return createPortal(
    <div className="operator-dialog-backdrop" role="presentation">
      <section ref={sectionRef} tabIndex={-1} onKeyDown={confirmOnEnter} className={`operator-dialog operator-dialog--${size}${tone ? ` operator-dialog--${tone}` : ""}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <div className="operator-dialog__heading">{kicker ? <small>{kicker}</small> : null}<h2 id={titleId}>{title}</h2></div>
          <button ref={closeRef} type="button" aria-label="Fechar" onClick={onCancel}>×</button>
        </header>
        {context ? <div className="operator-dialog__context">{context}</div> : null}
        <div className="operator-dialog__body">{children}</div>
      </section>
    </div>,
    document.body,
  );
}
