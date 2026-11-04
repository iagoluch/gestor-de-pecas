import { useId, type ReactNode } from "react";
import type { DashboardCardKey } from "../types/api";

export const DASHBOARD_CARD_COPY: Record<DashboardCardKey, { label: string; description: string }> = {
  producao_boa: { label: "Produção boa", description: "Total de peças boas no período" },
  oee: { label: "OEE", description: "Ineficiência global efetiva" },
  disponibilidade: { label: "Disponibilidade", description: "Tempo efetivo vs. tempo planejado" },
  performance: { label: "Performance", description: "Velocidade real vs. velocidade esperada" },
  ftt: { label: "FTT / Qualidade", description: "Peças boas na primeira tentativa" },
  simulation: { label: "Indicadores de simulação", description: "Planejado, atingimento, utilização, produtividade e AE" },
  planned_vs_actual: { label: "Planejado × realizado", description: "Acumulado do período e resumo" },
  exceptions: { label: "O que precisa de atenção", description: "Exceções operacionais priorizadas" },
  time_composition: { label: "Composição do tempo", description: "Para onde o tempo foi" },
  top_losses: { label: "Maiores perdas", description: "Causas com maior impacto" },
  live_events: { label: "Agora na fábrica", description: "Mudanças de estado dos recursos" },
  sectors_table: { label: "Setores — leitura rápida", description: "Produção, OEE e tempos por setor" },
  top_resources: { label: "Recursos com maior impacto", description: "Ranking por impacto" },
  audit_issues: { label: "Inconsistências de dados", description: "Alertas de auditoria abertos" },
};

type Props = {
  cardKey: DashboardCardKey;
  className?: string;
  hidden: boolean;
  editMode: boolean;
  index: number;
  total: number;
  onToggle: (key: DashboardCardKey) => void;
  onMoveUp: (key: DashboardCardKey) => void;
  onMoveDown: (key: DashboardCardKey) => void;
  onDropCard: (source: DashboardCardKey, target: DashboardCardKey, before: boolean) => void;
  children: ReactNode;
};

/**
 * Bloco da Visão Geral: em modo de edição ganha alça de arraste, botões de
 * ordem (teclado) e controle de visibilidade. Em modo normal não tem nenhuma
 * affordance de edição — os blocos se comportam como sempre, apenas na ordem
 * salva.
 */
export function DraggableDashboardBlock({
  cardKey,
  className,
  hidden,
  editMode,
  index,
  total,
  onToggle,
  onMoveUp,
  onMoveDown,
  onDropCard,
  children,
}: Props) {
  const copy = DASHBOARD_CARD_COPY[cardKey];
  const placeholderId = useId();

  if (hidden && !editMode) return null;

  const blockClass = [
    "home-dashboard-block",
    className,
    hidden ? "home-dashboard-block--hidden" : "",
  ].filter(Boolean).join(" ");

  const dragStart = (event: React.DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData("application/x-dashboard-card", cardKey);
    event.dataTransfer.effectAllowed = "move";
  };

  const allowDrop = (event: React.DragEvent<HTMLElement>) => {
    if (!editMode) return;
    if (!event.dataTransfer.types.includes("application/x-dashboard-card")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  };

  const drop = (event: React.DragEvent<HTMLElement>) => {
    if (!editMode) return;
    const source = event.dataTransfer.getData("application/x-dashboard-card") as DashboardCardKey;
    if (!source || source === cardKey) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const before = rect.width >= rect.height
      ? event.clientX < rect.left + rect.width / 2
      : event.clientY < rect.top + rect.height / 2;
    onDropCard(source, cardKey, before);
  };

  return (
    <section
      className={blockClass}
      data-card-key={cardKey}
      style={{ order: index }}
      onDragOver={allowDrop}
      onDrop={drop}
      aria-label={copy.label}
    >
      {editMode ? (
        <div className="home-dashboard-block__controls">
          <button
            type="button"
            className="home-dashboard-block__handle"
            draggable
            onDragStart={dragStart}
            aria-label={`Arrastar ${copy.label}`}
            title="Arrastar para reposicionar"
          >
            <span aria-hidden="true" className="home-dashboard-block__grip"><i /><i /><i /><i /><i /><i /></span>
          </button>
          <button type="button" className="home-dashboard-block__move" onClick={() => onMoveUp(cardKey)} disabled={index <= 0} aria-label={`Mover ${copy.label} para cima`} title="Mover para cima">↑</button>
          <button type="button" className="home-dashboard-block__move" onClick={() => onMoveDown(cardKey)} disabled={index >= total - 1} aria-label={`Mover ${copy.label} para baixo`} title="Mover para baixo">↓</button>
          <button type="button" className="home-dashboard-block__toggle" onClick={() => onToggle(cardKey)}>
            {hidden ? "Mostrar" : "Ocultar"}
          </button>
        </div>
      ) : null}
      {hidden ? (
        <button
          type="button"
          id={placeholderId}
          className="home-dashboard-block__hidden-placeholder"
          onClick={() => onToggle(cardKey)}
          aria-label={`Mostrar ${copy.label}`}
        >
          <span>Ocultado por você</span>
          <strong>{copy.label}</strong>
        </button>
      ) : (
        <div className="home-dashboard-block__content">
          {children}
        </div>
      )}
    </section>
  );
}
