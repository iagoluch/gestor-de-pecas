import { useLayoutEffect, useRef, type RefObject } from "react";

/**
 * Anima a troca de posição dos blocos da grade (técnica FLIP): mede antes,
 * mede depois e desloca o nó com `transform` para ele "deslizar" até o lugar
 * novo. Só roda quando `signature` muda; o bloco que está sendo arrastado
 * (`skipKey`) não é animado, porque quem segue o mouse é a prévia nativa.
 */
export function useGridFlip(
  containerRef: RefObject<HTMLElement | null>,
  signature: string,
  skipKey?: string | null,
) {
  const previous = useRef<Map<string, DOMRect>>(new Map());

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const nodes = Array.from(container.querySelectorAll<HTMLElement>("[data-card-key]"));
    const next = new Map<string, DOMRect>();
    for (const node of nodes) next.set(node.dataset.cardKey ?? "", node.getBoundingClientRect());

    for (const node of nodes) {
      const key = node.dataset.cardKey ?? "";
      if (skipKey && key === skipKey) continue;
      const before = previous.current.get(key);
      const after = next.get(key);
      if (!before || !after) continue;
      const dx = before.left - after.left;
      const dy = before.top - after.top;
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue;
      node.style.transition = "none";
      node.style.transform = `translate(${dx}px, ${dy}px)`;
      requestAnimationFrame(() => {
        node.style.transition = "transform 220ms cubic-bezier(.2, .8, .2, 1)";
        node.style.transform = "";
      });
    }
    previous.current = next;
  }, [containerRef, signature, skipKey]);
}
