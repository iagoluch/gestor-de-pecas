import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useOncePerMinute } from "../hooks/useOncePerMinute";

describe("useOncePerMinute", () => {
  afterEach(() => vi.useRealTimers());

  it("segura o valor dentro do mesmo minuto e troca na virada", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-19T10:00:05"));
    const { result, rerender } = renderHook(({ value }) => useOncePerMinute(value, "f"), { initialProps: { value: 100 } });
    rerender({ value: 138 });
    vi.setSystemTime(new Date("2026-10-19T10:00:50"));
    rerender({ value: 176 });
    expect(result.current).toBe(100);
    vi.setSystemTime(new Date("2026-10-19T10:01:01"));
    rerender({ value: 214 });
    expect(result.current).toBe(214);
  });

  it("troca na hora quando o filtro muda ou quando ainda não havia valor", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-19T10:00:05"));
    const { result, rerender } = renderHook(({ value, key }) => useOncePerMinute<number | undefined>(value, key), {
      initialProps: { value: undefined as number | undefined, key: "a" },
    });
    rerender({ value: 10, key: "a" });
    expect(result.current).toBe(10);
    rerender({ value: 20, key: "b" });
    expect(result.current).toBe(20);
  });
});
