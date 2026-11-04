import { useId, type CSSProperties, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import type { DashboardCardKey, DashboardCardSize } from "../types/api";
import { DASHBOARD_CARD_COPY, DASHBOARD_CARD_LIMITS, DASHBOARD_GRID_COLUMNS, DASHBOARD_ROW_HEIGHT, MAX_CARD_COLS, MAX_CARD_ROWS } from "../utils/dashboardCards";

export { DASHBOARD_CARD_COPY };

type Props = {
  cardKey: DashboardCardKey;
  hidden: boolean;
  editMode: boolean;
  index: number;
  total: number;
  size: DashboardCardSize;
  previewSize?: DashboardCardSize | null;
  dragging: boolean;
  dragSource: DashboardCardKey | null;
  canShow: boolean;
  onToggle: (key: DashboardCardKey) => void;
  onMoveUp: (key: DashboardCardKey) => void;
  onMoveDown: (key: DashboardCardKey) => void;
  onDragStartCard: (key: DashboardCardKey) => void;
  onDragEndCard: () => void;
  onHoverCard: (source: DashboardCardKey, target: DashboardCardKey) => void;
  onDropCard: () => void;
  onPreviewSize: (key: DashboardCardKey, size: DashboardCardSize | null) => void;
  onResizeCard: (key: DashboardCardKey, cols: number, rows: number) => void;
  children: ReactNode;
};

type ResizeAxis = "cols" | "rows" | "both";

/**
 * Bloco da Visão Geral: em modo de edição ganha alça de arraste (com prévia
 * viva da posição), botões de ordem por teclado, controle de visibilidade e
 * alças de redimensionamento. Em modo normal não tem nenhuma affordance de
 * edição — os blocos se comportam como sempre, na ordem e no tamanho salvos.
 */
export function DraggableDashboardBlock({
  cardKey,
  hidden,
  editMode,
  index,
  total,
  size,
  previewSize,
  dragging,
  dragSource,
  canShow,
  onToggle,
  onMoveUp,
  onMoveDown,
  onDragStartCard,
  onDragEndCard,
  onHoverCard,
  onDropCard,
  onPreviewSize,
  onResizeCard,
  children,
}: Props) {
  const copy = DASHBOARD_CARD_COPY[cardKey];
  const placeholderId = useId();
  const activeSize = previewSize ?? size;
  const limits = DASHBOARD_CARD_LIMITS[cardKey];

  if (hidden && !editMode) return null;

  const blockClass = [
    "home-dashboard-block",
    hidden ? "home-dashboard-block--hidden" : "",
    dragging ? "home-dashboard-block--dragging" : "",
    previewSize ? "home-dashboard-block--resizing" : "",
  ].filter(Boolean).join(" ");

  const dragStart = (event: React.DragEvent<HTMLButtonElement>) => {
    event.dataTransfer.setData("application/x-dashboard-card", cardKey);
    event.dataTransfer.effectAllowed = "move";
    const block = event.currentTarget.closest<HTMLElement>("[data-card-key]");
    if (block && typeof event.dataTransfer.setDragImage === "function") {
      const rect = block.getBoundingClientRect();
      event.dataTransfer.setDragImage(block, event.clientX - rect.left, event.clientY - rect.top);
    }
    onDragStartCard(cardKey);
  };

  const allowDrop = (event: React.DragEvent<HTMLElement>) => {
    if (!editMode || !dragSource) return;
    if (!event.dataTransfer.types.includes("application/x-dashboard-card")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    if (dragSource !== cardKey) onHoverCard(dragSource, cardKey);
  };

  const drop = (event: React.DragEvent<HTMLElement>) => {
    if (!editMode || !dragSource) return;
    event.preventDefault();
    onDropCard();
  };

  const startResize = (axis: ResizeAxis) => (event: ReactPointerEvent<HTMLSpanElement>) => {
    if (!editMode || hidden) return;
    const handle = event.currentTarget;
    const block = handle.closest<HTMLElement>("[data-card-key]");
    const grid = block?.parentElement;
    if (!block || !grid) return;
    event.preventDefault();
    event.stopPropagation();

    const computed = getComputedStyle(grid);
    const gap = Number.parseFloat(computed.columnGap) || 16;
    const columns = computed.gridTemplateColumns.split(" ").filter(Boolean).length || DASHBOARD_GRID_COLUMNS;
    const gridWidth = grid.getBoundingClientRect().width;
    const columnWidth = (gridWidth - gap * (columns - 1)) / columns;
    const rowHeight = Number.parseFloat(computed.getPropertyValue("--dashboard-row-height")) || DASHBOARD_ROW_HEIGHT;
    const startX = event.clientX;
    const startY = event.clientY;
    const startCols = activeSize.cols;
    const startRows = activeSize.rows;
    let latest = { cols: startCols, rows: startRows };

    const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
    const onMove = (moveEvent: PointerEvent) => {
      const cols = axis === "rows"
        ? startCols
        : clamp(startCols + Math.round((moveEvent.clientX - startX) / (columnWidth + gap)), limits.minCols, MAX_CARD_COLS);
      const rows = axis === "cols"
        ? startRows
        : clamp(startRows + Math.round((moveEvent.clientY - startY) / (rowHeight + gap)), limits.minRows, MAX_CARD_ROWS);
      if (cols === latest.cols && rows === latest.rows) return;
      latest = { cols, rows };
      onPreviewSize(cardKey, latest);
    };
    const finish = () => {
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      onPreviewSize(cardKey, null);
      onResizeCard(cardKey, latest.cols, latest.rows);
    };

    handle.setPointerCapture?.(event.pointerId);
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  };

  const resizeByKeyboard = (event: React.KeyboardEvent<HTMLSpanElement>) => {
    const deltas: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const delta = deltas[event.key];
    if (!delta) return;
    event.preventDefault();
    onResizeCard(cardKey, activeSize.cols + delta[0], activeSize.rows + delta[1]);
  };

  return (
    <section
      className={blockClass}
      data-card-key={cardKey}
      data-cols={activeSize.cols}
      style={{ order: index, "--card-cols": activeSize.cols, "--card-rows": activeSize.rows } as CSSProperties}
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
            onDragEnd={onDragEndCard}
            aria-label={`Arrastar ${copy.label}`}
            title="Arrastar para reposicionar"
          >
            <span aria-hidden="true" className="home-dashboard-block__grip"><i /><i /><i /><i /><i /><i /></span>
          </button>
          <button type="button" className="home-dashboard-block__move" onClick={() => onMoveUp(cardKey)} disabled={index <= 0} aria-label={`Mover ${copy.label} para cima`} title="Mover para cima">↑</button>
          <button type="button" className="home-dashboard-block__move" onClick={() => onMoveDown(cardKey)} disabled={index >= total - 1} aria-label={`Mover ${copy.label} para baixo`} title="Mover para baixo">↓</button>
          <button
            type="button"
            className="home-dashboard-block__toggle"
            onClick={() => onToggle(cardKey)}
            title={hidden && !canShow ? "Limite de blocos visíveis atingido" : undefined}
          >
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
          title={!canShow ? "Limite de blocos visíveis atingido" : undefined}
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
      {editMode && !hidden ? (
        <>
          <span
            className="home-dashboard-block__resize home-dashboard-block__resize--right"
            role="separator"
            aria-label={`Redimensionar largura de ${copy.label}`}
            onPointerDown={startResize("cols")}
          />
          <span
            className="home-dashboard-block__resize home-dashboard-block__resize--bottom"
            role="separator"
            aria-label={`Redimensionar altura de ${copy.label}`}
            onPointerDown={startResize("rows")}
          />
          <span
            className="home-dashboard-block__resize home-dashboard-block__resize--corner"
            role="separator"
            tabIndex={0}
            aria-label={`Redimensionar ${copy.label} (setas do teclado)`}
            title="Arraste ou use as setas para redimensionar"
            onPointerDown={startResize("both")}
            onKeyDown={resizeByKeyboard}
          />
        </>
      ) : null}
    </section>
  );
}
