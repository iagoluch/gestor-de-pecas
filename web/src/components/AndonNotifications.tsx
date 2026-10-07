import { useEffect, useRef, useState } from "react";
import type { AndonSnapshot } from "../types/andon";
import {
  EMPTY_NOTIFICATION_QUEUE,
  detectStateChanges,
  enqueueNotifications,
  expireNotifications,
  nextNotificationExpiry,
  syncNotificationsWithFocus,
} from "../utils/andonNotifications";

/**
 * Balões de mudança de estado no canto superior esquerdo da TV. Apresentação
 * fina: o diff e a fila vivem em `utils/andonNotifications`. Sem botões — o
 * balão some sozinho.
 */
export function AndonNotifications({ snapshot, focusSector }: { snapshot: AndonSnapshot; focusSector: string | null }) {
  const [queue, setQueue] = useState(EMPTY_NOTIFICATION_QUEUE);
  const previous = useRef<AndonSnapshot | null>(null);
  const focusRef = useRef(focusSector);

  // Declarado antes do efeito do snapshot: no mesmo commit, o foco novo já vale.
  useEffect(() => {
    focusRef.current = focusSector;
    setQueue((current) => syncNotificationsWithFocus(current, focusSector, Date.now()));
  }, [focusSector]);

  useEffect(() => {
    const changes = detectStateChanges(previous.current, snapshot);
    previous.current = snapshot;
    if (changes.length === 0) return;
    setQueue((current) => enqueueNotifications(current, changes, focusRef.current, Date.now()));
  }, [snapshot]);

  const expiry = nextNotificationExpiry(queue);
  useEffect(() => {
    if (expiry === null) return undefined;
    const timer = window.setTimeout(
      () => setQueue((current) => expireNotifications(current, Math.max(Date.now(), expiry))),
      Math.max(0, expiry - Date.now()),
    );
    return () => window.clearTimeout(timer);
  }, [expiry]);

  return (
    <div className="andon-toasts" role="status" aria-live="polite" aria-atomic="false">
      {queue.visible.map(({ notification }) => (
        <article
          key={notification.id}
          className={`andon-toast andon-toast--${notification.category}`}
          data-state={notification.category}
          data-stop-classification={notification.stopClassification ?? undefined}
        >
          <header className="andon-toast__header">
            <strong>{notification.resourceName}</strong>
            <span>{notification.sector}</span>
          </header>
          <p className="andon-toast__state"><i aria-hidden="true" />{notification.stateLabel}</p>
          {notification.reason ? <p className="andon-toast__detail">Motivo: {notification.reason}</p> : null}
          {notification.op || notification.operator ? (
            <p className="andon-toast__detail">
              {notification.op ? `OP ${notification.op}` : null}
              {notification.op && notification.operator ? " • " : null}
              {notification.operator ?? null}
            </p>
          ) : null}
        </article>
      ))}
    </div>
  );
}
