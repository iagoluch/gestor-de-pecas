import type { PropsWithChildren } from "react";
import { leaveActingSector } from "../api/client";
import { useOptionalAuth } from "../auth/AuthContext";
import { ChamadaButton } from "../components/ChamadaButton";
import { ChamadaRecebida } from "../components/ChamadaRecebida";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
import { ThemeToggle } from "../components/ThemeToggle";
import { HelpButton } from "../components/HelpButton";
import { assets } from "../config/assets";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export interface OperatorNavItem {
  key: string;
  label: string;
  icon?: string;
  onSelect: () => void;
}

export function OperatorShell({
  sector,
  resource,
  onBack,
  navigation,
  activeNav,
  title,
  calls = true,
  children,
}: PropsWithChildren<{
  sector: string;
  resource?: string | null;
  onBack?: () => void;
  navigation?: OperatorNavItem[];
  activeNav?: string;
  /** Título da aba/tela quando não é um posto de apontamento. */
  title?: string;
  /** Botão de chamada da liderança; a Manutenção não o usa. */
  calls?: boolean;
}>) {
  const auth = useOptionalAuth();
  const acting = auth?.user?.acting_sector ?? null;
  const items = navigation ?? [];
  const current = activeNav ?? items[0]?.key;
  const hasTabs = items.length > 1;
  const resourceLabel = sector.toLocaleLowerCase().startsWith("solda") ? "Estação" : "Máquina";
  const selectedResource = resource === sector ? resource : <><span>{sector} - </span><span>{resource}</span></>;
  const pageTitle = title ?? (!resource ? `Posto do operador · ${sector}` : resource === sector ? `${resourceLabel} ${resource}` : `${resourceLabel} ${sector} - ${resource}`);
  useDocumentTitle(pageTitle);
  return (
    <div className="operator-shell">
      <header className={`operator-topbar ${resource ? "operator-topbar--with-machine" : ""}`}>
        <h1 className="visually-hidden">{pageTitle}</h1>
        <div className="operator-topbar__brand">
          <img src={assets.logo} alt="Gestor de Peças" />
          <small className="operator-topbar__credit">Powered by Iago Luchtenberg</small>
        </div>
        <div className="operator-topbar__clock"><img src={assets.clock} alt="" /><SystemClock /></div>
        {resource ? (
          onBack ? (
            <button type="button" className="operator-topbar__machine" onClick={onBack} title={`Trocar ${resourceLabel.toLocaleLowerCase()}`}>
              <span>{resourceLabel}</span><strong>{selectedResource}</strong>
            </button>
          ) : (
            <div className="operator-topbar__machine"><span>{resourceLabel}</span><strong>{selectedResource}</strong></div>
          )
        ) : null}
        <div className="operator-topbar__actions">
          <HelpButton manual="operador" />
          <ThemeToggle compact />
          <LogoutButton compact />
        </div>
      </header>
      {hasTabs ? (
        <nav className="operator-tabs" aria-label="Áreas do posto">
          {items.map((item) => {
            const active = item.key === current;
            return (
              <button
                key={item.key}
                type="button"
                className={`operator-tab ${active ? "operator-tab--active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={item.onSelect}
              >
                {item.icon ? <img src={item.icon} alt="" /> : null}<span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      ) : null}
      {acting ? (
        <div className="operator-acting" role="status">
          <span>{`Apontando como ${acting} — feito pela gestão`}</span>
          <button
            type="button"
            className="button"
            onClick={leaveActingSector}
          >
            Sair do modo setor
          </button>
        </div>
      ) : null}
      <main className="operator-main">
        <div className="operator-content">{children}</div>
      </main>
      {calls && !acting ? <ChamadaButton sector={sector} resource={resource} /> : null}
      {/* No "Apontamento por setor" do IagoDev quem está logado é a gestão: ela também recebe os chamados. */}
      {calls ? <ChamadaRecebida /> : null}
    </div>
  );
}
