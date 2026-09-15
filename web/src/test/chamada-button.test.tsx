import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChamadaButton } from "../components/ChamadaButton";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const CONTATOS = [
  { id: 1, nome: "Fulano", funcao: "Líder" },
  { id: 2, nome: "Ciclano", funcao: "Supervisor" },
];

function stubFetch(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/chamadas/motivos")) return json({ items: ["Manutenção", "Qualidade", "Outro"] });
    if (path.includes("/chamadas/contato-padrao-gestao")) {
      return json({ item: overrides.contatoPadrao ?? null });
    }
    if (path.includes("/chamadas/contatos")) return json({ items: CONTATOS });
    if (path.includes("/chamadas") && !path.includes("admin")) {
      return json(overrides.callResponse ?? { ok: true, telegram_enviado: true, item: {} });
    }
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function selecionarFulanoEMotivo(motivo: string) {
  await screen.findByText("Fulano", { exact: false });
  fireEvent.click(screen.getByRole("option", { name: /Fulano/ }));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: motivo } });
  fireEvent.change(screen.getByPlaceholderText("Descreva rapidamente o que está acontecendo…"), {
    target: { value: "Relato do que está acontecendo" },
  });
}

describe("botão de chamada — variante operador (padrão)", () => {
  it("mostra o botão flutuante e abre o formulário ao clicar", async () => {
    stubFetch();
    render(<ChamadaButton />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await screen.findByRole("heading", { name: "Chamar alguém" });
    await screen.findByText("Fulano", { exact: false });
    await screen.findByText("Ciclano", { exact: false });
  });

  it("filtra os contatos pelo termo de busca", async () => {
    const fetchMock = stubFetch();
    render(<ChamadaButton />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    const busca = await screen.findByPlaceholderText("Buscar por nome ou função…");
    fireEvent.change(busca, { target: { value: "cicl" } });
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([path]) => String(path).includes("q=cicl"))).toBe(true);
    });
  });

  it("exige contato, motivo, comentário e crachá antes de permitir o envio", async () => {
    stubFetch();
    render(<ChamadaButton />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await screen.findByText("Fulano", { exact: false });
    expect(screen.getByRole("button", { name: "Chamar" })).toBeDisabled();

    fireEvent.click(screen.getByRole("option", { name: /Fulano/ }));
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Manutenção" } });
    fireEvent.change(screen.getByPlaceholderText("Descreva rapidamente o que está acontecendo…"), {
      target: { value: "Máquina parada" },
    });
    expect(screen.getByRole("button", { name: "Chamar" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Número do crachá"), { target: { value: "0042" } });
    expect(screen.getByRole("button", { name: "Chamar" })).toBeEnabled();
  });

  it("envia o crachá junto da chamada e mostra se o aviso saiu pelo Telegram", async () => {
    const fetchMock = stubFetch({ callResponse: { ok: true, telegram_enviado: true, item: {} } });
    render(<ChamadaButton />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await selecionarFulanoEMotivo("Manutenção");
    fireEvent.change(screen.getByPlaceholderText("Número do crachá"), { target: { value: "0042" } });
    fireEvent.click(screen.getByRole("button", { name: "Chamar" }));
    await screen.findByText("Chamada registrada.");
    expect(screen.getByText("O aviso foi enviado pelo Telegram.")).toBeInTheDocument();

    const chamada = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/chamadas"));
    const body = JSON.parse(String(chamada?.[1]?.body));
    expect(body.solicitante_cracha).toBe("0042");
  });

  it("avisa quando a chamada foi registrada mas o Telegram não pôde ser enviado", async () => {
    stubFetch({ callResponse: { ok: true, telegram_enviado: false, item: {} } });
    render(<ChamadaButton />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await selecionarFulanoEMotivo("Qualidade");
    fireEvent.change(screen.getByPlaceholderText("Número do crachá"), { target: { value: "0042" } });
    fireEvent.click(screen.getByRole("button", { name: "Chamar" }));
    await screen.findByText("Chamada registrada.");
    expect(screen.getByText(/não pôde ser enviado agora/)).toBeInTheDocument();
  });
});

describe("botão de chamada — variante gestão", () => {
  it("pré-seleciona o contato padrão sem exigir busca, mas ainda permite trocar", async () => {
    stubFetch({ contatoPadrao: { id: 1, nome: "Fulano", funcao: "Líder" } });
    render(<ChamadaButton variant="gestao" />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await screen.findByText("Fulano", { exact: false });
    expect(screen.queryByPlaceholderText("Buscar por nome ou função…")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Trocar" }));
    expect(screen.getByPlaceholderText("Buscar por nome ou função…")).toBeInTheDocument();
  });

  it("sem contato padrão cadastrado, abre a busca normalmente", async () => {
    stubFetch({ contatoPadrao: null });
    render(<ChamadaButton variant="gestao" />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await screen.findByPlaceholderText("Buscar por nome ou função…");
  });

  it("pede nome e e-mail em vez de crachá, e exige os dois para liberar o envio", async () => {
    stubFetch();
    render(<ChamadaButton variant="gestao" />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await selecionarFulanoEMotivo("Manutenção");
    expect(screen.queryByPlaceholderText("Número do crachá")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Chamar" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Nome de quem está chamando"), {
      target: { value: "Gestor de Verdade" },
    });
    expect(screen.getByRole("button", { name: "Chamar" })).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("seu.email@empresa.com"), {
      target: { value: "gestor@empresa.com" },
    });
    expect(screen.getByRole("button", { name: "Chamar" })).toBeEnabled();
  });

  it("envia nome e e-mail digitados em vez de crachá", async () => {
    const fetchMock = stubFetch({ callResponse: { ok: true, telegram_enviado: true, item: {} } });
    render(<ChamadaButton variant="gestao" />);
    fireEvent.click(screen.getByRole("button", { name: "Chamar alguém" }));
    await selecionarFulanoEMotivo("Manutenção");
    fireEvent.change(screen.getByPlaceholderText("Nome de quem está chamando"), {
      target: { value: "Gestor de Verdade" },
    });
    fireEvent.change(screen.getByPlaceholderText("seu.email@empresa.com"), {
      target: { value: "gestor@empresa.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Chamar" }));
    await screen.findByText("Chamada registrada.");

    const chamada = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/chamadas"));
    const body = JSON.parse(String(chamada?.[1]?.body));
    expect(body.solicitante_nome_manual).toBe("Gestor de Verdade");
    expect(body.solicitante_email).toBe("gestor@empresa.com");
    expect(body.solicitante_cracha).toBeUndefined();
  });
});
