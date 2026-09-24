import type { ApiErrorPayload } from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string | null;
  readonly details?: unknown;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message);
    this.name = "ApiError";
    this.status = status;
    this.code = payload.code;
    this.requestId = payload.request_id;
    this.details = payload.details;
  }
}

export function apiErrorMessage(reason: unknown) {
  return reason instanceof ApiError ? reason.message : "Não foi possível concluir a operação.";
}

function cookie(name: string): string | undefined {
  return document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = cookie("gestor_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(path, {
    ...init,
    method,
    headers,
    credentials: "include",
  });
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw failure(response.status, body);
  return body as T;
}

function failure(status: number, body: ApiErrorPayload | null) {
  return new ApiError(status, body ?? {
    code: "request_failed",
    message: "Não foi possível concluir a solicitação.",
  });
}

/**
 * Baixa um arquivo gerado pela API. Com `<a download>` direto, um erro do
 * servidor virava um .xlsx contendo o JSON do erro, sem aviso nenhum (GE-03);
 * aqui a falha chega como ApiError e só um 2xx vira arquivo.
 */
async function download(path: string, fallbackName: string) {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    const json = (response.headers.get("content-type") ?? "").includes("application/json");
    throw failure(response.status, json ? await response.json() : null);
  }
  const name = /filename="?([^";]+)"?/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: name });
  link.click();
  URL.revokeObjectURL(url);
}

export const api = {
  get: <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T>(path: string, payload?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: payload === undefined ? undefined : JSON.stringify(payload),
    }),
  delete: (path: string) => request<void>(path, { method: "DELETE" }),
  download,
};
