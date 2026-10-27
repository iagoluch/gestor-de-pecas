/** Contratos de `GET /api/v1/quality/rnc`, `POST/GET /quality/rnc/{id}/decisions` (`backend/api/routers/quality.py`). */

export type RncDecision = "usar_como_esta" | "retrabalhar" | "sucatear" | "quarentena";

export interface RncCurrentDecision {
  decisao: RncDecision;
  justificativa: string;
  decidido_por_nome: string | null;
  quando: string;
}

export interface RncListItem {
  id: number;
  codigo: string;
  motivo: string | null;
  resultado_peca: string | null;
  numero_peca: number | null;
  op: string | null;
  produto: string | null;
  recurso: string | null;
  criada_em: string;
  decisao_vigente: RncCurrentDecision | null;
  aviso: string | null;
}

export interface RncListResponse {
  items: RncListItem[];
  count: number;
}

export interface RncDecisionEntry {
  id: number;
  rnc_id: number;
  decisao: RncDecision;
  justificativa: string;
  decidido_por_id: number | null;
  decidido_por_nome: string | null;
  quando: string;
  vigente: boolean;
  aviso: string | null;
}

export interface RncHistoryResponse {
  rnc: { id: number; codigo: string; resultado_peca: string | null };
  vigente: RncDecisionEntry | null;
  items: RncDecisionEntry[];
}

export interface RncDecisionResponse {
  ok: boolean;
  decisao: RncDecisionEntry;
  resultado_peca: string | null;
  aviso: string | null;
}
