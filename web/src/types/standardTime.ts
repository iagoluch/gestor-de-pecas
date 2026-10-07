/** Contrato de `/api/v1/management/standard-times` (só engenharia de manufatura e admin). */

export type StandardTimeSource = "protheus" | "manual" | "estimado";

export interface StandardTimeRow {
  produto_codigo: string;
  numero_operacao: string;
  codigo_recurso: string;
  tipo_setor?: string | null;
  produto_descricao?: string | null;
  descricao_operacao?: string | null;
  tempo_protheus_segundos: number | null;
  tempo_manual_segundos: number | null;
  manual_observacao?: string | null;
  manual_alterado_por?: string | null;
  manual_alterado_em?: string | null;
  /** Instante (ISO; "YYYY-MM-DD" em backend antigo) a partir do qual o manual vale. Não é retroativo. */
  manual_vigente_desde?: string | null;
  tempo_estimado_segundos: number | null;
  estimado_amostras?: number | null;
  estimado_calculado_em?: string | null;
  estimado_janela_inicio?: string | null;
  estimado_janela_fim?: string | null;
  /** Instante (ISO; "YYYY-MM-DD" em backend antigo) a partir do qual o estimado vale. Não é retroativo. */
  estimado_vigente_desde?: string | null;
  /**
   * Linhas do catálogo desta chave com tempo no Protheus / total de linhas.
   * Chave mista (0 < com_protheus < total): o manual só cobre as linhas sem Protheus.
   */
  linhas_com_protheus?: number | null;
  linhas_total?: number | null;
  /** Fonte que vale hoje; `null` = sem padrão. */
  fonte_efetiva: StandardTimeSource | null;
}

export interface StandardTimeListResponse {
  items: StandardTimeRow[];
  total: number;
  sem_produto: number;
  limit: number;
  offset: number;
  somente_sem_padrao: boolean;
}

export interface StandardTimeHistoryEntry {
  acao: string;
  segundos_anterior: number | null;
  segundos_novo: number | null;
  observacao?: string | null;
  usuario_nome?: string | null;
  registrado_em: string;
  /** A partir de quando este valor passou a valer (sem retroativo). */
  vigente_desde?: string | null;
}

export interface StandardTimeRecalculateSummary {
  ok: boolean;
  calculado_em?: string | null;
  janela_inicio?: string | null;
  janela_fim?: string | null;
  execucoes_elegiveis: number;
  chaves_avaliadas: number;
  chaves_estimadas: number;
  amostra_minima: number;
}
