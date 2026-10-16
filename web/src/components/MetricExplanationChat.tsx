import { FormEvent, useEffect, useRef, useState } from "react";
import { aiApi } from "../api/ai";
import { ApiError } from "../api/client";
import { toQuery } from "../filters/FilterContext";
import type { AIExplanationRef, AIStreamEvent } from "../types/ai";
import type { OverviewFilters } from "../types/explanation";
import { AssistantMarkdown } from "./AssistantMarkdown";

interface ChatLine {
  id: number;
  role: "user" | "assistant";
  content: string;
}

const RATE_LIMIT_TEXT = "Limite temporário da IA. Aguarde um pouco e tente de novo.";
const GENERIC_ERROR_TEXT = "Não foi possível obter a resposta da IA agora.";

function errorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 429 || error.code === "rate_limit") return RATE_LIMIT_TEXT;
    if (error.status === 503) return "A IA não está disponível neste servidor.";
  }
  return GENERIC_ERROR_TEXT;
}

/** Mesmos filtros do painel, no formato do corpo da mensagem (nomes da API). */
function explanationRef(metric: string, filters: OverviewFilters): AIExplanationRef {
  return { metric, filters: Object.fromEntries(new URLSearchParams(toQuery(filters))) };
}

/**
 * Conversa simples com a IA dentro do painel. Cada mensagem leva só
 * `{metric, filters}`: o servidor recalcula a explicação e a IA responde apenas
 * com ela. A conversa vale enquanto o painel está aberto.
 */
export function MetricExplanationChat({ metric, label, filters }: {
  metric: string;
  label: string;
  filters: OverviewFilters;
}) {
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [draft, setDraft] = useState("");
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const conversationRef = useRef<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [lines, draft]);

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || sending) return;
    setQuestion("");
    setDraft("");
    setError(null);
    setSending(true);
    setLines((current) => [...current, { id: nextId.current++, role: "user", content: text }]);
    const controller = new AbortController();
    controllerRef.current = controller;
    const onEvent = (item: AIStreamEvent) => {
      if (item.event === "delta") setDraft((current) => current + item.data.content);
      else if (item.event === "done") {
        setLines((current) => [...current, { id: nextId.current++, role: "assistant", content: item.data.message.content }]);
        setDraft("");
      } else if (item.event === "error") {
        setError(item.data.code === "rate_limit" ? RATE_LIMIT_TEXT : GENERIC_ERROR_TEXT);
        setDraft("");
      }
    };
    try {
      if (conversationRef.current === null) {
        conversationRef.current = (await aiApi.createConversation(`Explicação: ${label}`)).id;
      }
      await aiApi.sendMessage(conversationRef.current, text, onEvent, controller.signal, false, explanationRef(metric, filters));
    } catch (caught) {
      if (controller.signal.aborted) return;
      setError(errorText(caught));
      setDraft("");
    } finally {
      if (!controller.signal.aborted) setSending(false);
    }
  };

  return (
    <section className="mx-chat" aria-label="Perguntar à IA sobre este número">
      <h3 className="mx-chat__title">Perguntar à IA</h3>
      {lines.length || draft || sending ? (
        <div className="mx-chat__log" ref={logRef} aria-live="polite">
          {lines.map((line) => (
            <div key={line.id} className={`mx-chat__msg mx-chat__msg--${line.role}`}>
              {line.role === "assistant" ? <AssistantMarkdown content={line.content} /> : <p>{line.content}</p>}
            </div>
          ))}
          {draft ? <div className="mx-chat__msg mx-chat__msg--assistant"><AssistantMarkdown content={draft} /></div> : null}
          {sending && !draft ? <p className="mx-dim mx-chat__wait">Consultando a explicação…</p> : null}
        </div>
      ) : (
        <p className="mx-dim mx-chat__hint">A IA responde só com os dados desta explicação.</p>
      )}
      {error ? <p className="mx-chat__error" role="alert">{error}</p> : null}
      <form className="mx-chat__form" onSubmit={(event) => void send(event)}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ex.: por que o LASER1 está sem demanda?"
          aria-label="Pergunta para a IA"
          maxLength={2000}
          disabled={sending}
        />
        <button type="submit" disabled={sending || !question.trim()}>Enviar</button>
      </form>
    </section>
  );
}
