import { useEffect, useState } from "react";
import type React from "react";

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

const svg = (children: React.ReactNode, fill = false) => <svg viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke={fill ? "none" : "currentColor"} strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">{children}</svg>;
const CLOCK = svg(<><circle cx="12" cy="12" r="9.5" /><path d="M12 7v5l3 2" /></>);
// Ícones da faixa de estado, os mesmos da maquete.
const STATE_ICONS: Record<string, React.ReactNode> = {
  producing: svg(<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.5-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z" />, true),
  stopped: svg(<><circle cx="12" cy="12" r="9.5" /><path d="M10 8.5v7M14 8.5v7" /></>),
  setup: svg(<><path d="M14.7 6.3a4 4 0 0 0 5.2 5.2l-8.6 8.6a2.1 2.1 0 0 1-3-3z" /><path d="M14.7 6.3 17 4l3 3-2.3 2.3" /></>),
  rework: svg(<><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" /><path d="M3 4v5h5" /></>),
  waiting: CLOCK,
  neutral: CLOCK,
};

function since(value?: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : `desde ${date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

// Cronômetro do hero do posto: só apresenta o tempo desde `data_inicio`
// (já decidido pelo backend), sem somar nem recalcular nada.
export function ElapsedTimer({ since: start }: { since: string }) {
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
export function StationStateBanner({ state, semOp = false, timer = false, opCount = 0, inlineReason = false }: { state?: StationState | null; semOp?: boolean; timer?: boolean; opCount?: number; inlineReason?: boolean }) {
  const category = String(state?.categoria ?? "");
  // Corte e Destaque trabalham com tarefas e planos, não com OP: fila ali é
  // só "Sem apontamento".
  const known = semOp && category === "fila"
    ? { label: "Sem apontamento", tone: "waiting" }
    : STATES[category] ?? { label: "Sem apontamento", tone: "neutral" };
  const op = String(state?.op ?? "").trim();
  // Com várias OPs no posto, citar só uma fazia parecer que todas começaram no
  // mesmo horário; o "desde" e o cronômetro são do posto, o início de cada OP
  // fica no card dela.
  const opText = opCount > 1 ? `${opCount} OPs no posto` : op ? `OP ${op}` : "";
  // Bancada do operador (12/11/2026): o motivo da parada fica ao lado do
  // estado e a linha de detalhes sai, porque OP, início e tempo já aparecem
  // grandes no painel da OP. Fora do turno mantém a linha (não há outro lugar).
  const reason = inlineReason && category === "parada" ? String(state?.motivo ?? "").trim() : "";
  const details = inlineReason && category !== "fora_turno"
    ? ""
    : [opText, state?.motivo ?? "", since(state?.data_inicio)].filter(Boolean).join(" · ");
  const hasTimer = timer && state?.data_inicio && !Number.isNaN(new Date(state.data_inicio).getTime());
  if (inlineReason) {
    // Bancada do operador: desenho da maquete aprovada (12/11/2026).
    return (
      <div className={`station-state station-state--${known.tone} station-state--inline wb2-status s-${known.tone}`} role="status" aria-label="Estado do posto">
        <div className="si" aria-hidden="true">{STATE_ICONS[known.tone] ?? STATE_ICONS.neutral}</div>
        <div className="wb2-status__text">
          <strong className="st">{known.label}{reason ? <span className={`why station-state__reason${reason.length > 22 ? " why--long" : ""}`}>{reason}</span> : null}</strong>
          {details ? <div className="sub">{details}</div> : null}
        </div>
        <div className="tm">{hasTimer ? <><small>Neste estado há</small><b><ElapsedTimer since={state!.data_inicio!} /></b></> : null}</div>
      </div>
    );
  }
  return (
    <div className={`station-state station-state--${known.tone}`} role="status" aria-label="Estado do posto">
      <strong>{known.label}</strong>
      {details ? <span>{details}</span> : null}
      {hasTimer ? <ElapsedTimer since={state!.data_inicio!} /> : null}
    </div>
  );
}
