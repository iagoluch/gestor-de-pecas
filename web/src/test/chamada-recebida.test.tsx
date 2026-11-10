import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChamadaRecebida } from "../components/ChamadaRecebida";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const CHAMADA = {
  id: 5,
  motivo: "Qualidade",
  prioridade: "Urgente",
  comentario: "Dobra fora de medida",
  solicitante_nome: "Carlos Operador",
  criado_em: new Date().toISOString(),
  contexto: { setor: "Dobra", maquina: "DOBRA 1", op: "12345", numero_operacao: "20", produto_descricao: "Suporte lateral" },
};

describe("chamada recebida na tela de quem foi chamado", () => {
  it("mostra o cartão com quem chama, onde e o que fazia", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ items: [CHAMADA] })));
    render(<ChamadaRecebida />);
    await screen.findByText("Carlos Operador está chamando");
    expect(screen.getByText("Qualidade")).toBeInTheDocument();
    expect(screen.getByText("Urgente")).toBeInTheDocument();
    expect(screen.getByText("Dobra · DOBRA 1")).toBeInTheDocument();
    expect(screen.getByText("12345 / Op. 20")).toBeInTheDocument();
    expect(screen.getByText("Suporte lateral")).toBeInTheDocument();
    expect(screen.getByText("Dobra fora de medida")).toBeInTheDocument();
    expect(screen.getByText("Ao vivo")).toBeInTheDocument();
  });

  it("sem chamadas pendentes não mostra nada", async () => {
    const fetchMock = vi.fn(async () => json({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<ChamadaRecebida />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("'Atender' marca a chamada como atendida e o cartão some", async () => {
    let pendente = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/chamadas/5/atender") && init?.method === "POST") {
        pendente = false;
        return json({ ok: true });
      }
      return json({ items: pendente ? [CHAMADA] : [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ChamadaRecebida />);
    fireEvent.click(await screen.findByRole("button", { name: "Atender" }));
    await waitFor(() => expect(screen.queryByText("Carlos Operador está chamando")).toBeNull());
    expect(fetchMock.mock.calls.some(
      ([path, init]) => String(path).includes("/chamadas/5/atender") && (init as RequestInit | undefined)?.method === "POST",
    )).toBe(true);
  });
});
