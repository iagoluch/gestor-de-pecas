import { useEffect, useState } from "react";
import type { PropsWithChildren, ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { aiApi } from "../api/ai";
import { useOptionalAuth } from "../auth/AuthContext";
import type { ManagementSectionId } from "../config/navigation";
import { sectionById } from "../config/navigation";
import type { FilterField } from "../filters/FilterContext";
import { FilterBar } from "./FilterBar";
import { Notice } from "./Notice";

export function PageFrame({ sectionId, title, subtitle, actions, children, filters = true, period = true, filterFields, staleError }: PropsWithChildren<{
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
  /**
   * Erro de uma atualização que falhou depois de já haver dados na tela.
   * Os dados continuam visíveis; o aviso só sinaliza que podem estar
   * desatualizados até a próxima atualização bem-sucedida.
   */
  staleError?: unknown;
}>) {
  const section = sectionById(sectionId);
  const auth = useOptionalAuth();
  const { pathname } = useLocation();
  // Na própria tela da IA a aba é a atual e a página já consulta o status.
  const aiEnabled = useAiEnabled(sectionId === "home" && pathname !== "/inicio/ia");
  const tabs = section.tabs.filter((tab) =>
    (!tab.adminOnly || auth?.user?.role === "admin") && !(tab.screen === "home-ai" && aiEnabled === false));
  return (
    <div className="page-wrap">
      <nav className="page-tabs" aria-label={section.label}>
        {tabs.map((tab) => (
          <NavLink key={tab.path} to={tab.path} className={({ isActive }) => isActive ? "page-tab page-tab--active" : "page-tab"}>
            {tab.label}
          </NavLink>
        ))}
      </nav>
      <section className="page-panel">
        <header className={filters ? "page-heading" : "page-heading page-heading--standalone"}>
          <div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          {actions}
        </header>
        {filters ? <FilterBar period={period} fields={filterFields} /> : null}
        {staleError ? (
          <Notice tone="stale">
            Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados.
          </Notice>
        ) : null}
        {children}
      </section>
    </div>
  );
}


/**
 * A aba "IA" só aparece quando a função está ligada no backend (IA-02).
 * Enquanto não há resposta, ou se a consulta falhar, a aba fica: a própria
 * tela da IA explica a indisponibilidade.
 */
function useAiEnabled(active: boolean) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    aiApi.status(controller.signal).then((status) => setEnabled(Boolean(status.enabled)), () => undefined);
    return () => controller.abort();
  }, [active]);
  return enabled;
}
