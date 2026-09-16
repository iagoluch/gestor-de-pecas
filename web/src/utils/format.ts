import { internalTermLabel, systemStateLabelOrNull } from "./systemState";

/**
 * Os rótulos de estado vivem na camada central `utils/systemState`. Este módulo
 * apenas reexporta para as telas que já consumiam `availabilityLabel`.
 */
export { availabilityLabel, humanizeSystemState, systemStateSentence } from "./systemState";

export function formatNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "Não disponível";
  return value.toLocaleString("pt-BR", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function normalizeMeasurementToken(token: string) {
  const separator = token.includes(",") ? "," : ".";
  const decimals = token.includes(separator) ? token.split(separator)[1] ?? "" : "";
  if (decimals.length <= 2) return token;
  const numeric = Number(token.replace(",", "."));
  if (!Number.isFinite(numeric)) return token;
  const rounded = Math.round(numeric * 100) / 100;
  if (Math.abs(numeric - rounded) > 1e-7) return token;
  const normalized = rounded.toFixed(2).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  return separator === "," ? normalized.replace(".", ",") : normalized;
}

/** Formata cotas sem alterar o valor persistido nem perder tolerâncias. */
export function formatMeasurement(value: string | number | null | undefined) {
  if (value === null || value === undefined || String(value).trim() === "") return "Não disponível";
  return String(value).replace(/[+-]?\d+(?:[.,]\d+)?/g, normalizeMeasurementToken);
}

export function formatPercent(value: number | null | undefined) {
  return value === null || value === undefined ? "Não disponível" : `${formatNumber(value, 1)}%`;
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "Não disponível";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

export function formatSignedDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "Não disponível";
  const sign = seconds < 0 ? "−" : seconds > 0 ? "+" : "";
  return `${sign}${formatDuration(Math.abs(seconds))}`;
}

export function formatHours(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "Não disponível";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${formatNumber(hours)}h${minutes ? ` ${minutes}m` : ""}`;
  if (minutes > 0) return `${minutes}m`;
  return `${total}s`;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return "Não disponível";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

/**
 * Texto legível para um valor vindo do backend. Estado técnico e identificador
 * interno conhecidos passam pela camada central; o resto é apenas formatado.
 */
export function humanize(value: string | null | undefined) {
  if (!value) return "Não disponível";
  const central = systemStateLabelOrNull(value) ?? internalTermLabel(value);
  if (central) return central;
  return value
    .replaceAll("_", " ")
    .replace(/(^|[\s/-])(\p{L})/gu, (_match, prefix: string, letter: string) => `${prefix}${letter.toLocaleUpperCase("pt-BR")}`);
}

/** Nome líquido do recurso, sem alterar o código/cadastro original. */
export function formatResourceName(value: string | null | undefined) {
  if (!value) return "Não disponível";
  const normalized = value.trim().toLocaleLowerCase("pt-BR");
  return normalized ? `${normalized[0].toLocaleUpperCase("pt-BR")}${normalized.slice(1)}` : "Não disponível";
}
