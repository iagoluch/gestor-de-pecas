/** Contrato de `GET /api/v1/quality/spc` (`backend/api/schemas/quality_spc.py`). Somente leitura. */

export interface SpcMetric {
  value: number | null;
  availability: string;
  unit?: string | null;
  reason?: string | null;
}

export interface SpcLimites {
  lcl: number;
  centro: number;
  ucl: number;
}

export interface SpcSinal {
  /** "x" (média / valor individual) ou "dispersao" (amplitude / amplitude móvel). */
  grafico: string;
  /** "fora_dos_limites" ou "sete_do_mesmo_lado". */
  regra: string;
}

export interface SpcPonto {
  indice: number;
  inspecao_id: number | null;
  codigo_op: string | null;
  inicio: string | null;
  fim: string | null;
  n: number;
  media: number;
  amplitude: number | null;
  limites_x: SpcLimites | null;
  limites_dispersao: SpcLimites | null;
  fora_de_controle: SpcSinal[];
}

export interface SpcSerie {
  produto: string;
  cota: { sequencia: number; descricao: string | null; unidade: string };
  padrao_snapshot: string;
  especificacao: { nominal: number; margem: number; lsl: number; usl: number };
  /** "xbar_r" ou "i_mr". */
  tipo_grafico: string;
  n_medidas: number;
  n_subgrupos: number;
  subgrupos_unitarios_descartados: number;
  media: number | null;
  desvio_geral: number | null;
  sigma_dentro: number | null;
  sigma_fonte: string | null;
  suficiente: boolean;
  motivo_insuficiente: string | null;
  motivo_sem_limites?: string | null;
  limites_x: SpcLimites | null;
  limites_dispersao: SpcLimites | null;
  cpk: SpcMetric;
  cpu: number | null;
  cpl: number | null;
  escopo_cpk: string;
  rotulo_cpk: string;
  pontos: SpcPonto[];
}

export interface SpcResponse {
  escopo_cpk: string;
  rotulo_cpk: string;
  amostra_minima: { medidas: number; subgrupos: number };
  ignoradas: { padrao_nao_numerico: number; medida_invalida: number };
  truncado: boolean;
  series: SpcSerie[];
}
