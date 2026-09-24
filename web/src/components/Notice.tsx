import type { PropsWithChildren } from "react";

export type NoticeTone = "info" | "success" | "error" | "stale";

/**
 * Aviso de resultado de ação ou de estado da tela — o único canal de
 * feedback em linha. Erro interrompe o leitor de tela (alert); o resto é
 * anunciado sem interromper (status). Carregamento de dados é do DataState;
 * carregamento de ação é do AsyncButton.
 */
export function Notice({ tone = "info", className, children }: PropsWithChildren<{ tone?: NoticeTone; className?: string }>) {
  const classes = ["operator-notice", tone === "info" ? "" : `operator-notice--${tone}`, className ?? ""].filter(Boolean).join(" ");
  return <p className={classes} role={tone === "error" ? "alert" : "status"}>{children}</p>;
}
