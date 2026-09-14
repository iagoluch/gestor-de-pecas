import { createContext, useContext, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { LoadingState } from "../components/DataState";
import { localDate, referenceNow, useReferenceClock } from "../system/ReferenceClock";

export interface ManagementFilters {
  startDate: string;
  endDate: string;
  sector: string;
  resource: string;
  shift: string;
  op: string;
  operation: string;
  product: string;
  operator: string;
}

interface FilterValue {
  filters: ManagementFilters;
  setFilters: (filters: ManagementFilters) => void;
  query: string;
  /**
   * Mesma seleção de setor/recurso/OP, porém sempre ancorada no dia corrente.
   * Telas de situação atual não usam período: elas consultam o valor diário.
   */
  dailyQuery: string;
  reset: () => void;
}

/**
 * Período padrão ancorado no relógio de referência do backend. Em ambiente
 * normal `reference` é `null` e o relógio real do navegador é usado.
 */
export function defaultFilters(reference: Date | null): ManagementFilters {
  const today = localDate(referenceNow(reference));
  return {
    startDate: today,
    endDate: today,
    sector: "",
    resource: "",
    shift: "",
    op: "",
    operation: "",
    product: "",
    operator: "",
  };
}

function toQuery(filters: ManagementFilters) {
  const query = new URLSearchParams();
  query.set("inicio", `${filters.startDate}T00:00:00`);
  query.set("fim", `${filters.endDate}T23:59:59`);
  const values = {
    setor: filters.sector,
    recurso: filters.resource,
    turno: filters.shift,
    op: filters.op,
    operacao: filters.operation,
    produto: filters.product,
    operador: filters.operator,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value.trim()) query.set(key, value.trim());
  });
  return query.toString();
}

const FilterContext = createContext<FilterValue | null>(null);

export function FilterProvider({ children }: PropsWithChildren) {
  const { reference, ready } = useReferenceClock();
  // Nenhuma consulta é montada antes de saber qual relógio vale: um refresh ou
  // deep link com o período do navegador seria recusado pelo backend.
  if (!ready) return <div className="app-loading"><LoadingState label="Carregando referência do sistema…" /></div>;
  return <ResolvedFilterProvider reference={reference}>{children}</ResolvedFilterProvider>;
}

function ResolvedFilterProvider({ reference, children }: PropsWithChildren<{ reference: Date | null }>) {
  const [filters, setFilters] = useState<ManagementFilters>(() => defaultFilters(reference));
  const value = useMemo(() => {
    const today = localDate(referenceNow(reference));
    return {
      filters,
      setFilters,
      query: toQuery(filters),
      dailyQuery: toQuery({ ...filters, startDate: today, endDate: today }),
      reset: () => setFilters(defaultFilters(reference)),
    };
  }, [filters, reference]);
  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

export function useManagementFilters() {
  const value = useContext(FilterContext);
  if (!value) throw new Error("Filtro gerencial fora de FilterProvider.");
  return value;
}
