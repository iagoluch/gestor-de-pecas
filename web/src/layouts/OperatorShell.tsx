import type { PropsWithChildren } from "react";
import { useAuth } from "../auth/AuthContext";
import { ChamadaButton } from "../components/ChamadaButton";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
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
  const { user } = useAuth();
  const navIcon = assets.operator.navigation[sector as keyof typeof assets.operator.navigation];
  const title = resource && resource !== sector ? `${sector} - ${resource}` : sector;
  // Sem navegação declarada o posto continua exibindo apenas o próprio setor,
  // exatamente como antes da aba Qualidade existir.
  const items: OperatorNavItem[] = navigation?.length
    ? navigation
    : [{ key: sector, label: sector, icon: navIcon, onSelect: () => undefined }];
  const current = activeNav ?? items[0]?.key;
  return (
    <div className="operator-shell">
      <aside className="operator-sidebar">
        <div className="operator-sidebar__brand"><img src={assets.operator.logo} alt="Gestor de Peças" /></div>
        <div className="operator-profile">
          <img src={assets.operator.profile} alt="" />
          <div><strong>Olá,</strong><span>{user?.name}</span></div>
        </div>
        <nav className="operator-sidebar__nav" aria-label="Áreas do posto">
          {items.map((item) => {
            const active = item.key === current;
            return (
              <button
                key={item.key}
                type="button"
                className={`operator-sector-link ${active ? "" : "operator-sector-link--inactive"}`}
                aria-current={active ? "page" : undefined}
                onClick={item.onSelect}
              >
                {item.icon ? <img src={item.icon} alt="" /> : null}<strong>{item.label}</strong>
              </button>
            );
          })}
        </nav>
        <div className="operator-sidebar__footer">
          <div className="operator-status-card">
            <div><img src={assets.clock} alt="" /><SystemClock /></div>
          </div>
          <small>Desenvolvido por:<br />Iago Luchtenberg da Silva</small>
        </div>
      </aside>
      <main className="operator-main">
        <header className="operator-header">
          {onBack ? <button type="button" className="operator-back" onClick={onBack} aria-label="Voltar">‹</button> : null}
          <h1>{title}</h1>
          <div className="operator-header__logout"><LogoutButton /></div>
        </header>
        <div className="operator-content">{children}</div>
      </main>
      <ChamadaButton />
    </div>
  );
}
