/** Contrato de `/api/v1/management/quality-templates` (só a conta qualidade e o admin). */

export interface QualityTemplateRow {
  produto_codigo: string;
  produto_descricao: string | null;
  revisao: number;
  quantidade_cotas: number;
  atualizado_por: string | null;
  atualizado_em: string | null;
  ativo: boolean;
}

export interface QualityTemplateListResponse {
  items: QualityTemplateRow[];
  total: number;
  limit: number;
  offset: number;
}
