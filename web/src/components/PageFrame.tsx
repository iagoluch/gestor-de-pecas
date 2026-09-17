import type { PropsWithChildren, ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useOptionalAuth } from "../auth/AuthContext";
import type { ManagementSectionId } from "../config/navigation";
import { sectionById } from "../config/navigation";
import type { FilterField } from "../filters/FilterContext";
import { FilterBar } from "./FilterBar";

export function PageFrame({ sectionId, title, subtitle, actions, children, filters = true, period = true, filterFields }: PropsWithChildren<{
  sectionId: ManagementSectionId;
  title: string;
  subtitle: string;
  actions?: ReactNode;
  filters?: boolean;
  /** Falso nas telas de situação atual, que consultam apenas o dia corrente. */
  period?: boolean;
  /**
   * Campos que a fonte da tela realmente recorta. Omitido, a barra mostra
   * todos; telas com fonte restrita (ex.: nestings do Corte) declaram só os
   * campos aplicáveis em vez de exibir um filtro sem efeito.
   */
  filterFields?: FilterField[];
}>) {
  const section = sectionById(sectionId);
  const auth = useOptionalAuth();
  const tabs = section.tabs.filter((tab) => !tab.adminOnly || auth?.user?.role === "admin");
  return (
    <div className="page-wrap">
      <div className="page-tabs" role="tablist" aria-label={section.label}>
        {tabs.map((tab) => (
          <NavLink key={tab.path} to={tab.path} role="tab" className={({ isActive }) => isActive ? "page-tab page-tab--active" : "page-tab"}>
            {tab.label}
          </NavLink>
        ))}
      </div>
      <section className="page-panel">
        <header className="page-heading">
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          {actions}
        </header>
        {filters ? <FilterBar period={period} fields={filterFields} /> : null}
        {children}
      </section>
    </div>
  );
}

