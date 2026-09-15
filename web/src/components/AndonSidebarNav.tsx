import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { assets } from "../config/assets";
import { isSectionActive, managementSections } from "../config/navigation";
import { ChamadaSino } from "./ChamadaSino";
import { LogoutButton } from "./LogoutButton";
import { SystemClock } from "./SystemClock";
import { ThemeToggle } from "./ThemeToggle";

/**
 * Andon e Solda abrem em página cheia, fora do menu lateral da gestão — quem
 * chega lá pelo menu fica sem jeito de voltar pra Tela inicial (ou alcançar
 * qualquer outra seção) a não ser pelo "voltar" do navegador. Este botão abre
 * o mesmo menu lateral da gestão como uma camada sobreposta ao quadro, sem
 * empurrar o conteúdo (decisão do usuário, 15/09/2026).
 *
 * Só aparece pra quem tem management_access: o login dedicado da TV (role
 * "andon", Modo TV) nunca vê isso — quem chama decide isso olhando o papel do
 * usuário, este componente só desenha o menu.
 */
export function AndonSidebarNav() {
  const { user } = useAuth();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const sections = managementSections.filter((section) => !section.adminOnly || user?.role === "admin");

  return (
    <>
      <button type="button" className="andon-sidebar-toggle" onClick={() => setOpen(true)} aria-label="Abrir navegação">
        <span />
        <span />
        <span />
      </button>
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
