import { api, ApiError } from "./client";
import type { ApiErrorPayload } from "../types/api";
import type { AIConversation, AIConversationDetail, AIStatus, AIStreamEvent } from "../types/ai";

function cookie(name: string): string | undefined {
  return document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

function parseEvent(block: string): AIStreamEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  return { event, data: JSON.parse(data.join("\n")) } as AIStreamEvent;
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let payload: ApiErrorPayload = {
    code: "request_failed",
    message: "Não foi possível concluir a solicitação.",
  };
  try {
    if ((response.headers.get("content-type") ?? "").includes("application/json")) {
      payload = await response.json() as ApiErrorPayload;
    }
  } catch {
    // Mantém a mensagem controlada quando o servidor não entregar JSON válido.
  }
  return new ApiError(response.status, payload);
}

export const aiApi = {
  status: (signal?: AbortSignal) => api.get<AIStatus>("/api/v1/ai/status", signal),
  conversations: (signal?: AbortSignal) => api.get<{ items: AIConversation[]; count: number }>("/api/v1/ai/conversations", signal),
  conversation: (id: number, signal?: AbortSignal) => api.get<AIConversationDetail>(`/api/v1/ai/conversations/${id}`, signal),
  createConversation: (title?: string) => api.post<AIConversation>("/api/v1/ai/conversations", title ? { title } : {}),
  deleteConversation: (id: number) => api.delete(`/api/v1/ai/conversations/${id}`),

  async sendMessage(
    conversationId: number,
    content: string,
    onEvent: (event: AIStreamEvent) => void,
    signal: AbortSignal,
    retry = false,
  ) {
    const headers = new Headers({
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    });
    const csrf = cookie("gestor_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
    const response = await fetch(`/api/v1/ai/conversations/${conversationId}/messages`, {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({ content, retry }),
      signal,
    });
    if (!response.ok) throw await errorFromResponse(response);
    if (!response.body) {
      throw new ApiError(502, { code: "ai_stream_unavailable", message: "O servidor não iniciou o streaming da IA." });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let completed = false;
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = parseEvent(block);
        if (!event) continue;
        onEvent(event);
        if (event.event === "done" || event.event === "error") {
          completed = true;
          await reader.cancel();
          return;
        }
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const event = parseEvent(buffer);
      if (event) {
        onEvent(event);
        if (event.event === "done" || event.event === "error") completed = true;
      }
    }
    if (!completed) {
      throw new ApiError(502, { code: "ai_stream_incomplete", message: "A resposta da IA foi interrompida antes de terminar." });
    }
  },
};
