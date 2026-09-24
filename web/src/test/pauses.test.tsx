import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ManagementPausesPage } from "../pages/home/PausesPage";

const PAUSAS = [
  { id: 1, tipo_setor: "Corte", nome: "Almoço", hora_inicio: "12:10:00", hora_fim: "12:52:00", ativo: true, ordem: 1 },
  { id: 2, tipo_setor: "Corte", nome: "Café", hora_inicio: "15:30:00", hora_fim: "15:45:00", ativo: true, ordem: 2 },
  { id: 3, tipo_setor: "Dobra", nome: "Almoço", hora_inicio: "11:40:00", hora_fim: "12:22:00", ativo: false, ordem: 1 },
  { id: 4, tipo_setor: "Solda", nome: "Pausa para ginástica", hora_inicio: "09:00:00", hora_fim: "09:10:00", ativo: true, ordem: 1 },
];

function payload(items = PAUSAS) {
  return {
    items,
    sectors: [...new Set(items.map((item) => item.tipo_setor))].sort(),
    count: items.length,
    active: items.filter((item) => item.ativo).length,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function stubFetch(items = PAUSAS) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/management/pauses") && method === "GET") return json(payload(items));
    if (path.includes("/management/pauses") && method === "POST") return json({ ok: true, item: items[0] });
    if (path.includes("/management/pauses/") && method === "DELETE") return json({ ok: true });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderPauses() {
  return render(<MemoryRouter><ManagementPausesPage /></MemoryRouter>);
}

function corpoDaTabela() {
  return document.querySelector(".data-table tbody")?.textContent ?? "";
}

function linhas() {
  return document.querySelectorAll(".data-table tbody tr").length;
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("Pausas automáticas — organização e filtros", () => {
  it("lista todas as pausas cadastradas com tipo e situação legíveis", async () => {
    stubFetch();
    renderPauses();

    await waitFor(() => expect(linhas()).toBe(4));
    expect(screen.getByText("4 pausas configuradas")).toBeInTheDocument();
    expect(corpoDaTabela()).toContain("Pausa para ginástica");
    // A coluna de tipo aparece porque a descrição livre não repete o tipo.
    expect(screen.getByRole("columnheader", { name: "Tipo" })).toBeInTheDocument();
    expect(corpoDaTabela()).toContain("Ginástica laboral");
    expect(screen.getAllByText("Ativa").length).toBe(3);
    expect(screen.getAllByText("Inativa").length).toBe(1);
  });

  it("filtra por setor", async () => {
    stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Corte" } });

    await waitFor(() => expect(linhas()).toBe(2));
    expect(corpoDaTabela()).not.toContain("Dobra");
    expect(screen.getByText("2 de 4 pausas no recorte atual")).toBeInTheDocument();
  });

  it("filtra por tipo de pausa", async () => {
    stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.change(screen.getByLabelText("Tipo de pausa"), { target: { value: "cafe" } });

    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("Café");
    expect(corpoDaTabela()).not.toContain("Almoço");
  });

  it("combina setor, tipo e busca e limpa a seleção", async () => {
    stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Corte" } });
    fireEvent.change(screen.getByLabelText("Tipo de pausa"), { target: { value: "almoco" } });
    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("12:10");

    fireEvent.change(screen.getByLabelText("Buscar por setor, pausa ou horário"), { target: { value: "15:30" } });
    await waitFor(() => expect(screen.getByText("Nenhuma pausa no filtro atual")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    await waitFor(() => expect(linhas()).toBe(4));
    expect((screen.getByLabelText("Setor") as HTMLSelectElement).value).toBe("");
    expect((screen.getByLabelText("Tipo de pausa") as HTMLSelectElement).value).toBe("");
  });

  it("explica o resultado vazio sem parecer tela quebrada e sem código técnico", async () => {
    stubFetch([]);
    renderPauses();

    expect(await screen.findByText("Nenhuma pausa configurada")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sem_registros|dados_insuficientes|not_configured|undefined|null/);
  });

  it("mantém o recorte enquanto o usuário navega e volta para a tela", async () => {
    stubFetch();
    const primeira = renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));
    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Dobra" } });
    await waitFor(() => expect(linhas()).toBe(1));
    primeira.unmount();

    renderPauses();
    await waitFor(() => expect((screen.getByLabelText("Setor") as HTMLSelectElement).value).toBe("Dobra"));
    await waitFor(() => expect(linhas()).toBe(1));
  });

  it("não dispara consulta nova ao trocar um filtro", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));
    const antes = mock.mock.calls.length;

    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Corte" } });
    await waitFor(() => expect(linhas()).toBe(2));

    expect(mock.mock.calls.length).toBe(antes);
  });

  it("edita uma pausa existente no diálogo e salva pelo contrato atual", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.click(screen.getAllByRole("button", { name: "Editar" })[0]);
    expect(await screen.findByRole("dialog", { name: "Editar pausa" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Fim"), { target: { value: "12:55" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Pausa salva"));
    const post = mock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post?.[1] as RequestInit).body))).toMatchObject({ hora_fim: "12:55", ativo: true });
  });

  it("cria uma pausa nova pelo diálogo", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.click(screen.getByRole("button", { name: "Nova pausa" }));
    expect(await screen.findByRole("dialog", { name: "Nova pausa" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Descrição"), { target: { value: "Reunião de turno" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Pausa salva"));
    const post = mock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
    const corpo = JSON.parse(String((post?.[1] as RequestInit).body));
    expect(corpo).toMatchObject({ nome: "Reunião de turno", ativo: true });
    expect(corpo.id).toBeUndefined();
  });

  it("desativa e reativa pela ação da linha sem mudar o contrato", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.click(screen.getAllByRole("button", { name: "Desativar" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Desativar pausa" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Pausa salva"));
    const desativa = mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST").at(-1);
    expect(JSON.parse(String((desativa?.[1] as RequestInit).body)).ativo).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Ativar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Ativar pausa" }));
    await waitFor(() => {
      const ativa = mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST").at(-1);
      expect(JSON.parse(String((ativa?.[1] as RequestInit).body)).ativo).toBe(true);
    });
  });

  it("remove a pausa pelo endpoint existente", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.click(screen.getAllByRole("button", { name: "Remover" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Remover pausa" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Pausa removida."));
    expect(mock.mock.calls.some(([path, init]) => String(path).includes("/management/pauses/")
      && (init as RequestInit)?.method === "DELETE")).toBe(true);
  });

  it("cancela Desativar e Remover quando o usuário não confirma", async () => {
    const mock = stubFetch();
    renderPauses();
    await waitFor(() => expect(linhas()).toBe(4));

    fireEvent.click(screen.getAllByRole("button", { name: "Desativar" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Remover" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    expect(mock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "POST")).toBe(false);
    expect(mock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "DELETE")).toBe(false);
  });
});
