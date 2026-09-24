import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Comportamento de teclado de um diálogo modal: foco inicial dentro dele,
 * Tab/Shift+Tab presos no conteúdo, Esc fecha e, ao fechar, o foco volta ao
 * elemento que abriu o diálogo.
 *
 * O efeito depende só de `active`: a troca de identidade de `onClose` ou uma
 * nova renderização com dados atualizados não rouba o foco do usuário.
 */
export function useDialogFocus(containerRef: RefObject<HTMLElement | null>, active: boolean, onClose: () => void) {
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  // Quem abriu o diálogo é lido durante a renderização, antes do commit: no
  // efeito já é tarde, porque um `autoFocus` de dentro do diálogo roubou o
  // foco e o retorno iria para o próprio campo desmontado (AX-02).
  const openerRef = useRef<HTMLElement | null>(null);
  if (!active) openerRef.current = null;
  else if (openerRef.current === null) openerRef.current = document.activeElement as HTMLElement | null;

  useEffect(() => {
    if (!active) return undefined;
    const container = containerRef.current;
    const previouslyFocused = openerRef.current;
    // Um campo com autoFocus dentro do diálogo continua com o foco; só sem ele
    // o foco vai para o primeiro controle.
    if (!container?.contains(document.activeElement)) {
      const focusables = container?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
      (focusables?.[0] ?? container)?.focus();
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !container) return;
      const nodes = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (nodes.length === 0) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      previouslyFocused?.focus?.();
    };
  }, [active, containerRef]);
}
