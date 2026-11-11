import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { EmptyState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SearchInput } from "../../components/SearchInput";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";

/** Setores da Solda que abrem o mapa Produto -> Subconjunto (mesma lista do backend). */
export const SOLDA_SETORES = ["Solda Aço", "Solda Alumínio", "Solda Robô", "Proj. Ferramentaria", "Protótipo"];

interface Codigo { id: number; produto_id: number; subconjunto_id: number | null; codigo_item: string }
interface Pendencia { op: string; produto_codigo: string; operacao: string; motivo: string; motivo_texto: string }
interface Contagem { operacoes: number; ops: number }
interface Subconjunto extends Contagem { id: number; produto_id: number; nome: string; codigo: string; ativo: boolean; codigos: Codigo[] }
interface Produto extends Contagem {
  id: number; nome: string; codigo: string; ativo: boolean;
  pendencias: Pendencia[]; subconjuntos: Subconjunto[]; codigos: Codigo[];
}
interface Mapa {
  setor: string;
  estacoes: { level: string; resources: string[] }[];
  produtos: Produto[];
  pendencias: Pendencia[];
  totais: Contagem & { pendencias: number };
}

const BASE = "/inicio/apontamento-por-setor";
const mapaPath = (setor: string) => `/api/v1/solda-mapa/${encodeURIComponent(setor)}`;
const contagem = (c: Contagem) => `${c.operacoes} operações na fila · ${c.ops} OPs`;

function useMapa() {
  const { setor = "" } = useParams();
  const query = useApiQuery<Mapa>(SOLDA_SETORES.includes(setor) ? mapaPath(setor) : null, { ignoreLiveTick: true });
  const [erro, setErro] = useState<string | null>(null);
  async function gravar(acao: () => Promise<unknown>) {
    setErro(null);
    try {
      await acao();
      query.reload();
      return true;
    } catch (reason) {
      setErro(apiErrorMessage(reason));
      return false;
    }
  }
  return { setor, query, erro, gravar };
}

function NovoCadastro({ rotulo, onSalvar }: { rotulo: string; onSalvar: (nome: string, codigo: string) => Promise<boolean> }) {
  const [nome, setNome] = useState("");
  const [codigo, setCodigo] = useState("");
  async function enviar(event: FormEvent) {
    event.preventDefault();
    if (await onSalvar(nome, codigo)) { setNome(""); setCodigo(""); }
  }
  return (
    <form className="solda-form" onSubmit={(event) => void enviar(event)}>
      <label>Nome<input value={nome} onChange={(e) => setNome(e.target.value)} required maxLength={120} /></label>
      <label>Código<input value={codigo} onChange={(e) => setCodigo(e.target.value)} required maxLength={60} /></label>
      <button type="submit" className="button button--primary">{rotulo}</button>
    </form>
  );
}

function Codigos({ itens, onAdicionar, onRemover }: {
  itens: Codigo[];
  onAdicionar: (codigo: string) => Promise<boolean>;
  onRemover: (id: number) => void;
}) {
  const [codigo, setCodigo] = useState("");
  async function enviar(event: FormEvent) {
    event.preventDefault();
    if (await onAdicionar(codigo)) setCodigo("");
  }
  return (
    <div className="solda-codigos">
      {itens.length ? (
        <ul>
          {itens.map((item) => (
            <li key={item.id}>
              <code>{item.codigo_item}</code>
              <button type="button" aria-label={`Remover código ${item.codigo_item}`} onClick={() => onRemover(item.id)}>×</button>
            </li>
          ))}
        </ul>
      ) : <small>Nenhum código de item vinculado.</small>}
      <form onSubmit={(event) => void enviar(event)}>
        <input value={codigo} onChange={(e) => setCodigo(e.target.value)} placeholder="Código do item (Protheus)" aria-label="Código do item" required maxLength={60} />
        <button type="submit" className="button">Vincular</button>
      </form>
    </div>
  );
}

function Pendencias({ itens, titulo }: { itens: Pendencia[]; titulo: string }) {
  if (!itens.length) return null;
  return (
    <Notice tone="stale">
      <details className="solda-pendencias">
        <summary>{`${itens.length} ${titulo}`}</summary>
        <ul>
          {itens.map((item, index) => (
            <li key={`${item.op}-${item.operacao}-${index}`}>
              {`OP ${item.op} · item ${item.produto_codigo || "sem código"} · operação ${item.operacao} — ${item.motivo_texto}`}
            </li>
          ))}
        </ul>
      </details>
    </Notice>
  );
}

function Status({ ativo }: { ativo: boolean }) {
  return <span className={`solda-status solda-status--${ativo ? "ativo" : "inativo"}`}>{ativo ? "Ativo" : "Inativo"}</span>;
}

/** Tela 2: produtos de um setor da Solda. */
export function SoldaProdutosPage() {
  const { setor, query, erro, gravar } = useMapa();
  const navigate = useNavigate();
  const [busca, setBusca] = useState("");
  const mapa = query.data;
  const termo = busca.trim().toLocaleLowerCase("pt-BR");
  const produtos = (mapa?.produtos ?? []).filter((p) => !termo || `${p.nome} ${p.codigo}`.toLocaleLowerCase("pt-BR").includes(termo));

  if (!SOLDA_SETORES.includes(setor)) return <EmptyState title="Setor da Solda não encontrado" detail="Volte e escolha um setor." />;
  return (
    <PageFrame
      sectionId="dev"
      title={setor}
      subtitle={`${setor} · Selecione o produto para acessar seus subconjuntos`}
      filters={false}
      staleError={mapa ? query.error : null}
      actions={<Link className="button" to={BASE}>Voltar aos setores</Link>}
      summary={mapa ? (
        <div className="metric-grid metric-grid--four">
          <MetricCard label="Operações na fila" value={String(mapa.totais.operacoes)} detail="Do setor inteiro, cada uma contada uma vez" accent="primary" />
          <MetricCard label="OPs na fila" value={String(mapa.totais.ops)} detail="OPs distintas" accent="teal" />
          <MetricCard label="Produtos ativos" value={String(mapa.produtos.filter((p) => p.ativo).length)} detail={`${mapa.produtos.length} cadastrados`} accent="purple" />
          <MetricCard label="Sem vínculo" value={String(mapa.totais.pendencias)} detail="Operações fora de produto/subconjunto" accent={mapa.totais.pendencias ? "warning" : "success"} />
        </div>
      ) : undefined}
    >
      {erro ? <Notice tone="error">{erro}</Notice> : null}
      {query.loading && !mapa ? <LoadingState /> : null}
      {mapa ? (
        <>
          <Pendencias itens={mapa.pendencias} titulo="operações sem produto — cadastre o código do item em um produto para elas aparecerem no mapa" />
          <SectionCard title="Produtos" className="content-section">
            <SearchInput value={busca} onChange={setBusca} placeholder="Buscar produto por nome ou código" />
            {produtos.length ? (
              <div className="solda-grid">
                {produtos.map((produto) => (
                  <article key={produto.id} className={`solda-card${produto.ativo ? "" : " solda-card--inativo"}`}>
                    <header><strong>{produto.nome}</strong><Status ativo={produto.ativo} /></header>
                    <small>{`Código ${produto.codigo}`}</small>
                    <span className="solda-card__contagem">{contagem(produto)}</span>
                    {produto.pendencias.length ? <span className="solda-card__pendencia">{`${produto.pendencias.length} sem subconjunto`}</span> : null}
                    <button type="button" className="button button--primary" onClick={() => navigate(`${BASE}/solda/${encodeURIComponent(setor)}/${produto.id}`)}>
                      Ver subconjuntos
                    </button>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                title={mapa.produtos.length ? "Nenhum produto com esse nome ou código" : "Nenhum produto cadastrado neste setor"}
                detail={mapa.produtos.length ? "Limpe a busca para ver todos." : "Cadastre abaixo os produtos da Solda. Até lá, toda a fila aparece como sem vínculo."}
              />
            )}
          </SectionCard>
          <SectionCard title="Cadastrar produto" className="content-section">
            <NovoCadastro rotulo="Adicionar produto" onSalvar={(nome, codigo) => gravar(() => api.post(`${mapaPath(setor)}/produtos`, { nome, codigo }))} />
          </SectionCard>
        </>
      ) : null}
    </PageFrame>
  );
}

/** Tela 3: subconjuntos de um produto. "Acessar recurso" abre a fila da estação já filtrada. */
export function SoldaSubconjuntosPage() {
  const { setor, query, erro, gravar } = useMapa();
  const { produtoId = "" } = useParams();
  const { actAsSector } = useAuth();
  const navigate = useNavigate();
  const [escolha, setEscolha] = useState<Subconjunto | null>(null);
  const mapa = query.data;
  const produto = mapa?.produtos.find((p) => String(p.id) === produtoId);
  const voltar = `${BASE}/solda/${encodeURIComponent(setor)}`;

  async function acessar(sub: Subconjunto, level: string) {
    // Entrar na fila não inicia tempo: só abre a estação com a fila filtrada.
    // Recarrega a página: trocar a sessão já redireciona para /operador e perderia o filtro na URL.
    const ok = await gravar(() => actAsSector(level));
    if (ok) window.location.assign(`/operador?subconjunto=${sub.id}`);
  }
  function abrir(sub: Subconjunto) {
    if (mapa && mapa.estacoes.length === 1) void acessar(sub, mapa.estacoes[0].level);
    else setEscolha(sub);
  }
  const removerCodigo = (id: number) => void gravar(() => api.delete(`/api/v1/solda-mapa/vinculos/${id}`));
  const vincular = (subconjuntoId: number | null) => (codigo_item: string) =>
    gravar(() => api.post(`/api/v1/solda-mapa/produtos/${produto?.id}/vinculos`, { codigo_item, subconjunto_id: subconjuntoId }));

  if (mapa && !produto) return <EmptyState title="Produto não encontrado" detail="Volte e escolha outro produto." />;
  return (
    <PageFrame
      sectionId="dev"
      title={produto?.nome ?? setor}
      subtitle={`${setor} › ${produto?.nome ?? ""} · Selecione o subconjunto para acessar a fila da estação já filtrada`}
      filters={false}
      staleError={mapa ? query.error : null}
      actions={<Link className="button" to={voltar}>Voltar aos produtos</Link>}
      summary={produto ? (
        <div className="metric-grid metric-grid--four">
          <MetricCard label="Operações na fila" value={String(produto.operacoes)} detail="Deste produto, já nos subconjuntos" accent="primary" />
          <MetricCard label="OPs na fila" value={String(produto.ops)} detail="OPs distintas" accent="teal" />
          <MetricCard label="Subconjuntos ativos" value={String(produto.subconjuntos.filter((s) => s.ativo).length)} detail={`${produto.subconjuntos.length} cadastrados`} accent="purple" />
          <MetricCard label="Sem subconjunto" value={String(produto.pendencias.length)} detail="Operações do produto sem subconjunto" accent={produto.pendencias.length ? "warning" : "success"} />
        </div>
      ) : undefined}
    >
      {erro ? <Notice tone="error">{erro}</Notice> : null}
      {query.loading && !mapa ? <LoadingState /> : null}
      {produto && mapa ? (
        <>
          <Pendencias itens={produto.pendencias} titulo="operações deste produto sem subconjunto" />
          {escolha ? (
            <SectionCard title={`Em qual estação abrir "${escolha.nome}"?`} className="content-section">
              <div className="solda-estacoes">
                {mapa.estacoes.map((estacao) => (
                  <button key={estacao.level} type="button" className="button" onClick={() => void acessar(escolha, estacao.level)}>
                    {estacao.resources.join(", ")}
                  </button>
                ))}
                <button type="button" className="button" onClick={() => setEscolha(null)}>Cancelar</button>
              </div>
            </SectionCard>
          ) : null}
          <SectionCard title={`Subconjuntos · código do produto ${produto.codigo}`} className="content-section">
            {produto.subconjuntos.length ? (
              <div className="solda-grid">
                {produto.subconjuntos.map((sub) => (
                  <article key={sub.id} className={`solda-card${sub.ativo ? "" : " solda-card--inativo"}`}>
                    <header><strong>{sub.nome}</strong><Status ativo={sub.ativo} /></header>
                    <small>{`Código ${sub.codigo}`}</small>
                    <span className="solda-card__contagem">{contagem(sub)}</span>
                    <button type="button" className="button button--primary" disabled={!sub.ativo || !produto.ativo} onClick={() => abrir(sub)}>
                      Acessar recurso
                    </button>
                    <details>
                      <summary>Códigos de item e status</summary>
                      <Codigos itens={sub.codigos} onAdicionar={vincular(sub.id)} onRemover={removerCodigo} />
                      <button type="button" className="button" onClick={() => void gravar(() => api.put(`/api/v1/solda-mapa/subconjuntos/${sub.id}`, { ativo: !sub.ativo }))}>
                        {sub.ativo ? "Desativar subconjunto" : "Reativar subconjunto"}
                      </button>
                    </details>
                  </article>
                ))}
              </div>
            ) : <EmptyState title="Nenhum subconjunto cadastrado" detail="Cadastre abaixo os subconjuntos deste produto." />}
          </SectionCard>
          <SectionCard title="Cadastrar subconjunto" className="content-section">
            <NovoCadastro rotulo="Adicionar subconjunto" onSalvar={(nome, codigo) => gravar(() => api.post(`/api/v1/solda-mapa/produtos/${produto.id}/subconjuntos`, { nome, codigo }))} />
          </SectionCard>
          <SectionCard title="Códigos do produto sem subconjunto" className="content-section">
            <p className="solda-ajuda">Item que pertence ao produto mas ainda não tem subconjunto: aparece como pendência dentro do produto, nunca some.</p>
            <Codigos itens={produto.codigos} onAdicionar={vincular(null)} onRemover={removerCodigo} />
            <button type="button" className="button" onClick={() => void gravar(() => api.put(`/api/v1/solda-mapa/produtos/${produto.id}`, { ativo: !produto.ativo }))}>
              {produto.ativo ? "Desativar produto" : "Reativar produto"}
            </button>
          </SectionCard>
        </>
      ) : null}
    </PageFrame>
  );
}
