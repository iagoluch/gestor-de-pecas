import { useCallback, useState, type ReactNode } from "react";
import { AsyncButton } from "./AsyncButton";
import { OperatorDialog } from "./OperatorDialog";

export type ConfirmOptions = {
  title: string;
  message: ReactNode;
  /** Verbo da ação ("Desativar usuário"), nunca "OK"/"Sim". */
  confirmLabel: string;
  cancelLabel?: string;
  /** "danger" para o que desativa, remove ou reinicia. */
  tone?: "primary" | "danger";
};

/**
 * Confirmação única do app (gestão e operador). Substitui o `window.confirm`
 * nativo: mesma moldura, foco preso, Esc cancela e o foco volta ao botão que
 * abriu. Com `onConfirm` assíncrono o diálogo fica aberto e travado até a
 * resposta, sem duplo envio.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel = "Cancelar",
  tone = "primary",
  onConfirm,
  onCancel,
}: ConfirmOptions & { onConfirm: () => unknown; onCancel: () => void }) {
  return (
    <OperatorDialog title={title} size="compact" onCancel={onCancel}>
      <div className="confirm-dialog__message">{message}</div>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>{cancelLabel}</button>
        <AsyncButton className={tone === "danger" ? "operator-danger" : "button button--primary"} pendingLabel="Aguarde…" onClick={onConfirm}>
          {confirmLabel}
        </AsyncButton>
      </div>
    </OperatorDialog>
  );
}

/**
 * `const [confirm, confirmDialog] = useConfirm();` — `await confirm({...})`
 * devolve true/false; renderize `confirmDialog` em qualquer lugar da página.
 */
export function useConfirm() {
  const [request, setRequest] = useState<(ConfirmOptions & { resolve: (confirmed: boolean) => void }) | null>(null);
  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => setRequest({ ...options, resolve })), []);
  const settle = (confirmed: boolean) => {
    request?.resolve(confirmed);
    setRequest(null);
  };
  const dialog = request ? <ConfirmDialog {...request} onConfirm={() => settle(true)} onCancel={() => settle(false)} /> : null;
  return [confirm, dialog] as const;
}
