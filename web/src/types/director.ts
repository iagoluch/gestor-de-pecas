/**
 * Contratos da aba Diretoria. Espelham `backend/api/schemas/director.py`;
 * horas vêm em horas (não segundos) e R$ só existe nestas respostas.
 */

export type DirectorPeriodName = "hoje" | "semana" | "mes";

export interface DirectorPeriod {
  nome: string;
  inicio: string;
  fim: string;
}

/** Mesmo objeto de OEE da Visão Geral (valor, unidade, motivo, disponibilidade). */
export interface DirectorEfficiencyMetric {
  value?: number | null;
  unit?: string | null;
  availability?: string | null;
  reason?: string | null;
  [key: string]: unknown;
}

export interface DirectorCards {
  produzido: number;
  horas_paradas: number;
  custo_parada: number;
  eficiencia_oee: DirectorEfficiencyMetric | number | null;
}

export interface DirectorLoss {
  setor: string | null;
  horas_paradas: number;
  custo: number;
  motivo_principal: string | null;
  custo_completo: boolean;
}

export interface DirectorSectorRank {
  nome: string | null;
  oee: number;
}

export interface DirectorPanel {
  periodo: DirectorPeriod;
  cards: DirectorCards;
  onde_perdemos: DirectorLoss[];
  melhor_setor: DirectorSectorRank | null;
  pior_setor: DirectorSectorRank | null;
  custo_completo: boolean;
  custos_faltando: number;
  aviso: string | null;
}

export interface DirectorStopReason {
  motivo: string;
  horas: number;
}

export interface DirectorPerson {
  nome: string | null;
  horas: number;
  custo: number;
  custo_completo: boolean;
}

export interface DirectorSheet {
  texto: string;
  trabalhou_h: number;
  disponivel_h: number;
  produzido: number;
  custo_trabalho: number;
  parado_h: number;
  custo_parada: number;
  motivo_principal: string | null;
  paradas_por_motivo: DirectorStopReason[];
  sem_demanda_h: number;
  fora_turno_h: number;
  pessoas: DirectorPerson[];
  custo_parada_completo: boolean;
  custos_faltando_parada: number;
  custo_trabalho_completo: boolean;
  custos_faltando_trabalho: number;
  custo_completo: boolean;
  custos_faltando: number;
}

export interface DirectorResourceRate {
  recurso: string;
  setor: string | null;
  valor_hora: number | null;
}

export interface DirectorPersonRate {
  operador_id: number;
  nome: string | null;
  cracha: string | null;
  valor_hora: number | null;
}

export interface DirectorCosts {
  recursos: DirectorResourceRate[];
  pessoas: DirectorPersonRate[];
}
