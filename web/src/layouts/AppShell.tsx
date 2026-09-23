import { useEffect, useState } from "react";
import type { PropsWithChildren } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ChamadaButton } from "../components/ChamadaButton";
import { ChamadaSino } from "../components/ChamadaSino";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
import { ThemeToggle } from "../components/ThemeToggle";
import { assets } from "../config/assets";
import { isSectionActive, managementSections } from "../config/navigation";

const SIDEBAR_COLLAPSED_KEY = "gestor.sidebar.collapsed";

function readStoredCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function AppShell({ children }: PropsWithChildren) {
  const { user } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  // Recolher a barra lateral pro lado, do jeito que já existe no celular —
  // só que fixo (não some sozinho ao navegar) e lembrado entre acessos
  // (decisão do usuário, 15/09/2026).
  const [collapsed, setCollapsed] = useState(readStoredCollapsed);
  const sections = managementSections.filter((section) => !section.adminOnly || user?.role === "admin");

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch {
      // Preferência não persiste (aba privada, storage bloqueado) — a barra
      // continua funcionando normalmente dentro desta sessão.
    }
  }, [collapsed]);

  return (
    <div className={`app-shell ${collapsed ? "app-shell--collapsed" : ""}`}>
      <button className="mobile-menu" type="button" onClick={() => setOpen(true)} aria-label="Abrir navegação">
        <span />
        <span />
        <span />
      </button>
      {open ? <button className="sidebar-scrim" type="button" aria-label="Fechar navegação" onClick={() => setOpen(false)} /> : null}
      <button
        type="button"
        className="sidebar-collapse-toggle"
        onClick={() => setCollapsed((value) => !value)}
        aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
        title={collapsed ? "Expandir menu" : "Recolher menu"}
      >
        <span aria-hidden="true">{collapsed ? "›" : "‹"}</span>
      </button>
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
          <ChamadaSino />
        </div>
        <nav className="sidebar__nav" aria-label="Navegação gerencial">
          {sections.map((item) => {
            const active = isSectionActive(item, location.pathname);
            return (
              <Link
                key={item.id}
                to={item.defaultPath}
                onClick={() => setOpen(false)}
                aria-current={active ? "page" : undefined}
                className={`sidebar-link ${active ? "sidebar-link--active" : ""}`}
              >
                <span className="sidebar-link__icon" aria-hidden="true"><img src={item.icon} alt="" /></span>
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="sidebar__footer">
          <div className="status-card">
            <div className="status-card__clock">
              <img src={assets.clock} alt="" aria-hidden="true" />
              <div>
                <SystemClock />
              </div>
            </div>
          </div>
          <div className="sidebar__quick-actions">
            <ThemeToggle compact />
            <LogoutButton compact />
          </div>
          <small className="sidebar__credit">Desenvolvido por:<br />Iago Luchtenberg da Silva</small>
        </div>
      </aside>
      <main className="app-content">{children ?? <Outlet />}</main>
      <ChamadaButton variant="gestao" />
    </div>
  );
}
