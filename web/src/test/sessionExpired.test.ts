import { afterEach, describe, expect, it, vi } from "vitest";
import { api, SESSION_EXPIRED_EVENT } from "../api/client";

function respond401() {
  return new Response(JSON.stringify({ code: "authentication_required", message: "Entre para continuar." }), {
    status: 401,
    headers: { "content-type": "application/json" },
  });
}

describe("sessão expirada", () => {
  afterEach(() => vi.restoreAllMocks());

  it("401 numa tela avisa o AuthProvider para voltar ao login", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(respond401());
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);
    await expect(api.get("/api/v1/operator/history")).rejects.toMatchObject({ status: 401 });
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
    expect(listener).toHaveBeenCalledOnce();
  });

  it("senha errada no login não é sessão expirada", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(respond401());
    const listener = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, listener);
    await expect(api.post("/api/v1/auth/login", { username: "x", password: "y" })).rejects.toMatchObject({ status: 401 });
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
    expect(listener).not.toHaveBeenCalled();
  });
});
