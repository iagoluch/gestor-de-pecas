import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { assets } from "../config/assets";
import { isSectionActive, managementSections, sectionById } from "../config/navigation";
import { ChamadaSino } from "./ChamadaSino";
import { LogoutButton } from "./LogoutButton";
import { SystemClock } from "./SystemClock";
import { ThemeToggle } from "./ThemeToggle";

const HIDDEN_KEY = "gestor.panelsNav.hidden";

function readStoredHidden(): boolean {
  try {
    return localStorage.getItem(HIDDEN_KEY) === "1";
  } catch {
    return false;
  }
}

function persistHidden(hidden: boolean) {
  try {
    localStorage.setItem(HIDDEN_KEY, hidden ? "1" : "0");
  } catch {
    // Preferência não persiste (aba privada, storage bloqueado) — a faixa
    // continua podendo ser escondida/trazida de volta nesta sessão.
  }
}

/**
 * Andon e Solda abrem em página cheia, fora do menu lateral da gestão. Dois
 * problemas resolvidos aqui (decisão do usuário, 15/09/2026):
 *
 * 1. Quem chega pelo menu perde o caminho de volta pra Tela inicial (ou
 *    qualquer outra seção) a não ser pelo "voltar" do navegador — o botão
 *    de menu abre o mesmo menu lateral da gestão como camada sobreposta.
 * 2. Quem só quer trocar entre Andon/Solda/Metas/Pausas continua
 *    com a faixa de sub-abas (minimizável, herdada da versão anterior).
 *
 * Tudo em fluxo normal (não fixo) pra não sobrepor os cartões do quadro.
 * Só aparece pra quem tem management_access: o login dedicado da TV (role
 * "andon", Modo TV) nunca vê isso — quem chama decide isso olhando o papel
 * do usuário, este componente só desenha o menu.
 */
export function AndonSidebarNav() {
  const { user } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [tabsHidden, setTabsHidden] = useState(readStoredHidden);
  const sections = managementSections.filter((section) => !section.adminOnly || user?.role === "admin");
  const panelsSection = sectionById("panels");

  function toggleTabs() {
    setTabsHidden((value) => {
      const next = !value;
      persistHidden(next);
      return next;
    });
  }

  function isCurrentPanelTab(path: string) {
    if (path === location.pathname) return true;
    return (path === "/inicio/andon" && location.pathname === "/andon")
      || (path === "/inicio/solda" && location.pathname === "/welding-management");
  }

  return (
    <>
      <div className="andon-nav-row">
        <button type="button" className="andon-sidebar-toggle" onClick={() => setOpen(true)} aria-label="Abrir navegação">
          <span />
          <span />
          <span />
        </button>
        {tabsHidden ? (
          <button type="button" className="panels-tabs-reopen" onClick={toggleTabs} aria-label="Mostrar abas dos Painéis Operacionais" title="Mostrar abas">
            <span aria-hidden="true">»</span> Painéis
          </button>
        ) : (
          <div className="panels-tabs-row">
            <nav className="page-tabs panels-tabs" aria-label={panelsSection.label}>
              {panelsSection.tabs.map((tab) => (
                <NavLink
                  key={tab.path}
                  to={tab.path}
                  className={() => (isCurrentPanelTab(tab.path) ? "page-tab page-tab--active" : "page-tab")}
                >
                  {tab.label}
                </NavLink>
              ))}
            </nav>
            <button type="button" className="panels-tabs-minimize" onClick={toggleTabs} aria-label="Minimizar abas dos Painéis Operacionais" title="Minimizar abas">
              <span aria-hidden="true">«</span>
            </button>
          </div>
        )}
      </div>
      {open ? (
        <button className="andon-sidebar-scrim" type="button" aria-label="Fechar navegação" onClick={() => setOpen(false)} />
      ) : null}
      <aside className={`sidebar andon-sidebar-panel ${open ? "andon-sidebar-panel--open" : ""}`}>
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
          <ThemeToggle />
          <LogoutButton />
          <div className="status-card">
            <div className="status-card__clock">
              <img src={assets.clock} alt="" aria-hidden="true" />
              <div>
                <SystemClock />
              </div>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}
