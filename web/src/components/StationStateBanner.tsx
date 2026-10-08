import { useEffect, useState } from "react";

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

// Cronômetro do hero do posto: só apresenta o tempo desde `data_inicio`
// (já decidido pelo backend), sem somar nem recalcular nada.
function ElapsedTimer({ since: start }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);
  const seconds = Math.max(0, Math.floor((now - new Date(start).getTime()) / 1000));
  const pad = (n: number) => String(n).padStart(2, "0");
  return <time className="station-state__timer" aria-hidden="true">{pad(Math.floor(seconds / 3600))}:{pad(Math.floor(seconds / 60) % 60)}:{pad(seconds % 60)}</time>;
}

/**
 * Faixa persistente do estado físico do posto (OP-02): o operador lê em 1–2 s
 * se a máquina está produzindo, parada ou em setup, sem depender da última
 * mensagem de ação.
 */
export function StationStateBanner({ state, semOp = false, timer = false }: { state?: StationState | null; semOp?: boolean; timer?: boolean }) {
  const category = String(state?.categoria ?? "");
  // Corte e Destaque trabalham com tarefas e planos, não com OP: fila ali é
  // só "Sem apontamento".
  const known = semOp && category === "fila"
    ? { label: "Sem apontamento", tone: "waiting" }
    : STATES[category] ?? { label: "Sem apontamento", tone: "neutral" };
  const op = String(state?.op ?? "").trim();
  const details = [op ? `OP ${op}` : "", state?.motivo ?? "", since(state?.data_inicio)].filter(Boolean).join(" · ");
  return (
    <div className={`station-state station-state--${known.tone}`} role="status" aria-label="Estado do posto">
      <strong>{known.label}</strong>
      {details ? <span>{details}</span> : null}
      {timer && state?.data_inicio && !Number.isNaN(new Date(state.data_inicio).getTime()) ? <ElapsedTimer since={state.data_inicio} /> : null}
    </div>
  );
}
