import type { PropsWithChildren, ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useOptionalAuth } from "../auth/AuthContext";
import type { ManagementSectionId } from "../config/navigation";
import { sectionById } from "../config/navigation";
import { FilterBar } from "./FilterBar";
import type { FilterFieldKey } from "../filters/FilterContext";

export function PageFrame({ sectionId, title, subtitle, actions, children, filters = true, period = true, fields }: PropsWithChildren<{
  sectionId: ManagementSectionId;
  title: string;
  subtitle: string;
  actions?: ReactNode;
  filters?: boolean;
  /** Falso nas telas de situação atual, que consultam apenas o dia corrente. */
  period?: boolean;
  /** Restringe a FilterBar aos campos que essa tela realmente aplica no backend. */
  fields?: FilterFieldKey[];
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
        {filters ? <FilterBar period={period} fields={fields} /> : null}
        {children}
      </section>
    </div>
  );
}

