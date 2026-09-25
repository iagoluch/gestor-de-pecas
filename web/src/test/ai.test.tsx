import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const manager = {
  id: 1,
  name: "Gestor IA",
  role: "gestor",
  management_access: true,
  andon_access: true,
  operator_access: false,
};

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function sse(blocks: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const block of blocks) controller.enqueue(encoder.encode(block));
      controller.close();
    },
  }), { headers: { "content-type": "text/event-stream" } });
}

function renderAI(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "gestor_csrf=csrf-teste; path=/";
  return render(
    <MemoryRouter initialEntries={["/inicio/ia"]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

describe("IA Industrial gerencial", () => {
  it("esconde a aba IA da Tela inicial só quando o backend diz que a função está desligada", async () => {
    for (const enabled of [false, true]) {
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes("/auth/session")) return json(manager);
        if (path.endsWith("/ai/status")) return json({ enabled, configured: enabled, available: enabled, model: null });
        return json({ code: "not_found", message: "Não encontrado" }, 404);
      }));
      const view = render(
        <MemoryRouter initialEntries={["/inicio/alertas"]}>
          <AuthProvider><App /></AuthProvider>
        </MemoryRouter>,
      );
      await screen.findByRole("link", { name: "Alertas" });
      await waitFor(() => expect(Boolean(screen.queryByRole("link", { name: "IA" }))).toBe(enabled));
      view.unmount();
    }
  });

  it("exibe estado não configurado sem chave ou segredo no navegador", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.includes("/ai/status")) return json({ enabled: true, configured: false, available: false, model: "openai/gpt-oss-120b" });
      if (path.includes("/ai/conversations")) return json({ items: [], count: 0 });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    expect(await screen.findByText("IA não configurada")).toBeInTheDocument();
    expect(screen.getByText(/configuração segura da IA ainda não foi concluída/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("GROQ_API_KEY");
    expect(document.body.textContent).not.toContain("chave-local");
  });

  it("exibe ações rápidas e entrega o artifact do chat sem expor destino", async () => {
    const conversation = { id: 21, user_id: 1, title: "Relatório", created_at: "2026-08-26T12:00:00", updated_at: "2026-08-26T12:00:00" };
    const artifact = {
      id: "00000000-0000-0000-0000-000000000021",
      name: "gestor_paradas.xlsx",
      type: "paradas",
      period_start: "2026-08-25T00:00:00",
      period_end: "2026-08-26T00:00:00",
      size_bytes: 4096,
      status: "pronto",
      download_url: "/api/v1/reports/artifacts/00000000-0000-0000-0000-000000000021/download",
      telegram_available: true,
      telegram_destination_id: 3,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/21")) return json({
        ...conversation,
        messages: [{
          id: 22,
          conversation_id: 21,
          role: "assistant",
          content: "Relatório concluído.",
          created_at: conversation.created_at,
          metadata: { artifacts: [artifact] },
        }],
      });
      if (path.endsWith(`/reports/artifacts/${artifact.id}/send`) && init?.method === "POST") {
        return json({ id: 1, report_id: artifact.id, destination_id: 3, status: "enviado", attempt: 1 });
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    expect(await screen.findByRole("link", { name: "Baixar Excel" }, { timeout: 5000 })).toHaveAttribute("href", artifact.download_url);
    expect(screen.getByRole("button", { name: "Resumir fábrica" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "O que precisa da minha atenção?" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("-1000000000000");
    fireEvent.click(screen.getByRole("button", { name: "Enviar no Telegram" }));
    expect(await screen.findByText("Enviado ao destino configurado.")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith(`/reports/artifacts/${artifact.id}/send`));
    expect(new Headers(call?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-teste");
    expect(call?.[1]?.body).toBe(JSON.stringify({ destination_id: 3 }));
  });

  it("oculta o envio no Telegram quando o destino não está disponível", async () => {
    const conversation = { id: 31, user_id: 1, title: "Relatório", created_at: "2026-08-26T12:00:00", updated_at: "2026-08-26T12:00:00" };
    const artifact = {
      id: "00000000-0000-0000-0000-000000000031",
      name: "gestor_paradas.xlsx",
      type: "paradas",
      period_start: "2026-08-25T00:00:00",
      period_end: "2026-08-26T00:00:00",
      size_bytes: 4096,
      status: "pronto",
      download_url: "/api/v1/reports/artifacts/00000000-0000-0000-0000-000000000031/download",
      telegram_available: false,
      telegram_destination_id: null,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/31")) return json({
        ...conversation,
        messages: [{
          id: 32,
          conversation_id: 31,
          role: "assistant",
          content: "Relatório concluído.",
          created_at: conversation.created_at,
          metadata: { artifacts: [artifact] },
        }],
      });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    expect(await screen.findByRole("link", { name: "Baixar Excel" }, { timeout: 5000 })).toHaveAttribute("href", artifact.download_url);
    expect(screen.queryByRole("button", { name: "Enviar no Telegram" })).toBeNull();
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/send"))).toBe(false);
  });

  it("cria conversa, envia com CSRF e apresenta a resposta em streaming", async () => {
    const conversation = { id: 7, user_id: 1, title: "Nova conversa", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const assistant = { id: 9, conversation_id: 7, role: "assistant", content: "Fábrica consultada.", model: "openai/gpt-oss-120b", created_at: "2026-08-24T12:01:00", metadata: {} };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations") && init?.method === "POST") return json(conversation, 201);
      if (path.endsWith("/ai/conversations")) return json({ items: [], count: 0 });
      if (path.includes("/messages") && init?.method === "POST") {
        return sse([
          "event: status\ndata: {\"message\":\"Consultando produção…\",\"user_message_id\":8}\n\n",
          "event: delta\ndata: {\"content\":\"Fábrica \"}\n\n",
          "event: delta\ndata: {\"content\":\"consultada.\"}\n\n",
          `event: done\ndata: ${JSON.stringify({ message: assistant, conversation_id: 7, tool_rounds: 1 })}\n\n`,
        ]);
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    fireEvent.click(await screen.findByRole("button", { name: "Nova conversa" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const question = screen.getByLabelText("Pergunta");
    fireEvent.change(question, { target: { value: "Como está a fábrica agora?" } });
    fireEvent.keyDown(question, { key: "Enter", code: "Enter", shiftKey: true });
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/messages"))).toBe(false);
    fireEvent.keyDown(question, { key: "Enter", code: "Enter" });
    expect(await screen.findByText("Fábrica consultada.")).toBeInTheDocument();
    const messageCall = fetchMock.mock.calls.find(([path]) => String(path).includes("/messages"));
    expect(messageCall).toBeTruthy();
    const headers = new Headers(messageCall?.[1]?.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-teste");
    expect(String(messageCall?.[1]?.body)).not.toContain("GROQ_API_KEY");
    expect(screen.getByText(/Enter envia • Shift\+Enter quebra a linha/)).toBeInTheDocument();
  });

  it("renderiza Markdown somente na resposta da IA e ignora HTML arbitrário", async () => {
    const conversation = { id: 11, user_id: 1, title: "Resumo", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const assistantMarkdown = [
      "**Situação controlada.**",
      "",
      "- Primeiro ponto",
      "- Segundo ponto",
      "",
      "| Recurso | Estado |",
      "| --- | --- |",
      "| Laser 1 | Produção |",
      "",
      "Use `OEE` como evidência.",
      "",
      "<script>window.__ai_xss = true</script><img src=x onerror=\"window.__ai_xss=true\">",
    ].join("\n");
    const userText = "**texto comum** <script>window.__user_xss=true</script>";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/11")) return json({
        ...conversation,
        messages: [
          { id: 20, conversation_id: 11, role: "user", content: userText, created_at: conversation.created_at },
          { id: 21, conversation_id: 11, role: "assistant", content: assistantMarkdown, created_at: conversation.created_at },
        ],
      });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    const { container } = renderAI(fetchMock);

    const conclusion = await screen.findByText("Situação controlada.");
    expect(conclusion.tagName).toBe("STRONG");
    expect(screen.getByRole("list")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("OEE").tagName).toBe("CODE");
    const userMessage = screen.getByText(userText).closest("article");
    expect(userMessage?.querySelector(".ai-markdown")).toBeNull();
    expect(userMessage?.querySelector("p")?.textContent).toBe(userText);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img[src='x']")).toBeNull();
    expect((window as unknown as Record<string, unknown>).__ai_xss).toBeUndefined();
    expect((window as unknown as Record<string, unknown>).__user_xss).toBeUndefined();
  });

  it("manté o Markdown progressivo durante o streaming e correto na resposta final", async () => {
    const conversation = { id: 12, user_id: 1, title: "Streaming", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const assistant = { id: 31, conversation_id: 12, role: "assistant", content: "**Análise concluída.**", created_at: conversation.created_at };
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/12")) return json({ ...conversation, messages: [] });
      if (path.includes("/messages") && init?.method === "POST") {
        return new Response(new ReadableStream({
          start(controller) {
            streamController = controller;
            controller.enqueue(encoder.encode("event: delta\ndata: {\"content\":\"**Análise\"}\n\n"));
          },
        }), { headers: { "content-type": "text/event-stream" } });
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    const question = await screen.findByLabelText("Pergunta");
    fireEvent.change(question, { target: { value: "Analise agora" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("**Análise")).toBeInTheDocument();
    expect(screen.getAllByLabelText("Tempo da solicitação")).toHaveLength(1);
    await act(async () => {
      streamController?.enqueue(encoder.encode("event: delta\ndata: {\"content\":\" concluída.**\"}\n\n"));
      streamController?.enqueue(encoder.encode(`event: done\ndata: ${JSON.stringify({ message: assistant, conversation_id: 12, tool_rounds: 1 })}\n\n`));
      streamController?.close();
    });
    expect((await screen.findByText("Análise concluída.")).tagName).toBe("STRONG");
    await waitFor(() => expect(screen.queryByLabelText("Tempo da solicitação")).toBeNull());
  });

  it("bloqueia somente novos envios no cooldown, preserva o texto e explica sem jargão", async () => {
    const conversation = { id: 13, user_id: 1, title: "Fábrica", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const blockedUntil = new Date(Date.now() + 37_000).toISOString();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b", cooldown: { active: false, retry_after_seconds: 0, blocked_until: null } });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/13")) return json({ ...conversation, messages: [{ id: 1, conversation_id: 13, role: "assistant", content: "Histórico preservado.", created_at: conversation.created_at }] });
      if (path.includes("/messages") && init?.method === "POST") return sse([
        `event: error\ndata: ${JSON.stringify({ code: "rate_limit", message: "Limite temporário da IA atingido.", retryable: true, retry_after_seconds: 37, blocked_until: blockedUntil })}\n\n`,
      ]);
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    const question = await screen.findByLabelText("Pergunta");
    fireEvent.change(question, { target: { value: "Como está a fábrica?" } });
    fireEvent.keyDown(question, { key: "Enter", code: "Enter" });

    expect(await screen.findByText("Limite temporário da IA atingido")).toBeInTheDocument();
    expect(question).toBeDisabled();
    expect(question).toHaveValue("Como está a fábrica?");
    expect(screen.getByRole("button", { name: "Enviar" })).toBeDisabled();
    expect(screen.getByText("Histórico preservado.")).toBeInTheDocument();
    expect(screen.getByText(/Nova pergunta disponível em 00:3/)).toBeInTheDocument();
    const messageCalls = () => fetchMock.mock.calls.filter(([path]) => String(path).includes("/messages")).length;
    const callsBefore = messageCalls();
    fireEvent.keyDown(question, { key: "Enter", code: "Enter" });
    expect(messageCalls()).toBe(callsBefore);

    const why = screen.getByRole("button", { name: "Por que isso ocorreu?" });
    fireEvent.click(why);
    const explanation = screen.getByText(/A IA possui um limite de uso em pequenos períodos/);
    expect(explanation).toBeInTheDocument();
    expect(explanation.textContent).not.toMatch(/TPM|HTTP 429|API quota|token bucket|headers/i);
    fireEvent.click(why);
    expect(screen.queryByText(/A IA possui um limite de uso em pequenos períodos/)).not.toBeInTheDocument();
  });

  it("reconstrói o cooldown ao montar e libera pelo status do backend ao final", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const conversation = { id: 14, user_id: 1, title: "Cooldown", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const blockedUntil = new Date(Date.now() + 1_000).toISOString();
    let statusCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) {
        statusCalls += 1;
        return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b", cooldown: statusCalls === 1 ? { active: true, retry_after_seconds: 1, blocked_until: blockedUntil } : { active: false, retry_after_seconds: 0, blocked_until: null } });
      }
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/14")) return json({ ...conversation, messages: [] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    const question = await screen.findByLabelText("Pergunta");
    expect(question).toBeDisabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(1_100); });
    await waitFor(() => expect(question).not.toBeDisabled());
    fireEvent.change(question, { target: { value: "Nova pergunta" } });
    expect(screen.getByRole("button", { name: "Enviar" })).not.toBeDisabled();
    expect(statusCalls).toBeGreaterThanOrEqual(2);
  });

  it("trata consulta grande demais sem contador e orienta pergunta específica", async () => {
    const conversation = { id: 15, user_id: 1, title: "Consulta", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/15")) return json({ ...conversation, messages: [] });
      if (path.includes("/messages") && init?.method === "POST") return sse([
        "event: error\ndata: {\"code\":\"request_token_limit\",\"message\":\"Esta consulta reuniu informações demais para serem analisadas de uma vez.\",\"retryable\":false}\n\n",
      ]);
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    const question = await screen.findByLabelText("Pergunta");
    fireEvent.change(question, { target: { value: "Analise tudo" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText(/Esta consulta reuniu informações demais/)).toBeInTheDocument();
    expect(screen.getByText(/pergunta mais específica/)).toBeInTheDocument();
    expect(question).not.toBeDisabled();
    expect(screen.queryByText(/Nova pergunta disponível em/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Por que isso ocorreu?" }));
    expect(screen.getByText(/Seus dados não foram alterados/)).toBeInTheDocument();
  });

  it("mostra erro controlado e permite tentar novamente", async () => {
    const conversation = { id: 4, user_id: 1, title: "Qualidade", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/4")) return json({ ...conversation, messages: [] });
      if (path.includes("/messages") && init?.method === "POST") {
        return sse(["event: error\ndata: {\"code\":\"groq_timeout\",\"message\":\"A Groq excedeu o tempo máximo.\",\"retryable\":true,\"request_id\":\"req-4\"}\n\n"]);
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    await screen.findByLabelText("Pergunta");
    fireEvent.change(screen.getByLabelText("Pergunta"), { target: { value: "Como está a qualidade?" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("A Groq excedeu o tempo máximo.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tempo da solicitação")).toBeNull();
    expect(screen.getByRole("button", { name: "Tentar novamente" })).toBeInTheDocument();
    expect(screen.getByText("Referência: req-4")).toBeInTheDocument();
  });

  it("exclui a conversa pela lixeira somente após confirmação", async () => {
    const conversation = { id: 4, user_id: 1, title: "Como está a qualidade?", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/4") && init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path.endsWith("/ai/conversations/4")) return json({ ...conversation, messages: [] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);

    const deleteTabButton = await screen.findByRole("button", { name: "Excluir conversa: Como está a qualidade?" });
    expect(deleteTabButton.querySelector("img")).not.toBeNull();
    fireEvent.click(deleteTabButton);
    expect(screen.getByRole("dialog", { name: "Excluir conversa" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);

    fireEvent.click(deleteTabButton);
    fireEvent.click(screen.getByRole("button", { name: "Excluir conversa" }));
    await waitFor(() => expect(screen.getByText("Nenhuma conversa iniciada.")).toBeInTheDocument());
    const deleteCall = fetchMock.mock.calls.find(([, init]) => init?.method === "DELETE");
    expect(deleteCall?.[0]).toBe("/api/v1/ai/conversations/4");
    expect(new Headers(deleteCall?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-teste");
  });

  it("cancela a leitura do stream ao comando do gestor", async () => {
    const conversation = { id: 5, user_id: 1, title: "Paradas", created_at: "2026-08-24T12:00:00", updated_at: "2026-08-24T12:00:00" };
    const encoder = new TextEncoder();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(manager);
      if (path.endsWith("/ai/status")) return json({ enabled: true, configured: true, available: true, model: "openai/gpt-oss-120b" });
      if (path.endsWith("/ai/conversations")) return json({ items: [conversation], count: 1 });
      if (path.endsWith("/ai/conversations/5")) return json({ ...conversation, messages: [] });
      if (path.includes("/messages") && init?.method === "POST") {
        return new Response(new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode("event: status\ndata: {\"message\":\"Consultando produção…\"}\n\n"));
            init.signal?.addEventListener("abort", () => controller.error(new DOMException("Abortado", "AbortError")));
          },
        }), { headers: { "content-type": "text/event-stream" } });
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    renderAI(fetchMock);
    await screen.findByLabelText("Pergunta");
    fireEvent.change(screen.getByLabelText("Pergunta"), { target: { value: "Quais são as paradas?" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    expect(await screen.findByText("Consulta cancelada.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Tempo da solicitação")).toBeNull();
  });
});
