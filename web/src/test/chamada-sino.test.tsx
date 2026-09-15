import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChamadaSino } from "../components/ChamadaSino";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderSino() {
  return render(
    <MemoryRouter initialEntries={["/inicio/visao-geral"]}>
      <Routes>
        <Route path="/inicio/visao-geral" element={<ChamadaSino />} />
        <Route path="/inicio/chamadas" element={<div>Página de chamadas</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("sininho de chamadas", () => {
  it("mostra a contagem de chamadas não vistas desta conta", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/chamadas/nao-vistas")) return json({ count: 3 });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));
    renderSino();
    await screen.findByText("3");
  });

  it("sem chamadas não vistas, não mostra contador", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ count: 0 })));
    renderSino();
    await waitFor(() => expect(screen.getByRole("button")).toBeInTheDocument());
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("ao clicar, marca como vistas e navega para o histórico", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/chamadas/marcar-vistas") && init?.method === "POST") {
        return json({ ok: true, count: 0 });
      }
      if (path.includes("/chamadas/nao-vistas")) return json({ count: 2 });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderSino();
    await screen.findByText("2");
    fireEvent.click(screen.getByRole("button"));
    await screen.findByText("Página de chamadas");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(
        ([path, init]) => String(path).includes("/chamadas/marcar-vistas") && (init as RequestInit | undefined)?.method === "POST",
      )).toBe(true);
    });
  });
});
