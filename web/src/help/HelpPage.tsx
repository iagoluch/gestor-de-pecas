import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../components/ThemeToggle";
import { MANUAIS, acharTopico, buscarTopicos, topicosDoManual, type HelpTopic, type ManualId } from "./helpContent";

function manualValido(valor?: string): valor is ManualId {
  return valor === "operador" || valor === "gestao";
}

function agrupar(topicos: HelpTopic[]): Array<{ grupo: string; itens: HelpTopic[] }> {
  const grupos: Array<{ grupo: string; itens: HelpTopic[] }> = [];
  for (const t of topicos) {
    const atual = grupos.find((g) => g.grupo === t.grupo);
    if (atual) atual.itens.push(t); else grupos.push({ grupo: t.grupo, itens: [t] });
  }
  return grupos;
}

/** Manual dentro do sistema: árvore à esquerda, texto à direita, busca e impressão. */
export function HelpPage() {
  const { manual: manualParam, topico: topicoParam } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [busca, setBusca] = useState("");

  const manual: ManualId | null = manualValido(manualParam) ? manualParam : null;
  const podeGestao = Boolean(user?.management_access);
  const topicos = useMemo(() => (manual ? topicosDoManual(manual) : []), [manual]);
  const grupos = useMemo(() => agrupar(topicos), [topicos]);
  const resultados = useMemo(() => (manual ? buscarTopicos(manual, busca) : []), [manual, busca]);

  if (!manual) return <Navigate to={`/ajuda/${podeGestao ? "gestao" : "operador"}`} replace />;
  if (manual === "gestao" && !podeGestao) return <Navigate to="/ajuda/operador" replace />;

  const atual = acharTopico(manual, topicoParam);
  const indice = atual ? topicos.indexOf(atual) : -1;
  const anterior = indice > 0 ? topicos[indice - 1] : undefined;
  const proximo = indice >= 0 && indice < topicos.length - 1 ? topicos[indice + 1] : undefined;
  const aberto = (t: HelpTopic) => t.id === atual?.id;

  return (
    <div className="help">
      <header className="help__top">
        <div className="help__brand">
          <span className="help__logo" aria-hidden="true">?</span>
          <div>
            <strong>{MANUAIS[manual].titulo}</strong>
            <small>{MANUAIS[manual].subtitulo}</small>
          </div>
        </div>
        <nav className="help__switch" aria-label="Escolher manual">
          <Link className={manual === "operador" ? "is-on" : ""} to="/ajuda/operador">Operador</Link>
          {podeGestao ? <Link className={manual === "gestao" ? "is-on" : ""} to="/ajuda/gestao">Gestão</Link> : null}
        </nav>
        <div className="help__top-actions">
          <ThemeToggle compact />
          <button type="button" className="help__btn" onClick={() => window.print()}>Imprimir este tópico</button>
          <button type="button" className="help__btn" onClick={() => (window.history.length > 1 ? navigate(-1) : window.close())}>Voltar ao sistema</button>
        </div>
      </header>

      <div className="help__body">
        <aside className="help__tree" aria-label="Índice do manual">
          <input
            className="help__search"
            type="search"
            value={busca}
            onChange={(e) => setBusca(e.target.value)}
            placeholder="Buscar no manual…"
            aria-label="Buscar no manual"
          />
          {busca.trim() ? (
            <ul className="help__results">
              {resultados.length === 0 ? <li className="help__empty">Nada encontrado para “{busca}”.</li> : null}
              {resultados.map((t) => (
                <li key={t.id}>
                  <Link to={`/ajuda/${manual}/${t.id}`} onClick={() => setBusca("")}>
                    <b>{t.titulo}</b>
                    {t.grupo ? <small>{t.grupo}</small> : null}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            grupos.map(({ grupo, itens }) => (
              <section key={grupo || "_"} className="help__group">
                {grupo ? <h2>{grupo}</h2> : null}
                <ul>
                  {itens.map((t) => (
                    <li key={t.id}>
                      <Link to={`/ajuda/${manual}/${t.id}`} className={aberto(t) ? "is-on" : ""} aria-current={aberto(t) ? "page" : undefined}>{t.titulo}</Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))
          )}
        </aside>

        <main className="help__content" id="conteudo-ajuda">
          {atual ? (
            <article>
              <h1 className="help__title">{atual.titulo}</h1>
              <div className="help__prose">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  skipHtml
                  components={{
                    table({ node, ...props }) { void node; return <div className="help__table"><table {...props} /></div>; },
                    a({ node, href, children, ...props }) {
                      void node;
                      if (href?.startsWith("topico:")) return <Link to={`/ajuda/${manual}/${href.slice(7)}`}>{children}</Link>;
                      return <a href={href} {...props}>{children}</a>;
                    },
                  }}
                >
                  {atual.corpo}
                </ReactMarkdown>
              </div>
              <footer className="help__pager">
                {anterior ? <Link to={`/ajuda/${manual}/${anterior.id}`}>← {anterior.titulo}</Link> : <span />}
                {proximo ? <Link to={`/ajuda/${manual}/${proximo.id}`}>{proximo.titulo} →</Link> : <span />}
              </footer>
            </article>
          ) : (
            <p className="help__empty">Este manual ainda não tem tópicos.</p>
          )}
        </main>
      </div>
    </div>
  );
}
