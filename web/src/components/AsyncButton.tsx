import { useRef, useState, type ButtonHTMLAttributes, type MouseEvent } from "react";

type AsyncButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & {
  onClick: (event: MouseEvent<HTMLButtonElement>) => unknown;
  /** Texto enquanto a ação roda ("Salvando…"); sem ele o rótulo não muda. */
  pendingLabel?: string;
};

/**
 * Botão de ação que fala com o servidor: fica travado até a promessa voltar,
 * então um duplo clique (ou o toque repetido de luva) não vira dois POSTs.
 * A trava por ref vale já no segundo clique do mesmo quadro, antes de o
 * React repintar o `disabled`. Erro continua com quem chamou.
 */
export function AsyncButton({ onClick, pendingLabel, disabled, children, type = "button", ...rest }: AsyncButtonProps) {
  const [pending, setPending] = useState(false);
  const running = useRef(false);

  async function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (running.current) return;
    running.current = true;
    setPending(true);
    try {
      await onClick(event);
    } finally {
      running.current = false;
      setPending(false);
    }
  }

  return (
    <button {...rest} type={type} disabled={disabled || pending} aria-busy={pending || undefined} onClick={(event) => void handleClick(event)}>
      {pending && pendingLabel ? pendingLabel : children}
    </button>
  );
}
