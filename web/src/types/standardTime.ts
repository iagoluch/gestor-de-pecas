/** Contrato de `/api/v1/management/standard-times` (só engenharia de manufatura e admin). */

/** O tempo manual não existe mais (04/11/2026): só vale o Protheus; o estimado é leitura separada. */
export type StandardTimeSource = "protheus" | "estimado";

/** Rótulo e explicação do tempo padrão oficial ausente (sem tempo no Protheus). Espelha `mes/domain/standard_time.py`. */
export const NO_STANDARD_LABEL = "n/a";
export const NO_PROTHEUS_STANDARD_TEXT =
  "Tempo padrão não cadastrado no Protheus. A engenharia de manufatura ajusta direto no ERP.";

export interface StandardTimeRow {
  produto_codigo: string;
  numero_operacao: string;
  codigo_recurso: string;
  tipo_setor?: string | null;
  produto_descricao?: string | null;
  descricao_operacao?: string | null;
  tempo_protheus_segundos: number | null;
  tempo_estimado_segundos: number | null;
  estimado_amostras?: number | null;
  estimado_calculado_em?: string | null;
  estimado_janela_inicio?: string | null;
  estimado_janela_fim?: string | null;
  /** Instante (ISO; "YYYY-MM-DD" em backend antigo) a partir do qual o estimado vale. Não é retroativo. */
  estimado_vigente_desde?: string | null;
  /**
   * Linhas do catálogo desta chave com tempo no Protheus / total de linhas.
   * Chave mista (0 < com_protheus < total): as linhas sem Protheus ficam "n/a".
   */
  linhas_com_protheus?: number | null;
  linhas_total?: number | null;
  /** Fonte que vale hoje; `null` = "n/a" (sem Protheus e sem estimado). */
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

export interface StandardTimeRecalculateSummary {
  calculado_em?: string | null;
  janela_inicio?: string | null;
  janela_fim?: string | null;
  execucoes_elegiveis: number;
  chaves_avaliadas: number;
  chaves_estimadas: number;
  amostra_minima: number;
}

export interface StandardTimeRecalculateStatus {
  status: "idle" | "running" | "done" | "error";
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  summary?: StandardTimeRecalculateSummary | null;
}
