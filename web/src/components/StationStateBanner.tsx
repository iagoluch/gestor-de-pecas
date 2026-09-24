export interface StationState {
  categoria?: string;
  motivo?: string;
  op?: string | null;
  data_inicio?: string | null;
}

// Categorias de `eventos_estado_recurso` (mes/domain/industrial.py). A tela só
// rotula o que o backend já decidiu; categoria desconhecida cai no neutro.
const STATES: Record<string, { label: string; tone: string }> = {
  producao: { label: "Produzindo", tone: "producing" },
  parada: { label: "Parado", tone: "stopped" },
  setup: { label: "Setup", tone: "setup" },
  retrabalho: { label: "Retrabalho", tone: "rework" },
  atividade_sem_op: { label: "Atividade sem OP", tone: "neutral" },
  fila: { label: "Aguardando OP", tone: "waiting" },
  fora_turno: { label: "Fora do turno", tone: "neutral" },
  sem_demanda: { label: "Sem demanda", tone: "neutral" },
};

function since(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : `desde ${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

/**
 * Faixa persistente do estado físico do posto (OP-02): o operador lê em 1–2 s
 * se a máquina está produzindo, parada ou em setup, sem depender da última
 * mensagem de ação.
 */
export function StationStateBanner({ state }: { state?: StationState | null }) {
  const known = STATES[String(state?.categoria ?? "")] ?? { label: "Sem apontamento", tone: "neutral" };
  const op = String(state?.op ?? "").trim();
  const details = [op ? `OP ${op}` : "", state?.motivo ?? "", since(state?.data_inicio)].filter(Boolean).join(" · ");
  return (
    <div className={`station-state station-state--${known.tone}`} role="status" aria-label="Estado do posto">
      <strong>{known.label}</strong>
      {details ? <span>{details}</span> : null}
    </div>
  );
}
