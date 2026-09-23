import type { PropsWithChildren } from "react";
import { ChamadaButton } from "../components/ChamadaButton";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
import { ThemeToggle } from "../components/ThemeToggle";
import { assets } from "../config/assets";

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
  children,
}: PropsWithChildren<{
  sector: string;
  resource?: string | null;
  onBack?: () => void;
  navigation?: OperatorNavItem[];
  activeNav?: string;
}>) {
  const navIcon = assets.operator.navigation[sector as keyof typeof assets.operator.navigation];
  const title = resource && resource !== sector ? `${sector} - ${resource}` : sector;
  // Sem navegação declarada o posto continua exibindo apenas o próprio setor,
  // exatamente como antes da aba Qualidade existir.
  const items: OperatorNavItem[] = navigation?.length
    ? navigation
    : [{ key: sector, label: sector, icon: navIcon, onSelect: () => undefined }];
  const current = activeNav ?? items[0]?.key;
  const hasTabs = items.length > 1;
  return (
    <div className="operator-shell">
      <header className="operator-topbar">
        <div className="operator-topbar__brand">
          <img src={assets.operator.logo} alt="Gestor de Peças" />
          <small className="sidebar__credit">Iago Luchtenberg da Silva</small>
        </div>
        <div className="operator-topbar__clock"><img src={assets.clock} alt="" /><SystemClock /></div>
        {resource ? <div className="operator-topbar__machine"><strong>{title}</strong></div> : <div />}
        <div className="operator-topbar__actions">
          <ThemeToggle compact />
          <LogoutButton compact />
        </div>
      </header>
      {hasTabs || onBack ? (
        <nav className="operator-tabs" aria-label="Áreas do posto">
          {onBack ? <button type="button" className="operator-back" onClick={onBack} aria-label="Voltar">‹</button> : null}
          {hasTabs
            ? items.map((item) => {
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
              })
            : null}
        </nav>
      ) : null}
      <main className="operator-main">
        <div className="operator-content">{children}</div>
      </main>
      <ChamadaButton sector={sector} resource={resource} />
    </div>
  );
}
