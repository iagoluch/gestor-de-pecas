import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { SpcPonto, SpcResponse, SpcSerie } from "../types/qualitySpc";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const session = (role: string) => ({ id: 1, name: `Conta ${role}`, role, management_access: true, andon_access: true, operator_access: false });

const limites = (centro: number, largura: number) => ({ lcl: centro - largura, centro, ucl: centro + largura });

const ponto = (indice: number, n: number, media: number, extra: Partial<SpcPonto> = {}): SpcPonto => ({
  indice, inspecao_id: indice, codigo_op: `OP${indice}`, inicio: null, fim: null, n, media, amplitude: 0.2,
  limites_x: limites(10, n === 5 ? 0.3 : 0.5), limites_dispersao: limites(0.2, 0.15), fora_de_controle: [], ...extra,
});

const serie = (extra: Partial<SpcSerie> = {}): SpcSerie => ({
  produto: "PROD-1", cota: { sequencia: 1, descricao: "Largura", unidade: "mm" }, padrao_snapshot: "10 +/- 1",
  especificacao: { nominal: 10, margem: 1, lsl: 9, usl: 11 }, tipo_grafico: "xbar_r",
  n_medidas: 30, n_subgrupos: 6, subgrupos_unitarios_descartados: 0, media: 10, desvio_geral: 0.1,
  sigma_dentro: 0.1, sigma_fonte: "R-barra/d2 (dentro dos subgrupos)", suficiente: true, motivo_insuficiente: null,
  limites_x: null, limites_dispersao: null,
  cpk: { value: 1.45, availability: "ok" }, cpu: 1.5, cpl: 1.45,
  escopo_cpk: "dentro_da_op_lote", rotulo_cpk: "ROTULO-DA-API Cpk dentro da OP/lote.",
  pontos: [ponto(1, 5, 10), ponto(2, 3, 10.9, { fora_de_controle: [{ grafico: "x", regra: "fora_dos_limites" }] }), ponto(3, 5, 10.1)],
  ...extra,
});

const resposta = (series: SpcSerie[], extra: Partial<SpcResponse> = {}): SpcResponse => ({
  escopo_cpk: "dentro_da_op_lote", rotulo_cpk: "GLOBAL", amostra_minima: { medidas: 20, subgrupos: 5 },
  ignoradas: { padrao_nao_numerico: 0, medida_invalida: 0 }, truncado: false, series, ...extra,
});

function stub(role: string, spc: () => Response) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(session(role));
    if (path.includes("/quality/spc")) return spc();
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderAt(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

afterEach(() => vi.restoreAllMocks());

describe("Qualidade — SPC (somente leitura)", () => {
  it("mostra o rótulo do Cpk exatamente como a API devolveu, por série", async () => {
    stub("qualidade", () => json(resposta([
      serie(),
      serie({ cota: { sequencia: 2, descricao: null, unidade: "mm" }, tipo_grafico: "i_mr", rotulo_cpk: "OUTRO-ROTULO-INDIVIDUAL" }),
    ])));
    renderAt("/qualidade/spc");
    const rotulos = await screen.findAllByTestId("spc-rotulo-cpk");
    expect(rotulos.map((item) => item.textContent)).toEqual(["ROTULO-DA-API Cpk dentro da OP/lote.", "OUTRO-ROTULO-INDIVIDUAL"]);
    expect(screen.getAllByTestId("spc-cpk")[0]).toHaveTextContent("1,45");
    expect(screen.getAllByTestId("spc-amostra-minima")[0]).toHaveTextContent("20 medidas e 5 subgrupos");
  });

  it("desenha o limite por ponto (escalonado) e marca o ponto com sinal", async () => {
    stub("admin", () => json(resposta([serie()])));
    const { container } = renderAt("/qualidade/spc");
    await screen.findByTestId("spc-cpk");
    const ucl = container.querySelector('path[data-limit="ucl"]')!.getAttribute("d")!;
    // 3 pontos = 3 degraus; alturas diferentes entre n=5 e n=3 (não é uma reta única).
    expect((ucl.match(/M|L/g) ?? []).length).toBe(6);
    const alturas = new Set([...ucl.matchAll(/[ML][\d.]+ ([\d.]+)/g)].map((m) => m[1]));
    expect(alturas.size).toBe(2);
    expect(container.querySelectorAll(".spc-chart__dot--outside")).toHaveLength(1);
    expect(screen.getByTestId("spc-sinais")).toHaveTextContent("1 ponto(s) com sinal");
  });

  it("série insuficiente mostra o aviso da API e o motivo do Cpk, sem limites", async () => {
    const motivo = "Amostra insuficiente: 8 medidas em 2 subgrupos (mínimo 20 medidas e 5 subgrupos).";
    stub("qualidade", () => json(resposta([serie({
      suficiente: false, motivo_insuficiente: motivo, cpk: { value: null, availability: "dados_insuficientes", reason: motivo },
      cpu: null, cpl: null, pontos: [ponto(1, 4, 10, { limites_x: null, limites_dispersao: null })],
    })])));
    const { container } = renderAt("/qualidade/spc");
    expect((await screen.findAllByText(motivo)).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("spc-cpk")).toHaveTextContent(motivo);
    expect(container.querySelector('path[data-limit="ucl"]')).toBeNull();
  });

  it("sem séries mostra 'Sem medições suficientes'", async () => {
    stub("qualidade", () => json(resposta([])));
    renderAt("/qualidade/spc");
    expect(await screen.findByText("Sem medições suficientes")).toBeInTheDocument();
  });

  it("403 da API vira mensagem clara e sem botão de tentar de novo", async () => {
    stub("qualidade", () => json({ code: "quality_templates_access_denied", message: "x" }, 403));
    renderAt("/qualidade/spc");
    expect(await screen.findByText(/Só a Qualidade e a administração usam esta tela/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tentar novamente" })).not.toBeInTheDocument();
  });

  it("gestor comum não vê a aba e, pela URL direta, a API nem é chamada", async () => {
    const mock = stub("gestor", () => json(resposta([])));
    renderAt("/qualidade/spc");
    expect(await screen.findByText("Acesso restrito à Qualidade")).toBeInTheDocument();
    expect(mock.mock.calls.some(([path]) => String(path).includes("/quality/spc"))).toBe(false);
  });

  it("a aba SPC aparece na seção Qualidade", async () => {
    stub("qualidade", () => json(resposta([])));
    renderAt("/qualidade/cotas");
    const nav = await screen.findByRole("navigation", { name: "Qualidade" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "SPC" })).toHaveAttribute("href", "/qualidade/spc"));
  });
});
