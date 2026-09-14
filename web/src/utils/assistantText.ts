import { humanizeSystemStateIn, internalTermLabel, systemStateLabelOrNull } from "./systemState";

/**
 * Apresentação da resposta da IA.
 *
 * O mecanismo da IA (provider, streaming, modelos, consultas, persistência)
 * não muda: só a forma como o texto chega ao usuário. A IA deve falar como um
 * sistema de gestão industrial — nunca como log de backend. Portanto, nesta
 * camada caem: estado técnico cru, chave interna, nome de campo/tabela,
 * consulta SQL e rastro de exceção.
 */

const SQL_FENCE = /```\s*(?:sql|postgres|postgresql)\b[\s\S]*?```/gi;
const SQL_STATEMENT = /\bSELECT\b[\s\S]{0,4000}?\bFROM\b[^\n;]*;?/gi;
const TRACEBACK_BLOCK = /Traceback \(most recent call last\):[\s\S]*?(?=\n[ \t]*\n|$)/gi;
const TRACEBACK_FRAME = /^[ \t]*File ".*?", line \d+.*$/gim;
const EXCEPTION_LINE = /^[ \t]*(?:[A-Za-z_][\w.]*\.)?[A-Z]\w*(?:Error|Exception|Warning)\b[^\n]*$/gm;

/**
 * Anotação interna de origem: `source = management_insights`,
 * `(fonte: eventos_quantidade_producao)`, `tabela: ai_messages`.
 * O identificador precisa ter `_` ou `.` para ser considerado interno — assim
 * "Fonte: apontamento do operador" continua intacto.
 */
const INTERNAL_ANNOTATION =
  /[([]?\s*(?:source|sources|fonte|fontes|tabela|table|campo|field|coluna|column|dataset|view|módulo|modulo|module)\s*[=:]\s*[`"']?[a-z][a-z0-9]*(?:[_.][a-z0-9]+)+[`"']?\s*[)\]]?/gi;

/**
 * `KPI = sem_registros` vira `KPI: Sem registros`. A chave é uma palavra só —
 * assim a frase que vem antes dela não é absorvida na troca.
 */
const KEY_STATE_PAIR = /([\p{L}][\p{L}\p{N}_./-]{0,40})\s*=\s*[`"']?([\p{L}_]+)[`"']?/gu;

const SUPPRESSED_DETAIL = "Detalhe interno não exibido.";

const REPEATED_SUPPRESSION = new RegExp(`(${SUPPRESSED_DETAIL.replace(".", "\\.")})(?:\\s*\\1)+`, "g");

function collapseSeparators(text: string): string {
  return text
    .replace(REPEATED_SUPPRESSION, "$1")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/\(\s*\)|\[\s*\]/g, "")
    .replace(/([•·—-])\s*(?=[.,;)\]\n]|$)/g, "")
    .replace(/\s+([.,;:])/g, "$1")
    .replace(/,\s*,/g, ",")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]+$/gm, "");
}

/**
 * Converte um par `chave = estado` em leitura humana, preservando o nome do
 * indicador e trocando o estado técnico pelo texto correspondente.
 */
function humanizeKeyStatePairs(text: string): string {
  return text.replace(KEY_STATE_PAIR, (match, rawKey: string, rawValue: string) => {
    const label = systemStateLabelOrNull(rawValue) ?? internalTermLabel(rawValue);
    if (!label) return match;
    const key = rawKey.trim();
    if (/^(?:availability|disponibilidade|status|estado|state)$/i.test(key)) return label;
    return `${key}: ${label}`;
  });
}

/**
 * Texto da IA pronto para leitura industrial. Não altera o conteúdo analítico:
 * remove ou traduz apenas o que é linguagem de backend.
 */
export function humanizeAssistantText(content: string): string {
  if (!content) return content;
  let text = content;
  text = text.replace(SQL_FENCE, SUPPRESSED_DETAIL);
  text = text.replace(SQL_STATEMENT, SUPPRESSED_DETAIL);
  text = text.replace(TRACEBACK_BLOCK, SUPPRESSED_DETAIL);
  text = text.replace(TRACEBACK_FRAME, "");
  text = text.replace(EXCEPTION_LINE, SUPPRESSED_DETAIL);
  text = text.replace(INTERNAL_ANNOTATION, "");
  text = humanizeKeyStatePairs(text);
  text = humanizeSystemStateIn(text);
  return collapseSeparators(text).trim();
}

/** Nome do relatório em linguagem de gestão, sem o identificador do contrato. */
export function reportTypeLabel(type: unknown): string {
  const known: Record<string, string> = {
    completo: "Relatório completo",
    gerencial: "Relatório gerencial",
    producao: "Produção",
    ops: "Ordens de produção",
    paradas: "Paradas",
    setup: "Setup",
    qualidade: "Qualidade",
    indicadores: "Indicadores",
    recursos: "Recursos",
    setores: "Setores",
    nestings: "Nestings",
    excecoes: "Exceções",
    rastreabilidade: "Rastreabilidade",
    auditoria: "Auditoria",
    perdas: "Perdas",
    dados_analiticos: "Dados analíticos",
  };
  const normalized = String(type ?? "").trim().toLocaleLowerCase("pt-BR");
  if (!normalized) return "Relatório";
  if (known[normalized]) return known[normalized];
  const readable = normalized.replaceAll("_", " ");
  return readable.charAt(0).toLocaleUpperCase("pt-BR") + readable.slice(1);
}

/** Situação de um artefato de relatório, sem expor o estado cru do backend. */
export function artifactStatusLabel(status: unknown): string {
  const known: Record<string, string> = {
    pronto: "Relatório pronto",
    gerando: "Relatório em preparação",
    processando: "Relatório em preparação",
    erro: "Não foi possível concluir este relatório",
    falha: "Não foi possível concluir este relatório",
    expirado: "Relatório expirado",
  };
  const normalized = String(status ?? "").trim().toLocaleLowerCase("pt-BR");
  if (known[normalized]) return known[normalized];
  return systemStateLabelOrNull(normalized) ?? "Situação do relatório em atualização";
}
