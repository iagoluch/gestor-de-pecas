import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";

interface ChamadaRecebidaItem {
  id: number;
  motivo: string;
  prioridade?: string | null;
  comentario: string;
  solicitante_nome: string;
  criado_em?: string | null;
  contexto?: {
    setor?: string;
    maquina?: string;
    op?: string | number;
    numero_operacao?: string | number;
    produto_codigo?: string;
    produto_descricao?: string;
    peca?: string;
  } | null;
}

function horaDaChamada(valor?: string | null) {
  if (!valor) return "";
  const data = new Date(valor);
  if (Number.isNaN(data.getTime())) return "";
  return data.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

/** Dois bipes curtos, sem arquivo de áudio. Navegador que bloqueia som só fica no visual. */
function tocarAlerta() {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const audio = new Ctx();
    [0, 0.25].forEach((inicio) => {
      const osc = audio.createOscillator();
      const volume = audio.createGain();
      osc.frequency.value = 880;
      volume.gain.setValueAtTime(0.25, audio.currentTime + inicio);
      volume.gain.exponentialRampToValueAtTime(0.001, audio.currentTime + inicio + 0.2);
      osc.connect(volume).connect(audio.destination);
      osc.start(audio.currentTime + inicio);
      osc.stop(audio.currentTime + inicio + 0.2);
    });
    window.setTimeout(() => void audio.close(), 800);
  } catch {
    // Sem som disponível: o cartão pulsando continua avisando.
  }
}

function Linha({ rotulo, children }: { rotulo: string; children: ReactNode }) {
  return (
    <div className="chamada-recebida__linha">
      <span className="chamada-recebida__rotulo">{rotulo}</span>
      <span className="chamada-recebida__valor">{children}</span>
    </div>
  );
}

/**
 * Chamadas endereçadas a quem está logado (o contato do botão de chamada está
 * ligado a esta conta). O cartão pulsa e toca um bipe quando chega, e fica na
 * tela até a pessoa clicar em "Atender" — não depende do Telegram.
 */
export function ChamadaRecebida() {
  const query = useApiQuery<{ items: ChamadaRecebidaItem[] }>("/api/v1/chamadas/para-mim");
  const [atendendo, setAtendendo] = useState<number | null>(null);
  const [falha, setFalha] = useState("");
  const itens = query.data?.items ?? [];
  const vistas = useRef<Set<number> | null>(null);

  useEffect(() => {
    if (!query.data) return;
    const ids = query.data.items.map((item) => item.id);
    // Na primeira carga não toca: são chamadas que já estavam na tela.
    if (vistas.current && ids.some((id) => !vistas.current?.has(id))) tocarAlerta();
    vistas.current = new Set(ids);
  }, [query.data]);

  async function atender(id: number) {
    setAtendendo(id);
    setFalha("");
    try {
      await api.post(`/api/v1/chamadas/${id}/atender`);
    } catch {
      setFalha("Não foi possível marcar como atendida. Tente de novo.");
    } finally {
      setAtendendo(null);
      query.reload();
    }
  }

  if (itens.length === 0) return null;

  return (
    <section className="chamada-recebida" role="alert" aria-live="assertive" aria-label="Chamadas para você">
      {itens.map((item) => {
        const contexto = item.contexto ?? {};
        const processo = [contexto.setor, contexto.maquina].filter(Boolean).join(" · ");
        const produto = contexto.produto_descricao || contexto.peca || contexto.produto_codigo;
        const prioridade = item.prioridade || "Média";
        const urgente = prioridade === "Urgente" || prioridade === "Alta";
        return (
          <article
            key={item.id}
            className={`chamada-recebida__card${urgente ? " chamada-recebida__card--urgente" : ""}`}
          >
            <header className="chamada-recebida__topo">
              <span className="chamada-recebida__icone" aria-hidden="true"><IconeChamado /></span>
              <div className="chamada-recebida__titulo">
                <strong>Chamado</strong>
                <span>{item.solicitante_nome} está chamando</span>
              </div>
              <span className="chamada-recebida__vivo">Ao vivo</span>
              <span className="chamada-recebida__hora">{horaDaChamada(item.criado_em)}</span>
            </header>
            <div className="chamada-recebida__detalhes">
              <Linha rotulo="Motivo">
                <strong>{item.motivo}</strong>
                <span className={`chamada-recebida__prioridade chamada-recebida__prioridade--${prioridade.toLowerCase()}`}>
                  {prioridade}
                </span>
              </Linha>
              {processo ? <Linha rotulo="Processo"><strong>{processo}</strong></Linha> : null}
              {contexto.op ? (
                <Linha rotulo="OP">
                  <strong>{`${contexto.op}${contexto.numero_operacao ? ` / Op. ${contexto.numero_operacao}` : ""}`}</strong>
                </Linha>
              ) : null}
              {produto ? <Linha rotulo="Descrição"><strong>{String(produto)}</strong></Linha> : null}
            </div>
            <footer className="chamada-recebida__rodape">
              <div className="chamada-recebida__mensagem">
                <span className="chamada-recebida__rotulo">Mensagem</span>
                <p>{item.comentario || "Sem comentário"}</p>
              </div>
              <button
                type="button"
                className="chamada-recebida__atender"
                disabled={atendendo === item.id}
                onClick={() => void atender(item.id)}
              >
                <IconeChamado />
                Atender
              </button>
            </footer>
          </article>
        );
      })}
      {falha ? <p className="chamada-recebida__erro">{falha}</p> : null}
    </section>
  );
}

function IconeChamado() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
      <path
        d="M4 14v-2a8 8 0 0 1 16 0v2M4 14a2 2 0 0 0 2 2h1v-5H6a2 2 0 0 0-2 2v1Zm16 0a2 2 0 0 1-2 2h-1v-5h1a2 2 0 0 1 2 2v1Zm-3 2v1a3 3 0 0 1-3 3h-2"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
