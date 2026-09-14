import { SearchInput } from "./SearchInput";

export interface RecordFilterOption {
  value: string;
  label: string;
  count?: number;
}

export interface RecordFilterSelect {
  id: string;
  label: string;
  allLabel: string;
  value: string;
  options: RecordFilterOption[];
  onChange: (value: string) => void;
}

/**
 * Barra de filtros das telas de cadastro (Pausas, Crachás).
 *
 * Combinação simples e previsível: seletores + busca + limpar, com a contagem
 * do recorte ao lado. O recorte é aplicado sobre a lista já carregada, então
 * mudar um filtro não dispara consulta nova.
 */
export function RecordToolbar({
  ariaLabel,
  selects,
  search,
  summary,
  onReset,
  resetDisabled = false,
}: {
  ariaLabel: string;
  selects: RecordFilterSelect[];
  search?: { value: string; onChange: (value: string) => void; placeholder?: string };
  summary?: string;
  onReset: () => void;
  resetDisabled?: boolean;
}) {
  return (
    <div className="record-toolbar" role="search" aria-label={ariaLabel}>
      <div className="record-toolbar__fields">
        {selects.map((select) => (
          <label key={select.id} htmlFor={select.id}>
            {select.label}
            <select id={select.id} value={select.value} onChange={(event) => select.onChange(event.target.value)}>
              <option value="">{select.allLabel}</option>
              {select.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.count === undefined ? option.label : `${option.label} (${option.count})`}
                </option>
              ))}
            </select>
          </label>
        ))}
        {search ? (
          <SearchInput value={search.value} onChange={search.onChange} placeholder={search.placeholder ?? "Buscar"} />
        ) : null}
      </div>
      <div className="record-toolbar__meta">
        {summary ? <span className="record-toolbar__summary">{summary}</span> : null}
        <button type="button" className="record-toolbar__reset" onClick={onReset} disabled={resetDisabled}>
          Limpar filtros
        </button>
      </div>
    </div>
  );
}
