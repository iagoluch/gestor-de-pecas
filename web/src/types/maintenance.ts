/** Contrato de `/api/v1/maintenance/suggestions` (`backend/api/schemas/maintenance.py`). */

export type MaintenanceSuggestionStatus = "sugerida" | "aceita" | "descartada";

export interface MaintenanceSuggestion {
  id: number;
  recurso: string;
  setor: string | null;
  parada_inicio: string | null;
  parada_fim: string | null;
  parada_segundos: number | null;
  motivo: string | null;
  op: string | null;
  status: MaintenanceSuggestionStatus;
  criada_em: string | null;
  decidido_por_id: number | null;
  decidido_por_nome: string | null;
  decidido_em: string | null;
  nota: string | null;
}

export interface MaintenanceSuggestionsResponse {
  status: MaintenanceSuggestionStatus;
  limit: number;
  count: number;
  items: MaintenanceSuggestion[];
}

export interface MaintenanceDecisionResponse {
  ok: boolean;
  item: MaintenanceSuggestion;
}

/** `details` do 409 `maintenance_suggestion_already_decided`. */
export interface MaintenanceAlreadyDecidedDetails {
  status?: MaintenanceSuggestionStatus | null;
  decidido_por_nome?: string | null;
  decidido_em?: string | null;
}
