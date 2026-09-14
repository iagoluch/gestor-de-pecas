import type { ReportedValue } from "../utils/systemState";

/**
 * Contrato da visão gerencial de acompanhamento da Solda.
 *
 * O estado técnico continua vindo do backend (`availability`); a tradução para
 * texto humano é da apresentação. Nenhum campo aqui é calculado no frontend.
 */

export interface WeldingProduct {
  codigo: string | null;
  descricao: string | null;
  quantidade: number | null;
}

export interface WeldingMachine {
  codigo: string | null;
  nome: string | null;
  operacao: string | null;
}

export interface WeldingTemporalBasis {
  value: string | null;
  label: string | null;
  availability: string;
}

export interface WeldingDates {
  emissao: string | null;
  prazo: string | null;
  inicio_planejado: string | null;
  fim_planejado: string | null;
  inicio_real: string | null;
  fim_real: string | null;
  criacao: WeldingTemporalBasis;
  referencia_prazo: WeldingTemporalBasis;
}

export interface WeldingStatus {
  /** `A VENCER`, `ATRASADA`, `FINALIZADA` ou ausente quando não há base de prazo. */
  value: string | null;
  availability: string;
  reason: string;
}

export interface WeldingOrderRow {
  op: string;
  operacao: string | null;
  produto: WeldingProduct;
  maquina: WeldingMachine;
  modelo: ReportedValue;
  estacao: ReportedValue;
  datas: WeldingDates;
  status: WeldingStatus;
}

export interface WeldingStationGroup {
  nome: string | null;
  availability: string;
  op_count: number;
  ops: WeldingOrderRow[];
}

/** Uma linha do pivô MACRO × situação de prazo, já contada pelo backend. */
export interface WeldingMacroRow {
  nome: string | null;
  codigo: string | null;
  availability: string;
  a_vencer: number;
  atrasadas: number;
  finalizadas: number;
  sem_prazo: number;
  total: number;
}

export interface WeldingSummary {
  ops: number;
  linhas: number;
  estacoes: number;
  a_vencer: number;
  atrasadas: number;
  finalizadas: number;
  sem_prazo: number;
  sem_modelo: number;
  sem_estacao: number;
}

export interface WeldingManagementSnapshot {
  setor: string;
  generated_at: string | null;
  availability: string;
  resumo: WeldingSummary;
  macros: WeldingMacroRow[];
  estacoes: WeldingStationGroup[];
  simulation_only: boolean;
}
