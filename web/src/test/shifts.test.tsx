import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ManagementShiftsPage } from "../pages/home/ShiftsPage";

const TURNOS = [
  { id: 1, nome: "H1", tipo: "hora_extra", hora_inicio: "06:00:00", hora_fim: "08:00:00", ativo: true, ordem: 1 },
  { id: 2, nome: "Oficial", tipo: "expediente", hora_inicio: "08:00:00", hora_fim: "17:30:00", ativo: true, ordem: 2 },
  { id: 3, nome: "H2", tipo: "hora_extra", hora_inicio: "17:30:00", hora_fim: "21:30:00", ativo: true, ordem: 3 },
];

function payload(items = TURNOS) {
  return { items, count: items.length };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function stubFetch(items = TURNOS) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/management/shift-parameters") && method === "GET") return json(payload(items));
    if (path.includes("/management/shift-parameters") && method === "POST") return json({ ok: true, item: items[0] ?? { id: 1 } });
    if (path.includes("/management/shift-parameters/") && method === "DELETE") return json({ ok: true });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderShifts() {
  return render(<MemoryRouter><ManagementShiftsPage /></MemoryRouter>);
}

function linhas() {
  return document.querySelectorAll(".data-table tbody tr").length;
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

// O menu "⋯" usa popover nativo; o jsdom o esconde mas não implementa showPopover, daí `hidden: true` nos itens.
describe("Turnos automáticos — tela IagoDev", () => {
  it("lista os turnos configurados com o expediente em destaque", async () => {
    stubFetch();
    renderShifts();

    await waitFor(() => expect(linhas()).toBe(3));
    expect(screen.getByText("08:00–17:30")).toBeInTheDocument();
    const card = screen.getByText("Horas extras ativas").closest(".metric-card");
    expect(card?.querySelector(".metric-card__value")?.textContent).toBe("2");
  });

  it("cria um novo turno com expediente, H1, H2 e fora de turno ligados ao oficial", async () => {
    const fetchMock = stubFetch([]);
    renderShifts();
    await screen.findByText("Nenhum turno configurado");

    fireEvent.click(screen.getByRole("button", { name: "Novo turno" }));
    fireEvent.change(screen.getByLabelText(/^Nome do turno/), { target: { value: "Turno B" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await screen.findByText("Turno salvo. O próximo ciclo já usa o novo horário.");
    const corpos = fetchMock.mock.calls
      .filter(([path, init]) => String(path).endsWith("/management/shift-parameters") && (init?.method ?? "GET").toUpperCase() === "POST")
      .map(([, init]) => JSON.parse(String(init?.body)));
    expect(corpos).toHaveLength(4);
    expect(corpos[0]).toMatchObject({ nome: "Turno B Oficial", tipo: "expediente", hora_inicio: "08:00", hora_fim: "17:30", turno_id: null });
    expect(corpos.slice(1).map((corpo) => corpo.tipo).sort()).toEqual(["fora_turno", "hora_extra", "hora_extra"]);
    expect(corpos.slice(1).every((corpo) => corpo.turno_id === 1)).toBe(true);
  });

  it("remove um turno", async () => {
    const fetchMock = stubFetch();
    renderShifts();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getAllByRole("menuitem", { name: "Remover", hidden: true })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Remover turno" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) =>
      String(path).includes("/management/shift-parameters/1") && (init?.method ?? "GET").toUpperCase() === "DELETE")).toBe(true));
  });

  it("sem nenhum turno cadastrado, mostra o estado vazio explicando o padrão homologado", async () => {
    stubFetch([]);
    renderShifts();

    await screen.findByText("Nenhum turno configurado");
  });
});
