import { useEffect } from "react";

const APP_TITLE = "Gestor de Peças";

/** IA-01: a aba do navegador leva o mesmo nome do h1 da tela. */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · ${APP_TITLE}`;
    return () => { document.title = APP_TITLE; };
  }, [title]);
}
