import { useState } from "react";
import type { PropsWithChildren } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
import { assets } from "../config/assets";
import { managementSections } from "../config/navigation";

export function AppShell({ children }: PropsWithChildren) {
  const { user } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);

  return (
    <div className="app-shell">
      <button className="mobile-menu" type="button" onClick={() => setOpen(true)} aria-label="Abrir navegação">
        <span />
        <span />
        <span />
      </button>
      {open ? <button className="sidebar-scrim" type="button" aria-label="Fechar navegação" onClick={() => setOpen(false)} /> : null}
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="sidebar__brand">
          <img src={assets.logo} alt="Gestor de Peças" />
          <button type="button" className="sidebar__close" onClick={() => setOpen(false)} aria-label="Fechar navegação">×</button>
        </div>
        <div className="profile-card">
          <img src={assets.profile} alt="" />
          <div>
            <strong>Olá,</strong>
            <span>{user?.name ?? "Usuário"}</span>
          </div>
        </div>
        <nav className="sidebar__nav" aria-label="Navegação gerencial">
          {managementSections.map((item) => (
            <Link
              key={item.id}
              to={item.defaultPath}
              onClick={() => setOpen(false)}
              aria-current={location.pathname.startsWith(`/${item.defaultPath.split("/")[1]}`) ? "page" : undefined}
              className={`sidebar-link ${location.pathname.startsWith(`/${item.defaultPath.split("/")[1]}`) ? "sidebar-link--active" : ""}`}
            >
              <span className="sidebar-link__icon" aria-hidden="true"><img src={item.icon} alt="" /></span>
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar__footer">
          <LogoutButton />
          <div className="status-card">
            <div className="status-card__clock">
              <img src={assets.clock} alt="" aria-hidden="true" />
              <div>
                <SystemClock />
              </div>
            </div>
          </div>
          <small className="sidebar__credit">Desenvolvido por:<br />Iago Luchtenberg da Silva</small>
        </div>
      </aside>
      <main className="app-content">{children ?? <Outlet />}</main>
    </div>
  );
}
