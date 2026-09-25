import { useState } from "react";
import type { ConfirmOptions } from "../components/ConfirmDialog";

/**
 * Rascunho de um formulário em diálogo: `fechar` pergunta antes de descartar
 * quando o rascunho difere do que foi aberto (GE-05).
 */
export function useDraft<T>(confirm: (options: ConfirmOptions) => Promise<boolean>) {
  const [draft, setDraft] = useState<T | null>(null);
  const [original, setOriginal] = useState("");
  const abrir = (value: T) => {
    setOriginal(JSON.stringify(value));
    setDraft(value);
  };
  const fechar = async () => {
    if (draft && JSON.stringify(draft) !== original) {
      const descartar = await confirm({
        title: "Descartar alterações?",
        message: "As alterações feitas neste formulário ainda não foram salvas e serão perdidas.",
        confirmLabel: "Descartar alterações",
        cancelLabel: "Continuar editando",
        tone: "danger",
      });
      if (!descartar) return;
    }
    setDraft(null);
  };
  return [draft, setDraft, abrir, fechar] as const;
}
