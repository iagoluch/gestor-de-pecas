import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AreaQueuePanel } from "../pages/areas/AreaQueuePanel";

const RECURSOS = { items: [{ resource: "SERRA1", nome: "Serra 1", setor: "Serra" }, { resource: "SERRA2", nome: "Serra 2", setor: "Serra" }] };

function entry(id: number, op: string, extra: Record<string, unknown> = {}) {
  return { entry_id: id, operation_id: id * 10, op, operation: "Corte", product: `PROD-${op}`, description: "", qty: 5, fixada: true, origem_recurso: null, posicao: id, ...extra };
}

const A = entry(1, "OP-A");
const B = entry(2, "OP-B", { origem_recurso: "SERRA2" });

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** Servidor falso: `fila` é o estado devolvido pelo GET; `escrita` responde POST/PUT/DELETE. */
function stub(fila: unknown[], escrita?: (method: string, body: unknown) => Response) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/queue/resources")) return json(RECURSOS);
    if (method === "GET") return json({ resource: "SERRA1", items: fila });
    return escrita!(method, init?.body ? JSON.parse(String(init.body)) : null);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const writes = (mock: ReturnType<typeof stub>) => mock.mock.calls.filter(([, init]) => (init?.method ?? "GET") !== "GET");

afterEach(() => vi.restoreAllMocks());

describe("Fila de prioridades por recurso", () => {
  it("carrega os recursos da área e a fila do primeiro", async () => {
    const mock = stub([A, B]);
    render(<AreaQueuePanel areaId="serra" />);
    const select = await screen.findByLabelText("Recurso");
    expect(screen.getByRole("heading", { name: "Fila de prioridades" })).toBeInTheDocument();
    expect(screen.getByText(/não zera no dia seguinte/)).toBeInTheDocument();
    expect(within(select).getAllByRole("option")).toHaveLength(2);
    expect(await screen.findByText("OP-A")).toBeInTheDocument();
    expect(mock.mock.calls.some(([path]) => String(path) === "/api/v1/areas/serra/queue?resource=SERRA1")).toBe(true);
    expect(screen.getAllByText("Fixada pelo líder")).toHaveLength(2);
    expect(screen.getByText(/Veio de/)).toBeInTheDocument();
  });

  it("adiciona uma OP com POST e mostra a lista devolvida", async () => {
    const mock = stub([], (method, body) => {
      expect(method).toBe("POST");
      expect(body).toEqual({ resource: "SERRA1", op: "OP-A" });
      return json({ resource: "SERRA1", items: [A] });
    });
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("Nenhuma OP na fila deste recurso");
    fireEvent.change(screen.getByLabelText("OP"), { target: { value: " OP-A " } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à fila" }));
    expect(await screen.findByText("PROD-OP-A")).toBeInTheDocument();
    expect(writes(mock)).toHaveLength(1);
    expect(screen.getByLabelText("OP")).toHaveValue("");
  });

  it("sobe e desce com PUT enviando a ordem completa", async () => {
    const mock = stub([A, B], (_method, body) => {
      const ids = (body as { operation_ids: number[] }).operation_ids;
      return json({ resource: "SERRA1", items: ids.map((id) => (id === 10 ? A : B)) });
    });
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("OP-A");
    fireEvent.click(screen.getByRole("button", { name: "Subir OP OP-B" }));
    await waitFor(() => expect(writes(mock)).toHaveLength(1));
    expect(JSON.parse(String(writes(mock)[0][1]?.body))).toEqual({ resource: "SERRA1", operation_ids: [20, 10] });
    expect(writes(mock)[0][1]?.method).toBe("PUT");
    await waitFor(() => expect(screen.getByRole("button", { name: "Subir OP OP-B" })).toBeDisabled());

    fireEvent.click(screen.getByRole("button", { name: "Descer OP OP-B" }));
    await waitFor(() => expect(writes(mock)).toHaveLength(2));
    expect(JSON.parse(String(writes(mock)[1][1]?.body)).operation_ids).toEqual([10, 20]);
  });

  it("remove com DELETE e atualiza a lista", async () => {
    const mock = stub([A, B], (method) => {
      expect(method).toBe("DELETE");
      return json({ resource: "SERRA1", items: [B] });
    });
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("OP-A");
    fireEvent.click(screen.getByRole("button", { name: "Remover OP OP-A da fila" }));
    await waitFor(() => expect(screen.queryByText("OP-A")).not.toBeInTheDocument());
    expect(String(writes(mock)[0][0])).toBe("/api/v1/areas/serra/queue/1?resource=SERRA1");
    expect(screen.getByText("OP-B")).toBeInTheDocument();
  });

  it("mostra a mensagem do servidor num erro 409", async () => {
    stub([A], () => json({ code: "queue_rule", message: "Esta OP já está na fila de outro recurso." }, 409));
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("OP-A");
    fireEvent.change(screen.getByLabelText("OP"), { target: { value: "OP-X" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à fila" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Esta OP já está na fila de outro recurso.");
    expect(screen.getByText("OP-A")).toBeInTheDocument();
  });

  it("recarrega a lista do servidor depois de um erro ao remover", async () => {
    const mock = stub([A, B], () => json({ code: "queue_rule", message: "A OP já saiu da fila." }, 409));
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("OP-A");
    const gets = () => mock.mock.calls.filter(([path, init]) => String(path).includes("?resource=") && (init?.method ?? "GET") === "GET").length;
    const antes = gets();
    fireEvent.click(screen.getByRole("button", { name: "Remover OP OP-A da fila" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A OP já saiu da fila.");
    await waitFor(() => expect(gets()).toBe(antes + 1));
  });

  it("entende o 409 no formato {detail:{code,message}}", async () => {
    stub([A], () => json({ detail: { code: "queue_rule", message: "OP encerrada não entra na fila." } }, 409));
    render(<AreaQueuePanel areaId="serra" />);
    await screen.findByText("OP-A");
    fireEvent.change(screen.getByLabelText("OP"), { target: { value: "OP-X" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar à fila" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("OP encerrada não entra na fila.");
  });

  it("mostra o estado vazio e não deixa adicionar sem OP", async () => {
    stub([]);
    render(<AreaQueuePanel areaId="serra" />);
    expect(await screen.findByText("Nenhuma OP na fila deste recurso")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Adicionar à fila" })).toBeDisabled();
  });
});
