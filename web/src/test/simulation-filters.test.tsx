import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FilterBar } from "../components/FilterBar";
import { FilterProvider, useManagementFilters } from "../filters/FilterContext";
import { ReferenceClockProvider } from "../system/ReferenceClock";

// O navegador da homologação está em 26/08; o backend simulado responde 24/08 08:32.
const RELOGIO_NAVEGADOR = new Date("2026-08-26T14:00:00");
const REFERENCIA_SIMULACAO = "2026-08-24T08:32:00";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

function capabilities(simulacao: boolean) {
  return json({
    schema_version: 15,
    simulation: simulacao
      ? { enabled: true, reference_time: REFERENCIA_SIMULACAO }
      : { enabled: false, reference_time: null },
  });
}

/** Registra toda consulta que a interface montaria a partir dos filtros. */
const consultas: string[] = [];

function Probe() {
  const { query } = useManagementFilters();
  consultas.push(query);
  return <output data-testid="query">{query}</output>;
}

function montar(simulacao: boolean) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/system/capabilities")) return capabilities(simulacao);
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const utils = render(
    <MemoryRouter>
      <ReferenceClockProvider>
        <FilterProvider><FilterBar /><Probe /></FilterProvider>
      </ReferenceClockProvider>
    </MemoryRouter>,
  );
  return { fetchMock, ...utils };
}

function periodo(query: string) {
  const params = new URLSearchParams(query);
  return { inicio: params.get("inicio"), fim: params.get("fim") };
}

beforeEach(() => {
  consultas.length = 0;
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(RELOGIO_NAVEGADOR);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("filtros gerenciais e relógio de referência", () => {
  it("ancora o período padrão na referência do backend em modo simulação", async () => {
    montar(true);
    const saida = await screen.findByTestId("query");
    expect(periodo(saida.textContent ?? "")).toEqual({
      inicio: "2026-08-24T00:00:00",
      fim: "2026-08-24T23:59:59",
    });
    // Nenhuma consulta chegou a ser montada com o relógio do navegador.
    expect(consultas.some((q) => q.includes("2026-08-26"))).toBe(false);
  });

  it("aplica Hoje sobre a referência da simulação, não sobre o navegador", async () => {
    montar(true);
    await screen.findByTestId("query");
    fireEvent.click(screen.getByRole("button", { name: "Hoje" }));
    await waitFor(() => {
      expect(periodo(screen.getByTestId("query").textContent ?? "")).toEqual({
        inicio: "2026-08-24T00:00:00",
        fim: "2026-08-24T23:59:59",
      });
    });
  });

  it("aplica Ontem e hoje sobre a referência da simulação", async () => {
    montar(true);
    await screen.findByTestId("query");
    fireEvent.click(screen.getByRole("button", { name: "Ontem e hoje" }));
    await waitFor(() => {
      expect(periodo(screen.getByTestId("query").textContent ?? "")).toEqual({
        inicio: "2026-08-23T00:00:00",
        fim: "2026-08-24T23:59:59",
      });
    });
  });

  it("mantém a referência após refresh e em deep link direto", async () => {
    const primeira = montar(true);
    await screen.findByTestId("query");
    primeira.unmount();

    // Refresh / deep link: a árvore é remontada do zero, como numa navegação direta.
    consultas.length = 0;
    montar(true);
    const saida = await screen.findByTestId("query");
    expect(periodo(saida.textContent ?? "").inicio).toBe("2026-08-24T00:00:00");
    expect(consultas.every((q) => q.includes("2026-08-24"))).toBe(true);
  });

  it("não interfere no ambiente normal: mantém o relógio real", async () => {
    montar(false);
    const saida = await screen.findByTestId("query");
    expect(periodo(saida.textContent ?? "")).toEqual({
      inicio: "2026-08-26T00:00:00",
      fim: "2026-08-26T23:59:59",
    });
  });

  it("volta ao relógio real quando as capabilities falham", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ code: "erro" }, 500)));
    render(
      <MemoryRouter>
        <ReferenceClockProvider>
          <FilterProvider><FilterBar /><Probe /></FilterProvider>
        </ReferenceClockProvider>
      </MemoryRouter>,
    );
    const saida = await screen.findByTestId("query");
    expect(periodo(saida.textContent ?? "").inicio).toBe("2026-08-26T00:00:00");
  });
});
