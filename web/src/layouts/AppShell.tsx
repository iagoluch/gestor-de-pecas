import { useEffect, useMemo, useRef, useState } from "react";
import type { PropsWithChildren } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AssistantDock } from "../components/AssistantDock";
import { ChamadaSino } from "../components/ChamadaSino";
import { CommandPalette } from "../components/CommandPalette";
import { LogoutButton } from "../components/LogoutButton";
import { SystemClock } from "../components/SystemClock";
import { ThemeToggle } from "../components/ThemeToggle";
import { assets } from "../config/assets";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { isSectionActive, managementSections, sectionPathFor, sectionVisibleFor } from "../config/navigation";

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
  const drawerRef = useRef<HTMLElement>(null);
  // No celular a barra vira gaveta modal: foco preso nela, Esc fecha e o foco
  // volta ao botão de menu (AX-05). No desktop `open` nunca liga.
  useDialogFocus(drawerRef, open, () => setOpen(false));
  const areaIds = useMemo(() => user?.areas?.map((area) => area.id) ?? [], [user?.areas]);
  const sections = managementSections.filter((section) => sectionVisibleFor(section, user?.role, areaIds));
  const section = sections.find((item) => isSectionActive(item, location.pathname));
  const tab = section?.tabs.find((item) => location.pathname === item.path || location.pathname.startsWith(`${item.path}/`));
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

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
      <a className="skip-link" href="#conteudo">Pular para o conteúdo</a>
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
      <aside ref={drawerRef} className={`sidebar ${open ? "sidebar--open" : ""}`} aria-modal={open || undefined} role={open ? "dialog" : undefined} aria-label={open ? "Navegação" : undefined}>
        <div className="sidebar__brand">
          <img src={assets.logo} alt="Gestor de Peças" />
          <button type="button" className="sidebar__close" onClick={() => setOpen(false)} aria-label="Fechar navegação">×</button>
        </div>
        <nav className="sidebar__nav" aria-label="Navegação gerencial">
          {sections.map((item) => {
            const active = isSectionActive(item, location.pathname);
            return (
              <Link
                key={item.id}
                to={sectionPathFor(item, user?.role, areaIds)}
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
          <small className="sidebar__credit">Desenvolvido por:<br />Iago Luchtenberg da Silva</small>
        </div>
      </aside>
      <div className="app-main">
        <header className="topbar">
          <div className="topbar__crumb" aria-label="Você está em">
            <span>Gestão</span>
            {section ? <><span aria-hidden="true">/</span><span>{section.label}</span></> : null}
            {tab ? <><span aria-hidden="true">/</span><b>{tab.label}</b></> : null}
          </div>
          <button type="button" className="topbar__search" onClick={() => setPaletteOpen(true)} aria-label="Ir para qualquer tela (Ctrl K)">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" aria-hidden="true"><circle cx="11" cy="11" r="6.5" stroke="currentColor" strokeWidth="1.8" /><path d="m20 20-4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            <span>Ir para qualquer tela…</span>
            <kbd>Ctrl K</kbd>
          </button>
          <div className="topbar__clock" aria-label="Horário do sistema"><i aria-hidden="true" /><SystemClock /></div>
          <ThemeToggle compact />
          <ChamadaSino />
          <div className="topbar__user">
            <img src={assets.profile} alt="" />
            <span>{user?.name ?? "Usuário"}</span>
            <LogoutButton compact />
          </div>
        </header>
        <main id="conteudo" tabIndex={-1} className="app-content">{children ?? <Outlet />}</main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} sections={sections} role={user?.role} areaIds={areaIds} />
      <AssistantDock />
    </div>
  );
}
