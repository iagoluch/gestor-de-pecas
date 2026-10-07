import type { StopClassification } from "../types/api";
import type { AndonResource, AndonSnapshot, AndonState } from "../types/andon";
import { displayText } from "./format";

/**
 * Balões de notificação da TV do Andon.
 *
 * Tudo aqui é puro: o diff entre dois snapshots e a fila dos balões não tocam
 * em relógio, DOM nem rede. O estado do recurso continua vindo pronto do
 * backend; o cliente só compara o que já chegou.
 */

export const MAX_VISIBLE_NOTIFICATIONS = 3;
export const NOTIFICATION_SECONDS = 8;

/**
 * Estados que merecem aviso. `fora_turno`, `sem_demanda` e `desconhecido` ficam
 * de fora: são leituras de calendário/ausência de dado, não eventos no recurso,
 * e a virada de turno dispararia um balão por máquina de uma só vez.
 */
const NOTIFIABLE_STATES: ReadonlySet<AndonState> = new Set<AndonState>([
  "producao",
  "parada",
  "setup",
  "retrabalho",
  "fila",
  "atividade_sem_op",
]);

export interface AndonNotification {
  id: string;
  /** Painel em que o recurso aparece no quadro (`sectors[].name` do snapshot). */
  sector: string;
  resourceCode: string;
  resourceName: string;
  category: AndonState;
  stopClassification: StopClassification | null;
  /** Rótulo do novo estado, no mesmo texto do cartão. */
  stateLabel: string;
  /** Motivo da parada, quando houver e for diferente do rótulo. */
  reason: string | null;
  op: string | null;
  operator: string | null;
}

function stateLabel(resource: AndonResource) {
  const { state } = resource;
  return displayText(state.category === "parada"
    ? state.display_label ?? state.reason ?? "Motivo não informado"
    : state.display_label ?? state.label);
}

function stopMotive(resource: AndonResource) {
  const { state } = resource;
  return `${state.reason ?? state.display_label ?? ""}\u0000${state.stop_classification ?? ""}`;
}

/** Só categoria e, dentro da parada, o motivo/classificação mudam o estado. */
function stateChanged(before: AndonResource, after: AndonResource) {
  if (before.state.category !== after.state.category) return true;
  return after.state.category === "parada" && stopMotive(before) !== stopMotive(after);
}

function resourceId(sector: string, code: string) {
  return `${sector}\u0000${code}`;
}

function toNotification(sector: string, resource: AndonResource): AndonNotification {
  const label = stateLabel(resource);
  const reason = resource.state.category === "parada" && resource.state.reason
    ? displayText(resource.state.reason)
    : null;
  return {
    id: `${resourceId(sector, resource.code)}\u0000${resource.state.category}\u0000${resource.state.started_at ?? ""}\u0000${reason ?? ""}`,
    sector,
    resourceCode: resource.code,
    resourceName: resource.name,
    category: resource.state.category,
    stopClassification: resource.state.stop_classification ?? null,
    stateLabel: label,
    reason: reason && reason !== label ? reason : null,
    op: resource.operation?.op ?? null,
    operator: resource.operation?.operator ?? null,
  };
}

/**
 * Compara o snapshot novo com o anterior, por setor + código do recurso.
 * Sem snapshot anterior (primeira carga) e recurso que acabou de entrar no
 * Andon não geram balão: nenhum dos dois é uma mudança de estado.
 */
export function detectStateChanges(previous: AndonSnapshot | null, next: AndonSnapshot): AndonNotification[] {
  if (!previous) return [];
  const before = new Map<string, AndonResource>();
  for (const sector of previous.sectors) {
    for (const resource of sector.resources) before.set(resourceId(sector.name, resource.code), resource);
  }
  const changes: AndonNotification[] = [];
  for (const sector of next.sectors) {
    for (const resource of sector.resources) {
      const prior = before.get(resourceId(sector.name, resource.code));
      if (!prior || !NOTIFIABLE_STATES.has(resource.state.category)) continue;
      if (stateChanged(prior, resource)) changes.push(toNotification(sector.name, resource));
    }
  }
  return changes;
}

export interface ShownNotification {
  notification: AndonNotification;
  /** Instante (ms) em que o balão sai da tela. */
  expiresAt: number;
}

export interface NotificationQueue {
  visible: ShownNotification[];
  pending: AndonNotification[];
}

export const EMPTY_NOTIFICATION_QUEUE: NotificationQueue = { visible: [], pending: [] };

/**
 * Um recurso está "à vista" quando o setor dele já está na tela: na visão geral
 * (`focusSector === null`) todos estão; num setor em foco, só os daquele setor.
 * Balão só serve para o que está fora da vista.
 */
export function isInView(notification: AndonNotification, focusSector: string | null) {
  return focusSector === null || notification.sector === focusSector;
}

function promote(queue: NotificationQueue, now: number): NotificationQueue {
  const room = MAX_VISIBLE_NOTIFICATIONS - queue.visible.length;
  if (room <= 0 || queue.pending.length === 0) return queue;
  const expiresAt = now + NOTIFICATION_SECONDS * 1000;
  return {
    visible: [...queue.visible, ...queue.pending.slice(0, room).map((notification) => ({ notification, expiresAt }))],
    pending: queue.pending.slice(room),
  };
}

/** Enfileira (FIFO) o que está fora da vista; promove até o máximo visível. */
export function enqueueNotifications(
  queue: NotificationQueue,
  incoming: AndonNotification[],
  focusSector: string | null,
  now: number,
): NotificationQueue {
  const accepted = incoming.filter((notification) => !isInView(notification, focusSector));
  if (accepted.length === 0) return queue;
  return promote({ visible: queue.visible, pending: [...queue.pending, ...accepted] }, now);
}

/** Remove os balões vencidos e promove os que esperavam. */
export function expireNotifications(queue: NotificationQueue, now: number): NotificationQueue {
  const visible = queue.visible.filter((shown) => shown.expiresAt > now);
  if (visible.length === queue.visible.length) return promote(queue, now);
  return promote({ visible, pending: queue.pending }, now);
}

/** Quando o foco muda, descarta o que passou a estar à vista. */
export function syncNotificationsWithFocus(
  queue: NotificationQueue,
  focusSector: string | null,
  now: number,
): NotificationQueue {
  const visible = queue.visible.filter((shown) => !isInView(shown.notification, focusSector));
  const pending = queue.pending.filter((notification) => !isInView(notification, focusSector));
  if (visible.length === queue.visible.length && pending.length === queue.pending.length) return queue;
  return promote({ visible, pending }, now);
}

/** Próximo instante em que a fila precisa ser reavaliada (`null` = nenhum). */
export function nextNotificationExpiry(queue: NotificationQueue): number | null {
  if (queue.visible.length === 0) return null;
  return Math.min(...queue.visible.map((shown) => shown.expiresAt));
}
