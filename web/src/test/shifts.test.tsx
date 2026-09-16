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
    if (path.includes("/management/shift-parameters") && method === "POST") return json({ ok: true, item: items[0] });
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

describe("Turnos automáticos — tela IagoDev", () => {
  it("lista os turnos configurados com o expediente em destaque", async () => {
    stubFetch();
    renderShifts();

    await waitFor(() => expect(linhas()).toBe(3));
    expect(screen.getByText("08:00–17:30")).toBeInTheDocument();
    const card = screen.getByText("Horas extras ativas").closest(".metric-card");
    expect(card?.querySelector(".metric-card__value")?.textContent).toBe("2");
  });

  it("cria um novo turno pelo formulário", async () => {
    const fetchMock = stubFetch();
    renderShifts();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getByRole("button", { name: "Novo turno" }));
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "H3" } });
    fireEvent.change(screen.getByLabelText("Início"), { target: { value: "21:30" } });
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "23:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await screen.findByText("Turno salvo. O próximo ciclo já usa o novo horário.");
    const chamada = fetchMock.mock.calls.find(([path, init]) =>
      String(path).endsWith("/management/shift-parameters") && (init?.method ?? "GET").toUpperCase() === "POST");
    const corpo = JSON.parse(String(chamada?.[1]?.body));
    expect(corpo).toMatchObject({ nome: "H3", tipo: "hora_extra", hora_inicio: "21:30", hora_fim: "23:00" });
  });

  it("remove um turno", async () => {
    const fetchMock = stubFetch();
    renderShifts();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getAllByRole("button", { name: "Remover" })[0]);

    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) =>
      String(path).includes("/management/shift-parameters/1") && (init?.method ?? "GET").toUpperCase() === "DELETE")).toBe(true));
  });

  it("sem nenhum turno cadastrado, mostra o estado vazio explicando o padrão homologado", async () => {
    stubFetch([]);
    renderShifts();

    await screen.findByText("Nenhum turno configurado");
  });
});
