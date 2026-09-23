import { humanize } from "../utils/format";

function matchesAny(normalized: string, keys: string[]) {
  return keys.some((key) => new RegExp(`\\b${key}\\b`, "u").test(normalized));
}

function tone(value: string) {
  const normalized = value.toLocaleLowerCase("pt-BR");
  if (matchesAny(normalized, ["concluído", "concluido", "normal", "ok", "ativa", "produção", "producao", "finalizado"])) return "success";
  if (matchesAny(normalized, ["crítico", "critico", "atrasado", "erro", "parada"])) return "danger";
  if (matchesAny(normalized, ["atenção", "atencao", "setup", "alerta"])) return "warning";
  if (matchesAny(normalized, ["processo", "destaque", "executando"])) return "info";
  return "neutral";
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const text = humanize(value);
  return <span className={`status-badge status-badge--${tone(text)}`}>{text}</span>;
}
