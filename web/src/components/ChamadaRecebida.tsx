import { useState } from "react";
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

function onde(item: ChamadaRecebidaItem) {
  const contexto = item.contexto ?? {};
  return [contexto.setor, contexto.maquina].filter(Boolean).join(" · ");
}

function oQueEstavaFazendo(item: ChamadaRecebidaItem) {
  const contexto = item.contexto ?? {};
  const partes: string[] = [];
  if (contexto.op) partes.push(`OP ${contexto.op}${contexto.numero_operacao ? ` / op. ${contexto.numero_operacao}` : ""}`);
  const produto = contexto.produto_descricao || contexto.peca || contexto.produto_codigo;
  if (produto) partes.push(String(produto));
  return partes.join(" · ");
}

/**
 * Chamadas endereçadas a quem está logado (o contato do botão de chamada está
 * ligado a esta conta). O cartão fica na tela até a pessoa dar "Atendi" — não
 * depende do Telegram. Atualiza ao vivo pelo mesmo canal das demais telas.
 */
export function ChamadaRecebida() {
  const query = useApiQuery<{ items: ChamadaRecebidaItem[] }>("/api/v1/chamadas/para-mim");
  const [atendendo, setAtendendo] = useState<number | null>(null);
  const [falha, setFalha] = useState("");
  const itens = query.data?.items ?? [];

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
        const local = onde(item);
        const trabalho = oQueEstavaFazendo(item);
        const urgente = item.prioridade === "Urgente" || item.prioridade === "Alta";
        return (
          <article
            key={item.id}
            className={`chamada-recebida__card${urgente ? " chamada-recebida__card--urgente" : ""}`}
          >
            <header className="chamada-recebida__topo">
              <strong>{item.solicitante_nome} está chamando</strong>
              <span className="chamada-recebida__hora">{horaDaChamada(item.criado_em)}</span>
            </header>
            <p className="chamada-recebida__motivo">
              {item.motivo}
              {item.prioridade ? <span className="chamada-recebida__prioridade"> · {item.prioridade}</span> : null}
            </p>
            {local ? <p className="chamada-recebida__linha">{local}</p> : null}
            {trabalho ? <p className="chamada-recebida__linha">{trabalho}</p> : null}
            <p className="chamada-recebida__comentario">{item.comentario}</p>
            <button
              type="button"
              className="button button--primary"
              disabled={atendendo === item.id}
              onClick={() => void atender(item.id)}
            >
              Atendi
            </button>
          </article>
        );
      })}
      {falha ? <p className="chamada-recebida__erro">{falha}</p> : null}
    </section>
  );
}
