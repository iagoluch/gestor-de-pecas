import { FormEvent, useEffect, useState } from "react";
import { useManagementFilters } from "../filters/FilterContext";
import { localDate, referenceNow, useReferenceClock } from "../system/ReferenceClock";
import { DatePicker } from "./DatePicker";

const MANAGEMENT_SECTORS = [
  "Corte", "Dobra", "Usinagem", "Serra", "Caldeiraria", "Pintura",
  "Solda", "Montagem", "Destaque", "Almoxarifado",
];

export function FilterBar({ period = true }: { period?: boolean } = {}) {
  const context = useManagementFilters();
  const { reference } = useReferenceClock();
  const [draft, setDraft] = useState(context.filters);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => setDraft(context.filters), [context.filters]);

  function apply(event: FormEvent) {
    event.preventDefault();
    context.setFilters(draft);
  }

  function applyPreset(days: number | "month") {
    const end = referenceNow(reference);
    const start = new Date(end);
    if (days === "month") start.setDate(1);
    else start.setDate(start.getDate() - days);
    const next = {
      ...draft,
      startDate: localDate(start),
      endDate: localDate(end),
    };
    setDraft(next);
    context.setFilters(next);
  }

  return (
    <form className={`filter-bar ${expanded ? "filter-bar--expanded" : ""}`} aria-label="Filtros gerenciais" onSubmit={apply}>
      {period ? (
        <>
          <div className="filter-bar__presets" aria-label="Períodos rápidos">
            <button type="button" onClick={() => applyPreset(0)}>Hoje</button>
            <button type="button" onClick={() => applyPreset(1)}>Ontem e hoje</button>
            <button type="button" onClick={() => applyPreset(6)}>7 dias</button>
            <button type="button" onClick={() => applyPreset(29)}>30 dias</button>
            <button type="button" onClick={() => applyPreset("month")}>Este mês</button>
          </div>
          <DatePicker label="Início" value={draft.startDate} onChange={(value) => setDraft({ ...draft, startDate: value })} />
          <DatePicker label="Fim" value={draft.endDate} onChange={(value) => setDraft({ ...draft, endDate: value })} />
        </>
      ) : (
        <p className="filter-bar__scope">Situação do dia corrente</p>
      )}
      <label>Setor<select value={draft.sector} onChange={(event) => setDraft({ ...draft, sector: event.target.value })}>
        <option value="">Todos os setores</option>
        {MANAGEMENT_SECTORS.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
      </select></label>
      <div className="filter-bar__advanced">
        <label>Recurso<input value={draft.resource} onChange={(event) => setDraft({ ...draft, resource: event.target.value })} placeholder="Todos" /></label>
        <label>Turno<input value={draft.shift} onChange={(event) => setDraft({ ...draft, shift: event.target.value })} placeholder="Todos" /></label>
        <label>OP<input value={draft.op} onChange={(event) => setDraft({ ...draft, op: event.target.value })} placeholder="Todas" /></label>
        <label>Operação<input value={draft.operation} onChange={(event) => setDraft({ ...draft, operation: event.target.value })} placeholder="Todas" /></label>
        <label>Produto<input value={draft.product} onChange={(event) => setDraft({ ...draft, product: event.target.value })} placeholder="Todos" /></label>
        <label>Operador<input value={draft.operator} onChange={(event) => setDraft({ ...draft, operator: event.target.value })} placeholder="Todos" /></label>
      </div>
      <button className="filter-bar__toggle" type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "Menos filtros" : "Mais filtros"}</button>
      <button className="filter-bar__reset" type="button" onClick={context.reset}>Limpar</button>
      <button className="filter-bar__apply" type="submit">Aplicar</button>
    </form>
  );
}
