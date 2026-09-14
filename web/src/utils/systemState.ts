import type { Availability } from "../types/api";

/**
 * Camada central de apresentação dos estados internos do sistema.
 *
 * O backend continua sendo a autoridade e continua expondo o estado técnico
 * (`sem_registros`, `dados_insuficientes`, `nao_configurado`, `parcial`…).
 * Nenhuma tela mostra esse identificador: a tradução para linguagem humana
 * acontece somente aqui, e as telas consomem esta camada.
 *
 * Fluxo: backend (estado técnico) → esta camada → texto humano.
 */

export type SystemStateKey =
  | "disponivel"
  | "parcial"
  | "nao_configurado"
  | "dados_insuficientes"
  | "sem_registros"
  | "nao_aplicavel"
  | "inconsistente"
  | "desconhecido";

interface SystemStateText {
  /** Texto curto, para valor de card, célula de tabela e selo. */
  label: string;
  /** Frase completa, para estado vazio, detalhe e tooltip. */
  sentence: string;
}

const SYSTEM_STATES: Record<SystemStateKey, SystemStateText> = {
  disponivel: {
    label: "Disponível",
    sentence: "Dados disponíveis para o período.",
  },
  parcial: {
    label: "Parcial",
    sentence: "Dados parciais disponíveis para o período.",
  },
  nao_configurado: {
    label: "Não configurado",
    sentence: "Este indicador ainda não foi configurado.",
  },
  dados_insuficientes: {
    label: "Dados insuficientes",
    sentence: "Ainda não há dados suficientes para este indicador.",
  },
  sem_registros: {
    label: "Sem registros",
    sentence: "Nenhum registro encontrado para o período.",
  },
  nao_aplicavel: {
    label: "Não aplicável",
    sentence: "Este indicador não se aplica ao período selecionado.",
  },
  inconsistente: {
    label: "Inconsistente",
    sentence: "Os registros do período estão inconsistentes e precisam de conferência.",
  },
  desconhecido: {
    label: "Não identificado",
    sentence: "Não foi possível identificar esta informação com os registros do período.",
  },
};

/** Grafias equivalentes recebidas do backend, de exportações e de terceiros. */
const STATE_ALIASES: Record<string, SystemStateKey> = {
  available: "disponivel",
  disponivel: "disponivel",
  partial: "parcial",
  parcial: "parcial",
  partial_data: "parcial",
  dados_parciais: "parcial",
  not_configured: "nao_configurado",
  unconfigured: "nao_configurado",
  nao_configurado: "nao_configurado",
  nao_configurada: "nao_configurado",
  sem_configuracao: "nao_configurado",
  insufficient_data: "dados_insuficientes",
  dados_insuficientes: "dados_insuficientes",
  no_records: "sem_registros",
  no_data: "sem_registros",
  sem_registros: "sem_registros",
  sem_registro: "sem_registros",
  not_applicable: "nao_aplicavel",
  nao_aplicavel: "nao_aplicavel",
  inconsistent: "inconsistente",
  inconsistente: "inconsistente",
  unknown: "desconhecido",
  desconhecido: "desconhecido",
  desconhecida: "desconhecido",
};

/**
 * Identificadores internos que já apareceram na interface (fonte de medição,
 * tabela canônica, módulo de análise). Ficam no backend; na tela viram o nome
 * do que a informação significa para quem opera a fábrica.
 */
const INTERNAL_TERMS: Record<string, string> = {
  timeline_op: "Linha do tempo da OP",
  rateio: "Rateio de tempo",
  tempo_real_operacao: "Tempo real da operação",
  management_insights: "Leitura gerencial",
  eventos_estado_recurso: "Estado físico do recurso",
  eventos_quantidade_producao: "Registros de quantidade produzida",
  eventos_apontamento_operador: "Apontamentos do operador",
  apontamentos_operacionais: "Apontamentos de produção",
  apontamentos_corte: "Apontamentos de corte",
  sessoes_recurso: "Sessões do recurso",
  rateios_tempo_op: "Rateio de tempo por OP",
  ai_conversations: "Histórico de conversas",
  ai_messages: "Mensagens da conversa",
  backend_only: "Calculado pelo sistema",
  // Origem de um cadastro (coluna `fonte`).
  cadastro: "Cadastro",
  gestao: "Gestão",
  importacao: "Importação",
  integracao: "Integração",
};

function normalize(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase("pt-BR")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[\s-]+/g, "_");
}

/** Devolve o estado canônico quando o valor recebido é um estado do sistema. */
export function resolveSystemState(value: unknown): SystemStateKey | null {
  const normalized = normalize(value);
  if (!normalized) return null;
  return STATE_ALIASES[normalized] ?? null;
}

/** Nome humano de um identificador interno conhecido, quando houver. */
export function internalTermLabel(value: unknown): string | null {
  const normalized = normalize(value);
  if (!normalized) return null;
  return INTERNAL_TERMS[normalized] ?? null;
}

export interface HumanizeOptions {
  /** `label` para valores e selos; `sentence` para estados vazios e detalhes. */
  style?: "label" | "sentence";
  fallback?: string;
}

/**
 * Traduz um estado técnico do backend para linguagem humana. Valor fora do
 * dicionário devolve o fallback: nenhuma tela inventa significado.
 */
export function humanizeSystemState(
  value: unknown,
  { style = "label", fallback = "Não disponível" }: HumanizeOptions = {},
): string {
  const state = resolveSystemState(value);
  if (!state) return internalTermLabel(value) ?? fallback;
  return style === "sentence" ? SYSTEM_STATES[state].sentence : SYSTEM_STATES[state].label;
}

/**
 * Valor de contrato que pode não existir: o backend manda o dado real ou o
 * estado técnico da ausência.
 */
export interface ReportedValue {
  value?: string | null;
  availability?: string | null;
}

/**
 * Texto de uma célula que pode estar sem valor.
 *
 * O valor real sempre vence. Na ausência, a coluna informa o que a falta
 * significa para quem lê (ex.: "Modelo não identificado."); sem essa frase, a
 * camada central responde pelo estado técnico. Nenhum componente passa a
 * decidir texto comparando `availability` por conta própria.
 */
export function reportedValueText(
  cell: ReportedValue | null | undefined,
  absenceSentence?: string,
): string {
  const value = typeof cell?.value === "string" ? cell.value.trim() : cell?.value ?? null;
  if (value) return String(value);
  return absenceSentence ?? systemStateSentence(cell?.availability);
}

/** Rótulo curto quando o valor é um estado conhecido; `null` caso contrário. */
export function systemStateLabelOrNull(value: unknown): string | null {
  const state = resolveSystemState(value);
  return state ? SYSTEM_STATES[state].label : null;
}

/** Frase de estado vazio para uma superfície sem dado no filtro atual. */
export function systemStateSentence(value: unknown, fallback = "Nenhum dado disponível para o filtro atual."): string {
  return humanizeSystemState(value, { style: "sentence", fallback });
}

/** Rótulo curto derivado da camada central; mantido para os cards existentes. */
export const availabilityLabel: Record<Availability, string> = {
  disponivel: SYSTEM_STATES.disponivel.label,
  parcial: SYSTEM_STATES.parcial.label,
  nao_configurado: SYSTEM_STATES.nao_configurado.label,
  dados_insuficientes: SYSTEM_STATES.dados_insuficientes.label,
  sem_registros: SYSTEM_STATES.sem_registros.label,
  nao_aplicavel: SYSTEM_STATES.nao_aplicavel.label,
  inconsistente: SYSTEM_STATES.inconsistente.label,
};

/**
 * Só os identificadores inequivocamente técnicos entram na substituição dentro
 * de texto livre. Palavras que já são português corrente ("parcial",
 * "inconsistente", "rateio") ficam de fora: trocá-las dentro de uma frase
 * deformaria o texto sem ganho de clareza.
 */
const TECHNICAL_TOKENS = [...Object.keys(STATE_ALIASES), ...Object.keys(INTERNAL_TERMS)]
  .filter((token) => token.includes("_"))
  .sort((left, right) => right.length - left.length);

const TOKEN_PATTERN = new RegExp(`\\b(${TECHNICAL_TOKENS.join("|")})\\b`, "gi");

/**
 * Substitui estados técnicos e identificadores internos que apareçam dentro de
 * um texto livre vindo do backend (justificativa, motivo, resposta da IA).
 */
export function humanizeSystemStateIn(text: string): string {
  if (!text) return text;
  return text.replace(TOKEN_PATTERN, (match) => {
    const state = resolveSystemState(match);
    if (state) return SYSTEM_STATES[state].label;
    return internalTermLabel(match) ?? match;
  });
}
