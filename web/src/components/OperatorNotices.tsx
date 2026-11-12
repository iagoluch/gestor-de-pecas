/**
 * Avisos e erros do posto como popups no canto superior direito, mais um sino
 * na barra superior (com pontinho vermelho enquanto houver aviso ativo) que
 * reabre a lista. Avisos de informação/sucesso somem sozinhos; alerta e erro
 * ficam até o operador fechar.
 */
import { useEffect, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "../styles/operator-notices.css";

export type OperatorNoticeTone = "info" | "ok" | "warn" | "err";
export type OperatorNoticeItem = { key: string; tone: OperatorNoticeTone; text: string };

/** Lugar na barra superior (OperatorShell) onde a tela do posto põe o sino. */
export const NOTICE_SLOT_ID = "operator-notice-slot";
const AUTO_HIDE_MS = 6000;

const ICON: Record<OperatorNoticeTone, ReactNode> = {
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  ok: <><circle cx="12" cy="12" r="9" /><path d="m8 12.5 2.7 2.7L16 9.8" /></>,
  warn: <><path d="M10.3 3.9 2.4 17.6A2 2 0 0 0 4.1 20.6h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
  err: <><circle cx="12" cy="12" r="9" /><path d="m15 9-6 6M9 9l6 6" /></>,
};

const sig = (item: OperatorNoticeItem) => `${item.key}|${item.text}`;

function NoticeCard({ item, onClose }: { item: OperatorNoticeItem; onClose?: () => void }) {
  return (
    <div className={`op-notice op-notice--${item.tone}`} role={item.tone === "err" ? "alert" : "status"}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{ICON[item.tone]}</svg>
      <span>{item.text}</span>
      {onClose ? <button type="button" className="op-notice__close" aria-label="Fechar aviso" onClick={onClose}>×</button> : null}
    </div>
  );
}

export function OperatorNotices({ items }: { items: OperatorNoticeItem[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());
  const [open, setOpen] = useState(false);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useEffect(() => { setSlot(document.getElementById(NOTICE_SLOT_ID)); }, []);

  const visible = items.filter((item) => !dismissed.has(sig(item)));
  const dismiss = (item: OperatorNoticeItem) => setDismissed((prev) => new Set(prev).add(sig(item)));

  // Esquece avisos que já saíram da lista: se o mesmo aviso voltar, aparece de novo.
  const liveKey = JSON.stringify(items.map(sig));
  useEffect(() => {
    const live = new Set<string>(JSON.parse(liveKey));
    setDismissed((prev) => ([...prev].every((k) => live.has(k)) ? prev : new Set([...prev].filter((k) => live.has(k)))));
  }, [liveKey]);

  // Informação e sucesso saem sozinhos; alerta e erro esperam o operador.
  const autoKey = JSON.stringify(visible.filter((i) => i.tone === "info" || i.tone === "ok").map(sig));
  useEffect(() => {
    const auto: string[] = JSON.parse(autoKey);
    if (!auto.length) return;
    const timer = window.setTimeout(() => setDismissed((prev) => new Set([...prev, ...auto])), AUTO_HIDE_MS);
    return () => window.clearTimeout(timer);
  }, [autoKey]);

  const bell = slot ? createPortal(
    <div className="op-bell">
      <button type="button" className="op-bell__btn" aria-label={items.length ? `Avisos (${items.length})` : "Avisos"} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 18a3 3 0 0 0 6 0M4.5 9.5a7.5 7.5 0 0 1 15 0c0 4 1.5 5 1.5 5h-18s1.5-1 1.5-5Z" /></svg>
        {items.length ? <span className="op-bell__dot" aria-hidden="true" /> : null}
      </button>
      {open ? (
        <div className="op-bell__panel">
          {items.length ? items.map((item) => <NoticeCard key={item.key} item={item} />) : <p className="op-bell__empty">Nenhum aviso agora.</p>}
        </div>
      ) : null}
    </div>,
    slot,
  ) : null;

  return (
    <>
      {bell}
      {!open && visible.length ? createPortal(
        <div className="op-toasts">{visible.map((item) => <NoticeCard key={item.key} item={item} onClose={() => dismiss(item)} />)}</div>,
        document.body,
      ) : null}
    </>
  );
}
