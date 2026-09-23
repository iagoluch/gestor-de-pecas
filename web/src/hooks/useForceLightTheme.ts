import { useEffect } from "react";

/**
 * Telas de TV (Andon, Solda) são pensadas para leitura à distância no chão de
 * fábrica com cores fixas e saturadas — ficam de fora do tema escuro por
 * decisão de design (ver comentário em styles/tokens.css). Nada garantia
 * isso antes: o tema do sistema operacional ou o botão de tema na barra
 * lateral escureciam essas telas mesmo assim, tornando texto e cores
 * ilegíveis. Este hook aplica `data-theme="light"` apenas enquanto a tela de
 * TV está montada, sem alterar a preferência salva do usuário.
 */
export function useForceLightTheme() {
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.dataset.theme;
    root.dataset.theme = "light";
    return () => {
      if (previous === undefined) delete root.dataset.theme;
      else root.dataset.theme = previous;
    };
  }, []);
}
