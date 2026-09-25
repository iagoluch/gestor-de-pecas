import { useEffect, useId, useRef } from "react";

export interface RowAction {
  label: string;
  onClick: () => void;
  /** Ações destrutivas vão para o fim do menu, separadas das seguras. */
  danger?: boolean;
  disabled?: boolean;
  title?: string;
}

/** Ação primária visível + demais ações num menu "⋯" (popover nativo: fecha ao clicar fora e com Escape). */
export function RowActions({ primary, actions, disabled, label }: { primary: RowAction; actions: RowAction[]; disabled?: boolean; label: string }) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const safe = actions.filter((action) => !action.danger);
  const danger = actions.filter((action) => action.danger);

  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const onToggle = (event: Event) => {
      if ((event as ToggleEvent).newState !== "open" || !triggerRef.current) return;
      const anchor = triggerRef.current.getBoundingClientRect();
      const left = Math.max(8, Math.min(anchor.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 8));
      const below = anchor.bottom + 4;
      const top = below + menu.offsetHeight > window.innerHeight - 8 ? Math.max(8, anchor.top - menu.offsetHeight - 4) : below;
      menu.style.left = `${left}px`;
      menu.style.top = `${top}px`;
      menu.querySelector<HTMLButtonElement>("button:not(:disabled)")?.focus();
    };
    menu.addEventListener("toggle", onToggle);
    return () => menu.removeEventListener("toggle", onToggle);
  }, []);

  const item = (action: RowAction) => (
    <button
      key={action.label}
      type="button"
      role="menuitem"
      className={action.danger ? "row-actions__item row-actions__item--danger" : "row-actions__item"}
      disabled={disabled || action.disabled}
      title={action.title}
      onClick={() => {
        menuRef.current?.hidePopover?.();
        triggerRef.current?.focus();
        action.onClick();
      }}
    >
      {action.label}
    </button>
  );

  return (
    <span className="row-actions">
      <button type="button" aria-label={`${primary.label}: ${label}`} disabled={disabled || primary.disabled} title={primary.title} onClick={primary.onClick}>{primary.label}</button>
      {actions.length ? (
        <>
          <button ref={triggerRef} type="button" className="row-actions__more" popoverTarget={id} aria-haspopup="menu" aria-label={`Mais ações: ${label}`} disabled={disabled}>
            <span aria-hidden="true">⋯</span>
          </button>
          <div ref={menuRef} id={id} popover="auto" role="menu" aria-label={`Ações: ${label}`} className="row-actions__menu">
            {safe.map(item)}
            {safe.length && danger.length ? <hr className="row-actions__divider" /> : null}
            {danger.map(item)}
          </div>
        </>
      ) : null}
    </span>
  );
}
