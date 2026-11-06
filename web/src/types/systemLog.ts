/** Contrato de `GET /api/v1/management/system-log` (+ `/summary`), migration 74. */

export type LogLevel = "info" | "aviso" | "erro";

export interface SystemLogEntry {
  id: number;
  quando: string;
  area: string;
  nivel: LogLevel;
  evento: string;
  mensagem: string;
  usuario: string | null;
  request_id: string | null;
  metodo: string | null;
  rota: string | null;
  status_http: number | null;
  duracao_ms: number | null;
  detalhe: Record<string, unknown> | null;
}

export interface SystemLogResponse {
  items: SystemLogEntry[];
  count: number;
}

export interface SystemLogAreaSummary {
  area: string;
  rotulo: string;
  total: number;
  aviso: number;
  erro: number;
}

export interface SystemLogSummaryResponse {
  horas: number;
  areas: SystemLogAreaSummary[];
}
