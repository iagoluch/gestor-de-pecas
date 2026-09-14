import { humanize } from "../utils/format";

function tone(value: string) {
  const normalized = value.toLocaleLowerCase("pt-BR");
  if (["concluído", "concluido", "normal", "ok", "ativa", "produção", "producao"].some((key) => normalized.includes(key))) return "success";
  if (["crítico", "critico", "atrasado", "erro", "parada"].some((key) => normalized.includes(key))) return "danger";
  if (["atenção", "atencao", "finalizado", "setup", "alerta"].some((key) => normalized.includes(key))) return "warning";
  if (["processo", "destaque", "executando"].some((key) => normalized.includes(key))) return "info";
  return "neutral";
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const text = humanize(value);
  return <span className={`status-badge status-badge--${tone(text)}`}>{text}</span>;
}
