import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AIPage } from "../pages/AIPage";
import { AIIcon } from "./AIIcon";
import { ChamadaButton } from "./ChamadaButton";
import { useAiEnabled } from "./PageFrame";

const AI_PAGE = "/inicio/ia";

/**
 * Menu de atalhos do canto da tela (gestão): um "?" que, ao passar o mouse,
 * abre para a esquerda o botão de chamada e o da IA. A IA abre em popup sobre
 * a tela atual, reaproveitando a própria tela da IA (`embedded`).
 */
export function AssistantDock() {
  const { pathname } = useLocation();
  const onAiPage = pathname === AI_PAGE;
  const aiEnabled = useAiEnabled(!onAiPage) !== false;
  const [expanded, setExpanded] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  // Depois da primeira abertura o chat fica montado (só escondido), para uma
  // resposta em andamento não ser cancelada ao fechar o popup.
  const [chatStarted, setChatStarted] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const showChat = aiEnabled && !onAiPage;

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setExpanded(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      setExpanded(false);
      setChatOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, []);

  function openChat() {
    setChatStarted(true);
    setChatOpen(true);
    setExpanded(false);
  }

  return (
    <>
      {showChat && chatStarted ? (
        <section className="ai-popup" hidden={!chatOpen} aria-label="IA Industrial">
          <header className="ai-popup__header">
            <span className="ai-popup__mark"><AIIcon size={18} /></span>
            <strong>IA Industrial</strong>
            <Link to={AI_PAGE} className="ai-popup__icon" title="Abrir na página inteira" aria-label="Abrir na página inteira" onClick={() => setChatOpen(false)}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 4h6v6M20 4l-8 8M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></svg>
            </Link>
            <button type="button" className="ai-popup__icon" aria-label="Fechar a IA" title="Fechar" onClick={() => setChatOpen(false)}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
            </button>
          </header>
          <AIPage embedded />
        </section>
      ) : null}

      <div ref={rootRef} className={`dock${expanded ? " dock--open" : ""}${showChat ? "" : " dock--no-ai"}`}>
        <button
          type="button"
          className="dock__toggle"
          aria-label="Atalhos: chamar alguém e IA"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9.2 9a3 3 0 1 1 4.4 2.7c-1 .6-1.6 1.2-1.6 2.3M12 17.5v.01" /></svg>
        </button>
        {showChat ? (
          <button type="button" className="dock-btn dock-btn--ai" data-label="Perguntar à IA" aria-label="Perguntar à IA" onClick={openChat}>
            <AIIcon size={24} />
          </button>
        ) : null}
        <ChamadaButton variant="gestao" dock label="Chamar alguém" />
      </div>
    </>
  );
}
