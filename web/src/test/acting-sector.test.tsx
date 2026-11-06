import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { setActingSector } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const admin = { id: 1, name: "Gabriel", role: "admin", assigned_level: "admin", management_access: true, andon_access: true, operator_access: false };
const acting = { ...admin, name: "Gabriel (gestão)", role: "operador_dobra", management_access: false, andon_access: false, operator_access: true, acting_sector: "Dobra" };

afterEach(() => {
  setActingSector(null);
  vi.restoreAllMocks();
});

describe("Apontamento por setor", () => {
  it("entra no setor enviando o cabeçalho e mostra a faixa de gestão", async () => {
    let inMode = false;
    const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/visao-geral") || path.includes("/overview")) return json({});
      if (path.includes("/auth/session")) return json(inMode ? acting : admin);
      if (path.includes("/management/operator-sectors")) return json({ items: [{ level: "operador_dobra", name: "Dobra", resources: ["Dobradeira 1"] }] });
      if (path.includes("/operator/context")) {
        expect(new Headers(init?.headers).get("X-Acting-Sector")).toBe("operador_dobra");
        return json({ sector: "Dobra", resources: ["Dobradeira 1"], workflow: "standard" });
      }
      return json({ items: [] });
    });
    vi.stubGlobal("fetch", mock);
    render(<MemoryRouter initialEntries={["/inicio/apontamento-por-setor"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    const card = await screen.findByRole("button", { name: /Dobra/ });
    inMode = true;
    fireEvent.click(card);
    await waitFor(() => expect(screen.getByText(/Apontando como Dobra — feito pela gestão/)).toBeTruthy());
    // Sair: o cabeçalho deixa de ser guardado (o app recarrega a aba já com a sessão de gestão).
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole("button", { name: "Sair do modo setor" }));
    expect(sessionStorage.getItem("gestor:acting-sector")).toBeNull();
  });
});
