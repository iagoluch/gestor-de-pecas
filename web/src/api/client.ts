import type { ApiErrorPayload } from "../types/api";
import type { DirectorCosts, DirectorPanel, DirectorPeriodName, DirectorSheet } from "../types/director";

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

/** Disparado quando a API responde 401 fora do login (sessão expirada ou encerrada). */
export const SESSION_EXPIRED_EVENT = "gestor:session-expired";

const ACTING_KEY = "gestor:acting-sector";
let actingSector: string | null = null;
try {
  actingSector = sessionStorage.getItem(ACTING_KEY);
} catch {
  /* sem storage: o modo vale só até recarregar */
}

/** Admin/desenvolvedor apontando "como" um setor: toda chamada leva o cabeçalho até sair do modo. */
export function setActingSector(level: string | null) {
  actingSector = level;
  try {
    if (level) sessionStorage.setItem(ACTING_KEY, level);
    else sessionStorage.removeItem(ACTING_KEY);
  } catch {
    /* ignora */
  }
}

/** Sai do modo setor e recarrega o app na aba: sessão e rota voltam juntas, sem passar por telas do outro perfil. */
export function leaveActingSector() {
  setActingSector(null);
  window.location.assign("/inicio/apontamento-por-setor");
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
  if (actingSector) headers.set("X-Acting-Sector", actingSector);
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
  if (response.status === 401 && !path.startsWith("/api/v1/auth/login") && !path.startsWith("/api/v1/dev-observatory")) {
    // Sessão acabou no meio do uso: o AuthProvider volta para o login em vez de
    // cada quadro da tela mostrar "Entre para continuar." sozinho.
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw failure(response.status, body);
  return body as T;
}

function failure(status: number, body: (ApiErrorPayload & { detail?: Partial<ApiErrorPayload> }) | null) {
  // Recusa de regra no formato FastAPI cru: {"detail": {"code", "message"}}.
  const detail = body?.detail;
  if (!body?.message && detail && typeof detail === "object" && detail.message) {
    return new ApiError(status, { code: detail.code ?? "request_failed", message: detail.message });
  }
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
  put: <T>(path: string, payload?: unknown) =>
    request<T>(path, {
      method: "PUT",
      body: payload === undefined ? undefined : JSON.stringify(payload),
    }),
  delete: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
  download,
};

// Aba Diretoria (só diretoria/admin; a API recusa os demais níveis).
const DIRECTOR_BASE = "/api/v1/diretoria";

/** Rotas de leitura da Diretoria, para `useApiQuery` (carregamento, erro e atualização ao vivo). */
export const directorPaths = {
  panel: (periodo: DirectorPeriodName) => `${DIRECTOR_BASE}/painel?periodo=${periodo}`,
  sheet: (periodo: DirectorPeriodName, setor = "", recurso = "") => {
    const query = new URLSearchParams({ periodo });
    if (setor) query.set("setor", setor);
    if (recurso) query.set("recurso", recurso);
    return `${DIRECTOR_BASE}/ficha?${query.toString()}`;
  },
  costs: `${DIRECTOR_BASE}/custos`,
  /** Conta aberta de um número da Diretoria (`dir.*`). Só os filtros preenchidos entram na rota. */
  explain: (metric: string, periodo: DirectorPeriodName, filters: { setor?: string; recurso?: string; pessoa?: string; motivo?: string } = {}) => {
    const query = new URLSearchParams({ metric, periodo });
    if (filters.setor) query.set("setor", filters.setor);
    if (filters.recurso) query.set("recurso", filters.recurso);
    if (filters.pessoa) query.set("pessoa", filters.pessoa);
    if (filters.motivo) query.set("motivo", filters.motivo);
    return `${DIRECTOR_BASE}/explicacao?${query.toString()}`;
  },
};

export const getDirectorPanel = (periodo: DirectorPeriodName, signal?: AbortSignal) =>
  api.get<DirectorPanel>(directorPaths.panel(periodo), signal);
export const getDirectorSheet = (periodo: DirectorPeriodName, setor?: string, recurso?: string, signal?: AbortSignal) =>
  api.get<DirectorSheet>(directorPaths.sheet(periodo, setor, recurso), signal);
export const getDirectorCosts = (signal?: AbortSignal) => api.get<DirectorCosts>(directorPaths.costs, signal);
/** Valor da hora em R$ (número JSON, ex.: 12.5). A regra (> 0, até 2 casas) é do servidor. */
export const putResourceRate = (recurso: string, valorHora: number) =>
  api.put<{ ok: boolean }>(`${DIRECTOR_BASE}/custos/recurso/${encodeURIComponent(recurso)}`, { valor_hora: valorHora });
export const putOperatorRate = (operadorId: number, valorHora: number) =>
  api.put<{ ok: boolean }>(`${DIRECTOR_BASE}/custos/pessoa/${operadorId}`, { valor_hora: valorHora });
