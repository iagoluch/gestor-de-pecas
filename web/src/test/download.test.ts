import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";

afterEach(() => vi.restoreAllMocks());

function stubFetch(response: Response) {
  vi.stubGlobal("fetch", vi.fn(async () => response));
}

describe("api.download — GE-03", () => {
  it("erro do servidor vira ApiError, sem gerar arquivo", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    stubFetch(new Response(JSON.stringify({ code: "export_failed", message: "Falha ao montar a planilha." }), {
      status: 500, headers: { "content-type": "application/json" },
    }));
    await expect(api.download("/api/v1/reports/gerencial/export.xlsx", "x.xlsx")).rejects.toThrow(ApiError);
    expect(click).not.toHaveBeenCalled();
  });

  it("sucesso baixa com o nome enviado pelo servidor", async () => {
    let name = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { name = this.download; });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    stubFetch(new Response(new Blob(["xlsx"]), {
      status: 200, headers: { "content-disposition": 'attachment; filename="gestor_gerencial_2026-09-24.xlsx"' },
    }));
    await api.download("/api/v1/reports/gerencial/export.xlsx", "x.xlsx");
    expect(name).toBe("gestor_gerencial_2026-09-24.xlsx");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:x");
  });
});
