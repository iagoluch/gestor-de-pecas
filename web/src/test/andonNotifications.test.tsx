import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AndonNotifications } from "../components/AndonNotifications";
import type { AndonResource, AndonSnapshot, AndonState } from "../types/andon";
import {
  EMPTY_NOTIFICATION_QUEUE,
  MAX_VISIBLE_NOTIFICATIONS,
  NOTIFICATION_SECONDS,
  detectStateChanges,
  enqueueNotifications,
  expireNotifications,
  syncNotificationsWithFocus,
  type AndonNotification,
} from "../utils/andonNotifications";

function resource(code: string, category: AndonState, extra: Partial<AndonResource["state"]> = {}, op: string | null = null): AndonResource {
  const metric = { value: null, unit: "%", availability: "unavailable" } as unknown as AndonResource["metrics"]["oee"];
  return {
    code,
    name: `Máquina ${code}`,
    sector: "Setor",
    active_operations: op ? 1 : 0,
    state: { category, label: category, ...extra },
    operation: op ? { op, operator: "Maria" } : null,
    metrics: { oee: metric, availability: metric, performance: metric, ftt: metric },
  };
}

function snapshot(sectors: Record<string, AndonResource[]>): AndonSnapshot {
  return {
    generated_at: "2026-10-07T10:00:00",
    sectors: Object.entries(sectors).map(([name, resources]) => ({ name, resources, resource_count: resources.length })),
  } as unknown as AndonSnapshot;
}

function notification(sector: string, code: string): AndonNotification {
  return {
    id: `${sector}-${code}`,
    sector,
    resourceCode: code,
    resourceName: code,
    category: "parada",
    stopClassification: null,
    stateLabel: "Parada",
    reason: null,
    op: null,
    operator: null,
  };
}

describe("detectStateChanges", () => {
  it("não gera balão na primeira carga", () => {
    const first = snapshot({ Corte: [resource("C1", "parada")] });
    expect(detectStateChanges(null, first)).toEqual([]);
  });

  it("gera balão com os dados do snapshot quando o estado muda", () => {
    const before = snapshot({ Corte: [resource("C1", "producao", {}, "OP1")] });
    const after = snapshot({ Corte: [resource("C1", "parada", { display_label: "Falta de material", reason: "Aguardando insumo", stop_classification: "nao_planejada" }, "OP1")] });
    const [only, ...rest] = detectStateChanges(before, after);
    expect(rest).toEqual([]);
    expect(only).toMatchObject({
      sector: "Corte",
      resourceCode: "C1",
      resourceName: "Máquina C1",
      category: "parada",
      stopClassification: "nao_planejada",
      stateLabel: "Falta de material",
      reason: "Aguardando insumo",
      op: "OP1",
      operator: "Maria",
    });
  });

  it("não gera balão quando o estado é o mesmo, mesmo com quantidade ou OP diferentes", () => {
    const before = snapshot({ Corte: [resource("C1", "producao", {}, "OP1")] });
    const after = snapshot({ Corte: [resource("C1", "producao", { duration_seconds: 90 }, "OP2")] });
    expect(detectStateChanges(before, after)).toEqual([]);
  });

  it("gera balão quando só o motivo da parada muda", () => {
    const before = snapshot({ Corte: [resource("C1", "parada", { reason: "Setup" })] });
    const after = snapshot({ Corte: [resource("C1", "parada", { reason: "Quebra" })] });
    expect(detectStateChanges(before, after)).toHaveLength(1);
  });

  it("ignora recurso novo e estados de calendário", () => {
    const before = snapshot({ Corte: [resource("C1", "producao")] });
    const after = snapshot({ Corte: [resource("C1", "fora_turno"), resource("C2", "parada")] });
    expect(detectStateChanges(before, after)).toEqual([]);
  });
});

describe("fila de balões", () => {
  const now = 1_000_000;
  const incoming = ["A", "B", "C", "D", "E"].map((code) => notification("Pintura", code));

  it("suprime recurso do setor em foco e tudo na visão geral", () => {
    expect(enqueueNotifications(EMPTY_NOTIFICATION_QUEUE, incoming, "Pintura", now)).toBe(EMPTY_NOTIFICATION_QUEUE);
    expect(enqueueNotifications(EMPTY_NOTIFICATION_QUEUE, incoming, null, now)).toBe(EMPTY_NOTIFICATION_QUEUE);
    const outside = enqueueNotifications(EMPTY_NOTIFICATION_QUEUE, incoming, "Corte", now);
    expect(outside.visible).toHaveLength(MAX_VISIBLE_NOTIFICATIONS);
  });

  it("mostra no máximo 3, em ordem de chegada, e promove a fila quando vencem", () => {
    const queue = enqueueNotifications(EMPTY_NOTIFICATION_QUEUE, incoming, "Corte", now);
    expect(queue.visible.map((shown) => shown.notification.resourceCode)).toEqual(["A", "B", "C"]);
    expect(queue.pending.map((item) => item.resourceCode)).toEqual(["D", "E"]);

    const stillVisible = expireNotifications(queue, now + NOTIFICATION_SECONDS * 1000 - 1);
    expect(stillVisible.visible).toHaveLength(3);

    const later = expireNotifications(queue, now + NOTIFICATION_SECONDS * 1000);
    expect(later.visible.map((shown) => shown.notification.resourceCode)).toEqual(["D", "E"]);
    expect(later.pending).toEqual([]);
  });

  it("descarta o que passou a estar à vista quando o foco muda", () => {
    const mixed = [notification("Pintura", "P1"), notification("Solda", "S1")];
    const queue = enqueueNotifications(EMPTY_NOTIFICATION_QUEUE, mixed, "Corte", now);
    const focusedPintura = syncNotificationsWithFocus(queue, "Pintura", now);
    expect(focusedPintura.visible.map((shown) => shown.notification.resourceCode)).toEqual(["S1"]);
    expect(syncNotificationsWithFocus(queue, null, now).visible).toEqual([]);
  });
});

describe("AndonNotifications", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const stopped = snapshot({ Corte: [resource("C1", "producao")], Pintura: [resource("P1", "producao")] });
  const afterStop = snapshot({
    Corte: [resource("C1", "producao")],
    Pintura: [resource("P1", "parada", { reason: "Quebra" })],
  });

  it("não mostra balão na primeira carga e mostra o da mudança fora da vista por 8 s", () => {
    const { rerender } = render(<AndonNotifications snapshot={stopped} focusSector="Corte" />);
    const region = screen.getByRole("status");
    expect(region).toBeEmptyDOMElement();

    rerender(<AndonNotifications snapshot={afterStop} focusSector="Corte" />);
    expect(region).toHaveTextContent("Máquina P1");
    expect(region).toHaveTextContent("Pintura");
    expect(region).toHaveAttribute("aria-live", "polite");

    act(() => { vi.advanceTimersByTime(NOTIFICATION_SECONDS * 1000); });
    expect(region).toBeEmptyDOMElement();
  });

  it("não mostra balão de recurso do setor em foco nem na visão geral", () => {
    const focused = render(<AndonNotifications snapshot={stopped} focusSector="Pintura" />);
    focused.rerender(<AndonNotifications snapshot={afterStop} focusSector="Pintura" />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    focused.unmount();

    const overview = render(<AndonNotifications snapshot={stopped} focusSector={null} />);
    overview.rerender(<AndonNotifications snapshot={afterStop} focusSector={null} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});
