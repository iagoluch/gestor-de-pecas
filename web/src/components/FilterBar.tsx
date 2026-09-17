import { FormEvent, useState } from "react";
import { ALL_FILTER_FIELDS, useManagementFilters } from "../filters/FilterContext";
import type { FilterField, ManagementFilters } from "../filters/FilterContext";
import { localDate, referenceNow, useReferenceClock } from "../system/ReferenceClock";
import { DatePicker } from "./DatePicker";

const MANAGEMENT_SECTORS = [
  "Corte", "Dobra", "Usinagem", "Serra", "Caldeiraria", "Pintura",
  "Solda Aço", "Solda Alumínio", "Solda Robô", "Proj. Ferramentaria", "Protótipo",
  "Montagem", "Destaque", "Almoxarifado",
];

const PRESETS: Array<{ label: string; days: number | "month" }> = [
  { label: "Hoje", days: 0 },
  { label: "Ontem e hoje", days: 1 },
  { label: "7 dias", days: 6 },
  { label: "30 dias", days: 29 },
  { label: "Este mês", days: "month" },
];

/** Campos de texto livre da seção "Mais filtros", na ordem de exibição. */
const ADVANCED: Array<{ field: FilterField; label: string; placeholder: string }> = [
  { field: "resource", label: "Recurso", placeholder: "Todos" },
  { field: "op", label: "OP", placeholder: "Todas" },
  { field: "operation", label: "Operação", placeholder: "Todas" },
  { field: "product", label: "Produto", placeholder: "Todos" },
  { field: "operator", label: "Operador", placeholder: "Todos" },
];

function countActive(filters: ManagementFilters, fields: Array<{ field: FilterField }>) {
  return fields.filter((item) => filters[item.field].trim()).length;
}

export function FilterBar({ period = true, fields = ALL_FILTER_FIELDS }: {
  period?: boolean;
  /** Campos que a fonte da tela realmente recorta; os demais não são exibidos. */
  fields?: FilterField[];
} = {}) {
  const context = useManagementFilters();
  const { reference } = useReferenceClock();
  const advanced = ADVANCED.filter((item) => fields.includes(item.field));
  const [draft, setDraft] = useState(context.filters);
  // Um filtro avançado já ativo (ex.: vindo de um drill-down da visão geral)
  // não pode ficar escondido atrás do botão: a seção abre junto com a tela.
  const [expanded, setExpanded] = useState(() => countActive(context.filters, advanced) > 0);
  const [applied, setApplied] = useState(context.filters);

  // O contexto é a fonte da verdade: se outra tela alterou os filtros (ex.:
  // drill-down da visão geral), o rascunho acompanha sem efeito colateral.
  if (applied !== context.filters) {
    setApplied(context.filters);
    setDraft(context.filters);
  }

  const showSector = fields.includes("sector");
  const activeAdvanced = countActive(context.filters, advanced);
  const pending = JSON.stringify(draft) !== JSON.stringify(context.filters);

  function update(patch: Partial<ManagementFilters>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function apply(event: FormEvent) {
    event.preventDefault();
    context.setFilters(draft);
  }

  function clear() {
    setExpanded(false);
    context.reset();
  }

  function applyPreset(days: number | "month") {
    const end = referenceNow(reference);
    const start = new Date(end);
    if (days === "month") start.setDate(1);
    else start.setDate(start.getDate() - days);
    // O preset é um atalho de período: aplica de imediato, já com o que estiver
    // digitado nos demais campos, para não deixar dois estados divergentes.
    context.setFilters({ ...draft, startDate: localDate(start), endDate: localDate(end) });
  }

  return (
    <form className="filter-bar" aria-label="Filtros gerenciais" onSubmit={apply}>
      <div className="filter-bar__row">
        {period ? (
          <>
            <div className="filter-bar__presets" role="group" aria-label="Períodos rápidos">
              {PRESETS.map((preset) => (
                <button key={preset.label} type="button" onClick={() => applyPreset(preset.days)}>{preset.label}</button>
              ))}
            </div>
            <DatePicker label="Início" value={draft.startDate} onChange={(value) => update({ startDate: value })} />
            <DatePicker label="Fim" value={draft.endDate} onChange={(value) => update({ endDate: value })} />
          </>
        ) : (
          <p className="filter-bar__scope">Situação do dia corrente</p>
        )}
        {showSector ? (
          <label>Setor
            <select value={draft.sector} onChange={(event) => update({ sector: event.target.value })}>
              <option value="">Todos os setores</option>
              {MANAGEMENT_SECTORS.map((sector) => <option key={sector} value={sector}>{sector}</option>)}
            </select>
          </label>
        ) : null}
        <div className="filter-bar__actions">
          {advanced.length ? (
            <button
              className="filter-bar__toggle"
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? "Menos filtros" : "Mais filtros"}
              {activeAdvanced ? <span className="filter-bar__badge">{activeAdvanced}</span> : null}
            </button>
          ) : null}
          <button className="filter-bar__reset" type="button" onClick={clear}>Limpar</button>
          <button className="filter-bar__apply" type="submit" data-pending={pending || undefined}>Aplicar</button>
        </div>
      </div>
      {expanded && advanced.length ? (
        <div className="filter-bar__advanced">
          {advanced.map((item) => (
            <label key={item.field}>{item.label}
              <input
                value={draft[item.field]}
                onChange={(event) => update({ [item.field]: event.target.value })}
                placeholder={item.placeholder}
              />
            </label>
          ))}
        </div>
      ) : null}
    </form>
  );
}
