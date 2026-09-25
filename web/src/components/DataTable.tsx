import { useState, type ReactNode } from "react";
import { EmptyState } from "./DataState";

export interface TableColumn<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  width?: string;
  /** Valor usado para ordenar pela coluna; sem ele o cabeçalho não ordena. */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Mantém a coluna visível durante a rolagem horizontal (use na primeira). */
  sticky?: boolean;
}

type Sort = { key: string; dir: "ascending" | "descending" };

const collator = new Intl.Collator("pt-BR", { numeric: true, sensitivity: "base" });

function compare(a: string | number | null | undefined, b: string | number | null | undefined) {
  // Vazios sempre no fim, em qualquer direção.
  if (a == null || a === "") return b == null || b === "" ? 0 : 1;
  if (b == null || b === "") return -1;
  return typeof a === "number" && typeof b === "number" ? a - b : collator.compare(String(a), String(b));
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  emptyTitle,
}: {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string | number;
  emptyTitle?: string;
}) {
  const [sort, setSort] = useState<Sort | null>(null);
  if (!rows.length) return <EmptyState title={emptyTitle} />;
  const sortColumn = sort ? columns.find((column) => column.key === sort.key) : undefined;
  const indexed = rows.map((row, index) => ({ row, index }));
  if (sort && sortColumn?.sortValue) {
    const value = sortColumn.sortValue;
    const sign = sort.dir === "ascending" ? 1 : -1;
    indexed.sort((a, b) => {
      const va = value(a.row), vb = value(b.row);
      const empty = (v: typeof va) => v == null || v === "";
      if (empty(va) || empty(vb)) return compare(va, vb);
      return sign * compare(va, vb) || a.index - b.index;
    });
  }
  const toggle = (key: string) => setSort((current) =>
    current?.key === key ? { key, dir: current.dir === "ascending" ? "descending" : "ascending" } : { key, dir: "ascending" });
  return (
    <div className="table-scroll data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>{columns.map((column) => (
            <th
              key={column.key}
              style={{ width: column.width }}
              className={column.sticky ? "data-table__sticky" : undefined}
              aria-sort={column.sortValue ? (sort?.key === column.key ? sort.dir : "none") : undefined}
            >
              {column.sortValue ? (
                <button type="button" className="data-table__sort" onClick={() => toggle(column.key)}>
                  {column.label}
                  <span aria-hidden="true" className="data-table__sort-icon">{sort?.key === column.key ? (sort.dir === "ascending" ? "▲" : "▼") : "↕"}</span>
                </button>
              ) : column.label}
            </th>
          ))}</tr>
        </thead>
        <tbody>
          {indexed.map(({ row, index }) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => <td key={column.key} className={column.sticky ? "data-table__sticky" : undefined}>{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
