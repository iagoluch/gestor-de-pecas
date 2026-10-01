import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManagementChamadasPage } from "../pages/home/ChamadasPage";
import { DevChamadasContatosPage } from "../pages/home/ChamadasContatosPage";

vi.mock("../auth/AuthContext", () => {
  const auth = { user: { id: 1, name: "Admin", role: "admin" } };
  return { useAuth: () => auth, useOptionalAuth: () => auth };
});

const CONTATOS = [{ id: 7, nome: "Carla Souza", funcao: "Manutenção", ativo: true, padrao_gestao: false, setores: [] }];

function stubFetch() {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/contatos") ? { items: CONTATOS } : { items: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const deletes = (mock: ReturnType<typeof stubFetch>) => mock.mock.calls.filter(([, init]) => init?.method === "DELETE");

afterEach(() => vi.restoreAllMocks());

// O menu "⋯" usa popover nativo; o jsdom o esconde mas não implementa showPopover, daí `hidden: true` nos itens.
function historicoFetch(items: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items }), { status: 200, headers: { "content-type": "application/json" } })));
}

const base = { contato_nome: "Carla", contato_funcao: "Manutenção", motivo: "Qualidade", comentario: "x", solicitante_nome: "Op", solicitante_nivel: "operador", solicitante_cracha: null, solicitante_email: null };
const minutosAtras = (min: number) => new Date(Date.now() - min * 60_000).toISOString();

describe("Histórico de chamadas — coluna Aviso", () => {
  it("mostra Enviado, Falhou (com motivo no title), Enviando… e Sem confirmação", async () => {
    historicoFetch([
      { ...base, id: 1, telegram_enviado: true, telegram_status: "enviado", telegram_erro: null, criado_em: minutosAtras(1) },
      { ...base, id: 2, telegram_enviado: false, telegram_status: "falhou", telegram_erro: "Contato sem Telegram cadastrado", criado_em: minutosAtras(1) },
      { ...base, id: 3, telegram_enviado: false, telegram_status: "pendente", telegram_erro: null, criado_em: minutosAtras(1) },
      { ...base, id: 4, telegram_enviado: false, telegram_status: "pendente", telegram_erro: null, criado_em: minutosAtras(10) },
    ]);
    render(<MemoryRouter><ManagementChamadasPage /></MemoryRouter>);
    await screen.findByText("Últimas chamadas");
    expect(await screen.findByText("Enviado")).toBeInTheDocument();
    expect(screen.getByText("Falhou")).toHaveAttribute("title", "Contato sem Telegram cadastrado");
    expect(screen.getByText("Enviando…")).toBeInTheDocument();
    expect(screen.getByText("Sem confirmação")).toBeInTheDocument();
    // Métrica = falhou + sem confirmação.
    expect(screen.getByText("Sem aviso no Telegram").closest("article")?.querySelector(".metric-card__value")).toHaveTextContent("2");
  });

  it("sem telegram_status (mensagem antiga) cai em telegram_enviado", async () => {
    historicoFetch([
      { ...base, id: 1, telegram_enviado: true, criado_em: minutosAtras(60) },
      { ...base, id: 2, telegram_enviado: false, criado_em: minutosAtras(60) },
    ]);
    render(<MemoryRouter><ManagementChamadasPage /></MemoryRouter>);
    expect(await screen.findByText("Enviado")).toBeInTheDocument();
    expect(screen.getByText("Falhou")).toBeInTheDocument();
    expect(screen.queryByText("Sem confirmação")).toBeNull();
  });
});

describe("Contatos de chamada — GE-01", () => {
  it("só remove o contato depois da confirmação", async () => {
    const mock = stubFetch();
    render(<MemoryRouter><DevChamadasContatosPage /></MemoryRouter>);
    const remover = await screen.findByRole("menuitem", { name: "Remover", hidden: true });

    fireEvent.click(remover);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(deletes(mock)).toHaveLength(0);

    fireEvent.click(remover);
    fireEvent.click(await screen.findByRole("button", { name: "Remover contato" }));
    await waitFor(() => expect(deletes(mock)).toHaveLength(1));
    expect(String(deletes(mock)[0][0])).toContain("/api/v1/chamadas/admin/contatos/7");
  });

  it("o histórico da gestão não carrega nem mostra o cadastro de contatos", async () => {
    const mock = stubFetch();
    render(<MemoryRouter><ManagementChamadasPage /></MemoryRouter>);
    await screen.findByText("Últimas chamadas");
    expect(screen.queryByText("Contatos cadastrados")).toBeNull();
    expect(screen.queryByRole("button", { name: "Novo contato" })).toBeNull();
    const urls = mock.mock.calls.map(([input]) => String(input));
    expect(urls.some((url) => url.includes("/chamadas/admin/historico"))).toBe(true);
    expect(urls.some((url) => url.includes("/admin/contatos"))).toBe(false);
  });
});
