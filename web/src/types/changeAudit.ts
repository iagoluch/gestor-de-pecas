/** Contrato de `GET /api/v1/management/audit` (`backend/api/schemas/change_audit.py`). */

export type ChangeAction = "criar" | "alterar" | "excluir";

export interface ChangeAuditEntry {
  id: number;
  quando: string;
  usuario_id: number | null;
  usuario_nome: string | null;
  entidade: string;
  chave: string;
  acao: ChangeAction;
  antes: Record<string, unknown> | null;
  depois: Record<string, unknown> | null;
}

export interface ChangeAuditResponse {
  items: ChangeAuditEntry[];
  count: number;
}
