import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ROTATION_SECONDS, cycleSectorNames, useAndonSectorCycle } from "../hooks/useAndonSectorCycle";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

function tick(seconds = ROTATION_SECONDS) {
  act(() => { vi.advanceTimersByTime(seconds * 1000); });
}

describe("useAndonSectorCycle", () => {
  it("usa 12 s por etapa", () => {
    expect(ROTATION_SECONDS).toBe(12);
  });

  it("começa na visão geral, passa por cada setor e volta à visão geral", () => {
    const { result } = renderHook(() => useAndonSectorCycle(["Corte", "Solda"], true));
    expect(result.current).toBeNull();
    tick(ROTATION_SECONDS - 1);
    expect(result.current).toBeNull();
    tick(1);
    expect(result.current).toBe("Corte");
    tick();
    expect(result.current).toBe("Solda");
    tick();
    expect(result.current).toBeNull();
    tick();
    expect(result.current).toBe("Corte");
  });

  it("não reinicia o temporizador quando o snapshot traz a mesma lista de setores", () => {
    const { result, rerender } = renderHook(({ names }) => useAndonSectorCycle(names, true), {
      initialProps: { names: ["Corte", "Solda"] },
    });
    tick(ROTATION_SECONDS - 2);
    rerender({ names: ["Corte", "Solda"] });
    tick(2);
    expect(result.current).toBe("Corte");
  });

  it("fica só na visão geral com um setor ou fora da TV", () => {
    const single = renderHook(() => useAndonSectorCycle(["Corte"], true));
    tick(ROTATION_SECONDS * 3);
    expect(single.result.current).toBeNull();

    const manager = renderHook(() => useAndonSectorCycle(["Corte", "Solda"], false));
    tick(ROTATION_SECONDS * 3);
    expect(manager.result.current).toBeNull();
  });
});

describe("cycleSectorNames", () => {
  it("mantém a ordem do snapshot e pula setor sem recursos ativos", () => {
    const names = cycleSectorNames([
      { name: "Corte", resources: [{}] },
      { name: "Solda", resources: [] },
      { name: "Pintura", resource_count: 2, resources: [] },
      { name: "Caldeiraria", resource_count: 0, resources: [{}] },
    ]);
    expect(names).toEqual(["Corte", "Pintura"]);
    expect(cycleSectorNames(undefined)).toEqual([]);
  });

  it("pula o setor vazio no ciclo", () => {
    const names = cycleSectorNames([
      { name: "Corte", resources: [{}] },
      { name: "Solda", resources: [] },
      { name: "Pintura", resources: [{}] },
    ]);
    const { result } = renderHook(() => useAndonSectorCycle(names, true));
    tick();
    expect(result.current).toBe("Corte");
    tick();
    expect(result.current).toBe("Pintura");
    tick();
    expect(result.current).toBeNull();
  });
});
