import type { PropsWithChildren, ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { ManagementSectionId } from "../config/navigation";
import { sectionById } from "../config/navigation";
import { FilterBar } from "./FilterBar";

export function PageFrame({ sectionId, title, subtitle, actions, children, filters = true, period = true }: PropsWithChildren<{
  sectionId: ManagementSectionId;
  title: string;
  subtitle: string;
  actions?: ReactNode;
  filters?: boolean;
  /** Falso nas telas de situação atual, que consultam apenas o dia corrente. */
  period?: boolean;
}>) {
  const section = sectionById(sectionId);
  return (
    <div className="page-wrap">
      <div className="page-tabs" role="tablist" aria-label={section.label}>
        {section.tabs.map((tab) => (
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
        {filters ? <FilterBar period={period} /> : null}
        {children}
      </section>
    </div>
  );
}

