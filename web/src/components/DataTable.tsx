import type { ReactNode } from "react";
import { EmptyState } from "./DataState";

export interface TableColumn<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  width?: string;
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
  if (!rows.length) return <EmptyState title={emptyTitle} />;
  return (
    <div className="table-scroll data-table-wrap">
      <table className="data-table">
        <thead>
          <tr>{columns.map((column) => <th key={column.key} style={{ width: column.width }}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => <td key={column.key}>{column.render(row)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

