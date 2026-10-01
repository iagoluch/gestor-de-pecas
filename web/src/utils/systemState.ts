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
  // Severidade e situação que o backend expõe em inglês.
  critical: "Crítico",
  error: "Erro",
  warning: "Atenção",
  info: "Informação",
  high: "Alta",
  medium: "Média",
  low: "Baixa",
  pending: "Pendente",
  running: "Em andamento",
  in_progress: "Em andamento",
  paused: "Pausado",
  stopped: "Parado",
  idle: "Ocioso",
  done: "Concluído",
  completed: "Concluído",
  cancelled: "Cancelado",
  canceled: "Cancelado",
  failed: "Falhou",
  success: "Sucesso",
  active: "Ativo",
  inactive: "Inativo",
  open: "Aberto",
  closed: "Fechado",
  // Origem de um cadastro (coluna `fonte`).
  cadastro: "Cadastro",
  gestao: "Gestão",
  importacao: "Importação",
  integracao: "Integração",
};

/**
 * Palavras de identificadores em snake_case que perdem o acento no código
 * (`estacao`, `producao`…). Só entram aqui palavras que nunca são outra coisa.
 */
const SLUG_WORDS: Record<string, string> = {
  acao: "ação", aco: "aço", aluminio: "alumínio", area: "área", cracha: "crachá",
  codigo: "código", conferencia: "conferência", configuracao: "configuração",
  descricao: "descrição", eletrica: "elétrica", estacao: "estação", funcao: "função",
  ginastica: "ginástica", inspecao: "inspeção", integracao: "integração",
  lider: "líder", manutencao: "manutenção", mecanica: "mecânica", mecanico: "mecânico",
  nao: "não", ocorrencia: "ocorrência", operacao: "operação", operacoes: "operações",
  peca: "peça", pecas: "peças", preparacao: "preparação", producao: "produção",
  prototipo: "protótipo", reuniao: "reunião", refeicao: "refeição", robo: "robô",
  servico: "serviço", situacao: "situação", tecnico: "técnico", usuario: "usuário",
  calibracao: "calibração", informacao: "informação", ate: "até", disponivel: "disponível",
  aplicavel: "aplicável", critico: "crítico",
};

/**
 * Nível de acesso da conta (`usuarios.nivel`). Os níveis fixos têm nome próprio;
 * os de operador seguem o padrão `operador_<setor>` e os de Solda por estação
 * (`estacaoNaco`, `estacaoNalu`, `robo1`, `projetos`, `prototipo`) vêm do catálogo.
 */
const ROLE_LABELS: Record<string, string> = {
  admin: "Administrador",
  lider: "Líder",
  supervisor: "Supervisor",
  manufatura: "Manufatura",
  gestor: "Gestor",
  diretoria: "Diretoria",
  andon: "Painel Andon",
  almoxarifado: "Almoxarifado",
  comum: "Operador de Destaque",
  robo1: "Operador Solda Robô 1",
  projetos: "Operador Proj. Ferramentaria",
  prototipo: "Operador Protótipo",
};

/** Texto de um identificador técnico em snake_case, com acento e capitalização. */
export function humanizeSlug(value: string): string {
  const raw = value.trim();
  // `CORTE_LASER` e `CONFORME` (enum em caixa alta) viram texto normal; sigla curta (OEE, OP) fica.
  const shouting = raw === raw.toLocaleUpperCase("pt-BR") && (raw.includes("_") || /^\p{Lu}{4,}$/u.test(raw));
  const base = shouting ? raw.toLocaleLowerCase("pt-BR") : raw;
  const isCode = base.includes("_") || base === base.toLocaleLowerCase("pt-BR");
  return base
    .replaceAll("_", " ")
    .split(/(\s+)/)
    .map((word) => (isCode ? SLUG_WORDS[word.toLocaleLowerCase("pt-BR")] ?? word : word))
    .join("")
    .replace(/(^|[\s/-])(\p{L})/gu, (_match, prefix: string, letter: string) => `${prefix}${letter.toLocaleUpperCase("pt-BR")}`);
}

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

/** Nome humano do nível de acesso de uma conta; `null` quando não é um nível. */
export function roleLabelOrNull(value: unknown): string | null {
  const normalized = normalize(value);
  if (!normalized) return null;
  if (ROLE_LABELS[normalized]) return ROLE_LABELS[normalized];
  const steel = /^estacao_?(\d+)_?aco$/.exec(normalized);
  if (steel) return `Operador Solda Aço — Estação ${steel[1]}`;
  const aluminum = /^estacao_?(\d+)_?alu$/.exec(normalized);
  if (aluminum) return `Operador Solda Alumínio ${aluminum[1]}`;
  const legacyStation = /^operador_solda_estacao_(\d+)$/.exec(normalized);
  if (legacyStation) return `Operador Solda — Estação ${legacyStation[1]}`;
  const sector = /^operador_([a-z0-9_]+)$/.exec(normalized);
  return sector ? `Operador de ${humanizeSlug(sector[1])}` : null;
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
