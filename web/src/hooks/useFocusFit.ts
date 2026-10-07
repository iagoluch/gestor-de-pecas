import { useLayoutEffect } from "react";

const MIN_UNIT_PX = 1.4;
// Teto: sem ele, um setor com 1 recurso viraria um cartão do tamanho da tela.
const MAX_UNIT_VW = 0.2;  // em % da largura (0,2 vw)
const STEPS = 9;
// O cartão tem folga própria (~97% da linha); espremido pelo grid cai a ~65%.
const SQUISH_LIMIT = 0.9;

/**
 * Setor em foco na TV: escolhe a maior unidade `--u` em que os cartões ainda cabem
 * no painel. O CSS fixo deixava setores com poucos recursos num canto da tela;
 * medir é mais simples e mais robusto que prever a quebra de linhas dos grupos.
 */
export function fitFocusUnit(panel: HTMLElement): void {
  const lanes = Array.from(panel.querySelectorAll<HTMLElement>(".andon-resource-group__cards"));
  const fits = (unit: number) => {
    panel.style.setProperty("--u", `${unit}px`);
    // As linhas da pista são minmax(0, h) e encolhem para caber, e o conteúdo do
    // cartão encolhe junto (nada estoura): o sinal de falta de espaço é o cartão
    // ficar mais baixo que a altura nominal da linha.
    return lanes.every((lane) => {
      const rowHeight = parseFloat(getComputedStyle(lane).gridAutoRows.split(",")[1]);
      return Array.from(lane.children).every((card) => card.getBoundingClientRect().height >= rowHeight * SQUISH_LIMIT);
    });
  };
  let high = (window.innerWidth * MAX_UNIT_VW) / 100;
  if (fits(high)) return;
  let low = MIN_UNIT_PX;
  for (let step = 0; step < STEPS; step += 1) {
    const middle = (low + high) / 2;
    if (fits(middle)) low = middle;
    else high = middle;
  }
  panel.style.setProperty("--u", `${low}px`);
}

/** `layoutKey` muda quando o setor em foco ou a quantidade de recursos muda. */
export function useFocusFit(layoutKey: string): void {
  useLayoutEffect(() => {
    if (!layoutKey) return undefined;
    const fit = () => {
      const panel = document.querySelector<HTMLElement>(".andon-page--tv .andon-board--focus .andon-sector-panel");
      if (panel) fitFocusUnit(panel);
    };
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, [layoutKey]);
}
