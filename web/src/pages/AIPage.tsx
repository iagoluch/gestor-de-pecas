import { ComponentProps, FormEvent, KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import { aiApi } from "../api/ai";
import { api, ApiError } from "../api/client";
import { AssistantMarkdown } from "../components/AssistantMarkdown";
import { EmptyState, LoadingState } from "../components/DataState";
import { OperatorDialog } from "../components/OperatorDialog";
import { AIIcon } from "../components/AIIcon";
import { PageFrame } from "../components/PageFrame";
import { assets } from "../config/assets";
import type { AIConversation, AICooldown, AIMessage, AIReportArtifact, AIStatus, AIStreamEvent } from "../types/ai";
import { artifactStatusLabel, humanizeAssistantText, reportTypeLabel } from "../utils/assistantText";

const QUICK_ACTIONS = [
  ["Resumir fábrica", "Resuma a fábrica agora."],
  ["Resumir turno", "Resuma o turno atual usando somente o período e os dados canônicos disponíveis."],
  ["O que precisa da minha atenção?", "O que precisa da minha atenção agora?"],
  ["Analisar principais perdas", "Analise as principais perdas do período atual."],
  ["Gerar relatório", "Gere um relatório completo de hoje em Excel."],
] as const;

const DAY_MS = 86_400_000;

function conversationGroup(updatedAt: string): string {
  const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(new Date()) - startOfDay(new Date(updatedAt))) / DAY_MS);
  if (days <= 0) return "Hoje";
  if (days === 1) return "Ontem";
  if (days <= 7) return "Últimos 7 dias";
  return "Anteriores";
}

function conversationStamp(updatedAt: string): string {
  const date = new Date(updatedAt);
  return conversationGroup(updatedAt) === "Hoje"
    ? date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" }).replace(".", "");
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Sem permissão de área de transferência: o texto continua selecionável na tela.
    }
  };
  return (
    <button type="button" className="ai-message__action" onClick={() => void copy()} aria-label={copied ? "Resposta copiada" : "Copiar resposta"} title="Copiar resposta">
      <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {copied ? <path d="M5 12.5l4.5 4.5L19 7.5" /> : <><rect x="9" y="9" width="11" height="11" rx="2.5" /><path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15" /></>}
      </svg>
      {copied ? <span>Copiado</span> : null}
    </button>
  );
}

function formatFileSize(bytes?: number) {
  if (!bytes || bytes < 1024) return `${bytes ?? 0} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function messageArtifacts(message: AIMessage): AIReportArtifact[] {
  const raw = message.metadata?.artifacts;
  if (!Array.isArray(raw)) return [];
  return raw.filter((item): item is AIReportArtifact => Boolean(
    item && typeof item === "object" && typeof item.id === "string"
    && typeof item.download_url === "string" && typeof item.name === "string",
  ));
}

function ReportArtifactCard({ artifact }: { artifact: AIReportArtifact }) {
  const [sending, setSending] = useState(false);
  const [delivery, setDelivery] = useState<string | null>(null);
  const period = artifact.period_start && artifact.period_end
    ? `${new Date(artifact.period_start).toLocaleDateString("pt-BR")} a ${new Date(artifact.period_end).toLocaleDateString("pt-BR")}`
    : "Período informado no relatório";
  const sendToTelegram = async () => {
    if (!artifact.telegram_destination_id || sending) return;
    setSending(true);
    setDelivery(null);
    try {
      await api.post(`/api/v1/reports/artifacts/${artifact.id}/send`, {
        destination_id: artifact.telegram_destination_id,
      });
      setDelivery("Enviado ao destino configurado.");
    } catch (error) {
      setDelivery(error instanceof ApiError
        ? error.message
        : "Não foi possível enviar. O arquivo continua disponível para download.");
    } finally {
      setSending(false);
    }
  };
  return (
    <article className="ai-artifact" aria-label={`Relatório ${artifact.name}`}>
      <div>
        <strong>{artifact.name}</strong>
        <span>{reportTypeLabel(artifact.type)} • {period} • {formatFileSize(artifact.size_bytes)}</span>
        <small>{artifactStatusLabel(artifact.status)}</small>
      </div>
      <div className="ai-artifact__actions">
        <a className="button button--primary" href={artifact.download_url} download>Export técnico</a>
        {artifact.download_url_simples ? (
          <a className="button button--primary" href={artifact.download_url_simples} download>Export simples</a>
        ) : null}
        {artifact.telegram_available && artifact.telegram_destination_id ? (
          <button className="button" type="button" onClick={() => void sendToTelegram()} disabled={sending}>
            {sending ? "Enviando…" : "Enviar no Telegram"}
          </button>
        ) : null}
        {delivery ? <small role="status">{delivery}</small> : null}
      </div>
    </article>
  );
}

function controlledError(error: unknown) {
  if (error instanceof ApiError) return error;
  return new ApiError(500, {
    code: "ai_request_failed",
    message: "Não foi possível concluir a consulta da IA.",
  });
}

function errorCooldown(error: ApiError): AICooldown | null {
  if (error.code !== "rate_limit" || !error.details || typeof error.details !== "object") return null;
  const details = error.details as Record<string, unknown>;
  const blockedUntil = typeof details.blocked_until === "string" ? details.blocked_until : null;
  if (!blockedUntil) return null;
  return {
    active: true,
    retry_after_seconds: typeof details.retry_after_seconds === "number" ? details.retry_after_seconds : 0,
    blocked_until: blockedUntil,
  };
}

function remainingSeconds(blockedUntil: string): number {
  const timestamp = Date.parse(blockedUntil);
  if (!Number.isFinite(timestamp)) return 0;
  return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
}

function formatCountdown(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function EmbeddedFrame({ children }: ComponentProps<typeof PageFrame>) {
  return <div className="ai-embedded">{children}</div>;
}

export function AIPage({ embedded = false }: { embedded?: boolean } = {}) {
  const Frame = embedded ? EmbeddedFrame : PageFrame;
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [conversations, setConversations] = useState<AIConversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<AIMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [draft, setDraft] = useState("");
  const [progress, setProgress] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [deleteCandidate, setDeleteCandidate] = useState<AIConversation | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [timerRunning, setTimerRunning] = useState(false);
  const [requestElapsed, setRequestElapsed] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [retryQuestion, setRetryQuestion] = useState<string | null>(null);
  const [cooldownRetryQuestion, setCooldownRetryQuestion] = useState<string | null>(null);
  const [blockedUntil, setBlockedUntil] = useState<string | null>(null);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);
  const [rateLimitExpanded, setRateLimitExpanded] = useState(false);
  const [largeQueryExpanded, setLargeQueryExpanded] = useState(false);
  const [liveArtifacts, setLiveArtifacts] = useState<AIReportArtifact[]>([]);
  const controllerRef = useRef<AbortController | null>(null);
  const inflightQuestionRef = useRef("");
  const skipConversationLoadRef = useRef<number | null>(null);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);

  const applyCooldown = useCallback((cooldown?: AICooldown | null) => {
    if (cooldown?.active && cooldown.blocked_until) {
      setBlockedUntil(cooldown.blocked_until);
      setCooldownSeconds(Math.max(cooldown.retry_after_seconds, remainingSeconds(cooldown.blocked_until)));
      return;
    }
    setBlockedUntil(null);
    setCooldownSeconds(0);
    setRateLimitExpanded(false);
    setError((current) => current?.code === "rate_limit" ? null : current);
  }, []);

  const loadConversations = useCallback(async (signal?: AbortSignal) => {
    const payload = await aiApi.conversations(signal);
    setConversations(payload.items);
    return payload.items;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([aiApi.status(controller.signal), loadConversations(controller.signal)])
      .then(([nextStatus, items]) => {
        setStatus(nextStatus);
        applyCooldown(nextStatus.cooldown);
        if (items.length) setActiveId((current) => current ?? items[0].id);
      })
      .catch((nextError) => {
        if (nextError?.name !== "AbortError") setError(controlledError(nextError));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [applyCooldown, loadConversations]);

  useEffect(() => {
    if (!blockedUntil) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const tick = async () => {
      const remaining = remainingSeconds(blockedUntil);
      setCooldownSeconds(remaining);
      if (remaining > 0) {
        timer = setTimeout(() => void tick(), 1000);
        return;
      }
      try {
        const nextStatus = await aiApi.status(controller.signal);
        if (cancelled) return;
        setStatus(nextStatus);
        if (nextStatus.cooldown?.active && nextStatus.cooldown.blocked_until) {
          applyCooldown(nextStatus.cooldown);
        } else {
          applyCooldown(null);
        }
      } catch (nextError) {
        if (cancelled || (nextError as { name?: string })?.name === "AbortError") return;
        setCooldownSeconds(0);
        timer = setTimeout(() => void tick(), 1000);
      }
    };

    void tick();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [applyCooldown, blockedUntil]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      setLiveArtifacts([]);
      return;
    }
    if (skipConversationLoadRef.current === activeId) {
      skipConversationLoadRef.current = null;
      setMessages([]);
      return;
    }
    const controller = new AbortController();
    setLoadingConversation(true);
    setLiveArtifacts([]);
    setError(null);
    aiApi.conversation(activeId, controller.signal)
      .then((conversation) => setMessages(conversation.messages))
      .catch((nextError) => {
        if (nextError?.name !== "AbortError") setError(controlledError(nextError));
      })
      .finally(() => setLoadingConversation(false));
    return () => controller.abort();
  }, [activeId]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  // Acompanha a resposta só enquanto a pessoa está no fim da conversa; se rolou
  // para cima para reler, a tela não puxa de volta.
  useEffect(() => { stickToBottomRef.current = true; }, [activeId]);
  useEffect(() => {
    const el = messagesRef.current;
    if (el && stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, draft, progress, liveArtifacts, loadingConversation]);

  useEffect(() => {
    if (!timerRunning) {
      setRequestElapsed(0);
      return undefined;
    }
    const started = Date.now();
    setRequestElapsed(0);
    const timer = window.setInterval(() => {
      setRequestElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [timerRunning]);

  const newConversation = async () => {
    setError(null);
    setCreatingConversation(true);
    try {
      const created = await aiApi.createConversation();
      skipConversationLoadRef.current = created.id;
      setConversations((current) => [created, ...current]);
      setActiveId(created.id);
      setMessages([]);
      setLiveArtifacts([]);
      return created.id;
    } finally {
      setCreatingConversation(false);
    }
  };

  const startNewConversation = () => {
    void newConversation().catch((nextError) => setError(controlledError(nextError)));
  };

  const deleteConversation = async () => {
    if (!deleteCandidate || streaming || deletingId !== null) return;
    const target = deleteCandidate;
    setDeletingId(target.id);
    setError(null);
    try {
      await aiApi.deleteConversation(target.id);
      const remaining = conversations.filter((conversation) => conversation.id !== target.id);
      setConversations(remaining);
      if (activeId === target.id) {
        setActiveId(remaining[0]?.id ?? null);
        setMessages([]);
        setDraft("");
        setProgress("");
        setRetryQuestion(null);
        setCooldownRetryQuestion(null);
      }
      setDeleteCandidate(null);
    } catch (nextError) {
      setError(controlledError(nextError));
    } finally {
      setDeletingId(null);
    }
  };

  const handleStreamEvent = (event: AIStreamEvent) => {
    if (event.event === "status") {
      setProgress(event.data.message);
      if (event.data.user_message_id) {
        setMessages((current) => current.map((item) => item.id < 0 ? { ...item, id: event.data.user_message_id! } : item));
      }
    } else if (event.event === "delta") {
      setDraft((current) => current + event.data.content);
    } else if (event.event === "artifact") {
      setProgress("Relatório pronto");
      setLiveArtifacts((current) => current.some((item) => item.id === event.data.id)
        ? current : [...current, event.data]);
    } else if (event.event === "done") {
      setTimerRunning(false);
      setMessages((current) => [...current, event.data.message]);
      if (messageArtifacts(event.data.message).length) setLiveArtifacts([]);
      setDraft("");
      setProgress("");
      setRetryQuestion(null);
      setCooldownRetryQuestion(null);
    } else if (event.event === "error") {
      setTimerRunning(false);
      setProgress("");
      const nextError = new ApiError(event.data.code === "rate_limit" ? 429 : 502, {
        code: event.data.code,
        message: event.data.message,
        request_id: event.data.request_id,
        details: {
          retryable: event.data.retryable,
          retry_after_seconds: event.data.retry_after_seconds,
          blocked_until: event.data.blocked_until,
        },
      });
      setError(nextError);
      if (event.data.code === "rate_limit" && event.data.blocked_until) {
        applyCooldown({
          active: true,
          retry_after_seconds: event.data.retry_after_seconds ?? 0,
          blocked_until: event.data.blocked_until,
        });
        setQuestion(inflightQuestionRef.current);
        setCooldownRetryQuestion(inflightQuestionRef.current);
      }
      if (!event.data.retryable) setRetryQuestion(null);
    }
  };

  const send = async (text: string, retry = false) => {
    const clean = text.trim();
    if (!clean || streaming || creatingConversation || blockedUntil) return;
    let conversationId = activeId;
    let optimisticId: number | null = null;
    try {
      setError(null);
      inflightQuestionRef.current = clean;
      if (!conversationId) conversationId = await newConversation();
      if (!retry) {
        optimisticId = -Date.now();
        const optimistic: AIMessage = {
          id: optimisticId,
          conversation_id: conversationId,
          role: "user",
          content: clean,
          created_at: new Date().toISOString(),
        };
        setMessages((current) => [...current, optimistic]);
        setQuestion("");
      } else {
        setQuestion("");
      }
      setRetryQuestion(clean);
      setDraft("");
      setProgress("Preparando a consulta…");
      setStreaming(true);
      setTimerRunning(true);
      const controller = new AbortController();
      controllerRef.current = controller;
      await aiApi.sendMessage(conversationId, clean, handleStreamEvent, controller.signal, retry);
      await loadConversations();
    } catch (nextError: unknown) {
      if ((nextError as { name?: string })?.name === "AbortError") {
        setProgress("Consulta cancelada.");
      } else {
        const nextControlledError = controlledError(nextError);
        setError(nextControlledError);
        const cooldown = errorCooldown(nextControlledError);
        if (cooldown) {
          applyCooldown(cooldown);
          setQuestion(clean);
          setCooldownRetryQuestion(null);
          if (optimisticId !== null) {
            setMessages((current) => current.filter((item) => item.id !== optimisticId));
          }
          setProgress("");
        }
      }
    } finally {
      controllerRef.current = null;
      setTimerRunning(false);
      setStreaming(false);
    }
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (blockedUntil) return;
    void send(question, cooldownRetryQuestion === question);
  };

  const handleQuestionKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (blockedUntil) return;
    void send(question, cooldownRetryQuestion === question);
  };

  const cooldownActive = blockedUntil !== null;
  const conversationGroups = conversations.reduce<{ label: string; items: AIConversation[] }[]>((groups, conversation) => {
    const label = conversationGroup(conversation.updated_at);
    const last = groups[groups.length - 1];
    if (last?.label === label) last.items.push(conversation);
    else groups.push({ label, items: [conversation] });
    return groups;
  }, []);
  const conversationEmpty = !loadingConversation && !messages.length && !draft;
  const countdown = formatCountdown(cooldownSeconds);
  const requestTooLarge = error?.code === "request_token_limit";
  const regularError = error && error.code !== "rate_limit" && !requestTooLarge ? error : null;

  if (loading) {
    return <Frame sectionId="home" title="Tela inicial — IA" subtitle="Consulta segura aos dados canônicos do MES." filters={false}><LoadingState label="Verificando a IA…" /></Frame>;
  }

  if (!status?.enabled || !status.configured) {
    const title = !status?.enabled ? "IA Industrial desabilitada" : "IA não configurada";
    const detail = !status?.enabled
      ? "A disponibilidade desta função deve ser ativada pelo responsável pelo sistema."
      : "A configuração segura da IA ainda não foi concluída pelo responsável. O restante do Gestor continua disponível.";
    return (
      <Frame sectionId="home" title="Tela inicial — IA" subtitle="Consulta segura aos dados canônicos do MES." filters={false}>
        <div className="ai-unavailable"><EmptyState title={title} detail={detail} /></div>
      </Frame>
    );
  }

  return (
    <Frame
      sectionId="home"
      title="Tela inicial — IA"
      subtitle="Pergunte sobre fábrica, setor, recurso, OP, KPI, perdas e relatórios. A IA não executa ações produtivas."
      filters={false}
      actions={<span>Somente leitura • Dados oficiais</span>}
    >
      <div className={embedded ? "ai-workspace ai-workspace--embedded" : "ai-workspace"}>
        <aside className="ai-conversations" aria-label="Conversas da IA">
          <button className="button button--primary ai-new-conversation" type="button" onClick={startNewConversation} disabled={streaming || creatingConversation}>
            Nova conversa
          </button>
          <div className="ai-conversation-list">
            {conversations.length ? conversationGroups.map((group) => (
              <div key={group.label} className="ai-conversation-group">
                <h3>{group.label}</h3>
                {group.items.map((conversation) => (
                  <div
                    key={conversation.id}
                    className={conversation.id === activeId ? "ai-conversation ai-conversation--active" : "ai-conversation"}
                  >
                    <button
                      type="button"
                      className="ai-conversation__select"
                      onClick={() => setActiveId(conversation.id)}
                      disabled={streaming}
                    >
                      <strong>{conversation.title}</strong>
                      <span>{conversationStamp(conversation.updated_at)}</span>
                    </button>
                    <button
                      type="button"
                      className="ai-conversation__delete"
                      aria-label={`Excluir conversa: ${conversation.title}`}
                      title="Excluir conversa"
                      onClick={() => setDeleteCandidate(conversation)}
                      disabled={streaming || deletingId !== null}
                    >
                      <img src={assets.trash} alt="" aria-hidden="true" />
                    </button>
                  </div>
                ))}
              </div>
            )) : <p>Nenhuma conversa iniciada.</p>}
          </div>
        </aside>

        <section className="ai-chat" aria-label="Conversa com a IA Industrial">
          <div
            className="ai-messages"
            aria-live="polite"
            ref={messagesRef}
            onScroll={(event) => {
              const el = event.currentTarget;
              stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
            }}
          >
            <div className="ai-thread">
              {loadingConversation ? <LoadingState label="Carregando conversa…" /> : null}
              {conversationEmpty ? (
                <div className="ai-hero">
                  <span className="ai-hero__mark"><AIIcon /></span>
                  <h2>Como posso ajudar na fábrica hoje?</h2>
                  <p>Consulto somente os dados oficiais e autorizados. Não executo nenhuma ação produtiva.</p>
                  <div className="ai-quick-actions ai-quick-actions--cards" aria-label="Ações rápidas da IA">
                    {QUICK_ACTIONS.map(([label, prompt]) => (
                      <button key={label} type="button" onClick={() => void send(prompt)} disabled={streaming || creatingConversation || cooldownActive}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {messages.map((message) => message.role === "user" ? (
                <article key={message.id} className={message.id < 0 ? "ai-message ai-message--user ai-message--enter" : "ai-message ai-message--user"}>
                  <strong className="visually-hidden">Você</strong>
                  <p>{message.content}</p>
                </article>
              ) : (
                <article key={message.id} className="ai-message ai-message--assistant">
                  <span className="ai-message__avatar"><AIIcon /></span>
                  <div className="ai-message__body">
                    <strong className="visually-hidden">IA Industrial</strong>
                    <AssistantMarkdown content={message.content} />
                    {messageArtifacts(message).map((artifact) => <ReportArtifactCard key={artifact.id} artifact={artifact} />)}
                    <div className="ai-message__actions"><CopyButton text={humanizeAssistantText(message.content)} /></div>
                  </div>
                </article>
              ))}
              {draft ? (
                <article className="ai-message ai-message--assistant ai-message--streaming">
                  <span className="ai-message__avatar"><AIIcon /></span>
                  <div className="ai-message__body">
                    <strong className="visually-hidden">IA Industrial</strong>
                    <AssistantMarkdown content={draft} />
                  </div>
                </article>
              ) : null}
              {liveArtifacts.map((artifact) => <ReportArtifactCard key={artifact.id} artifact={artifact} />)}
              {progress ? <div className="ai-progress" role="status"><span className={streaming ? "loading-dot" : ""} /><span className="ai-progress__text">{humanizeAssistantText(progress)}</span>{timerRunning ? <time aria-label="Tempo da solicitação">{formatCountdown(requestElapsed)}</time> : null}</div> : null}
            </div>
          </div>

          <div className="ai-dock">
            {cooldownActive ? (
              <div className="ai-limit-notice" role="status" aria-live="polite">
                <div>
                  <strong>Limite temporário da IA atingido</strong>
                  <span aria-hidden="true">Nova pergunta disponível em {countdown}.</span>
                  <span className="visually-hidden">O envio de novas perguntas está temporariamente indisponível.</span>
                  <button type="button" aria-expanded={rateLimitExpanded} onClick={() => setRateLimitExpanded((current) => !current)}>Por que isso ocorreu?</button>
                  {rateLimitExpanded ? <p>A IA possui um limite de uso em pequenos períodos de tempo. Muitas perguntas ou análises grandes em sequência podem atingir esse limite. Isso é temporário e não afeta os dados do Gestor de Peças. Quando o contador terminar, você poderá perguntar novamente.</p> : null}
                </div>
              </div>
            ) : null}
            {requestTooLarge ? (
              <div className="ai-limit-notice" role="status">
                <div>
                  <strong>Esta consulta reuniu informações demais para serem analisadas de uma vez.</strong>
                  <span>Tente fazer uma pergunta mais específica, por exemplo sobre um setor, máquina, OP ou indicador.</span>
                  <button type="button" aria-expanded={largeQueryExpanded} onClick={() => setLargeQueryExpanded((current) => !current)}>Por que isso ocorreu?</button>
                  {largeQueryExpanded ? <p>A quantidade de informações necessária para responder foi maior do que a IA consegue processar nessa consulta. Seus dados não foram alterados. Uma pergunta mais específica normalmente resolve.</p> : null}
                </div>
              </div>
            ) : null}
            {regularError ? (
              <div className="ai-error" role="alert">
                <div><strong>Não foi possível concluir</strong><span>{humanizeAssistantText(regularError.message)}</span></div>
                {regularError.requestId ? <small>Referência: {regularError.requestId}</small> : null}
                {retryQuestion ? <button type="button" onClick={() => void send(retryQuestion, true)} disabled={streaming}>Tentar novamente</button> : null}
              </div>
            ) : null}

            {!conversationEmpty ? (
              <div className="ai-quick-actions" aria-label="Ações rápidas da IA">
                {QUICK_ACTIONS.map(([label, prompt]) => (
                  <button key={label} type="button" onClick={() => void send(prompt)} disabled={streaming || creatingConversation || cooldownActive}>
                    {label}
                  </button>
                ))}
              </div>
            ) : null}

            <form className="ai-composer" onSubmit={submit}>
              <label htmlFor="ai-question" className="visually-hidden">Pergunta</label>
              <div className="ai-composer__box">
                <textarea
                  id="ai-question"
                  rows={1}
                  value={question}
                  onChange={(event) => {
                    setQuestion(event.target.value);
                    if (event.target.value !== cooldownRetryQuestion) setCooldownRetryQuestion(null);
                  }}
                  onKeyDown={handleQuestionKeyDown}
                  placeholder={cooldownActive ? `IA disponível novamente em ${countdown}` : "Pergunte qualquer coisa sobre a fábrica…"}
                  maxLength={4000}
                  disabled={streaming || creatingConversation || cooldownActive}
                  aria-disabled={streaming || creatingConversation || cooldownActive}
                  aria-describedby={cooldownActive ? "ai-cooldown-hint" : undefined}
                />
                {streaming ? (
                  <button className="ai-composer__send ai-composer__send--stop" type="button" aria-label="Cancelar" title="Cancelar" onClick={() => controllerRef.current?.abort()}>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="3" /></svg>
                  </button>
                ) : (
                  <button className="ai-composer__send" type="submit" aria-label="Enviar" title="Enviar" disabled={!question.trim() || creatingConversation || cooldownActive}>
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5" /></svg>
                  </button>
                )}
              </div>
              <small id={cooldownActive ? "ai-cooldown-hint" : undefined}>{cooldownActive ? `IA disponível novamente em ${countdown} • ` : ""}Enter envia • Shift+Enter quebra a linha • {question.length}/4000 • Nenhuma alteração produtiva pode ser executada pela IA.</small>
            </form>
          </div>
        </section>
      </div>
      {deleteCandidate ? (
        <OperatorDialog
          title="Excluir conversa"
          size="compact"
          onCancel={() => deletingId === null && setDeleteCandidate(null)}
        >
          <div className="ai-delete-dialog__text">
            <p>Tem certeza de que deseja excluir esta conversa?</p>
            <strong>{deleteCandidate.title}</strong>
            <p>As mensagens desta conversa também serão removidas.</p>
          </div>
          <div className="operator-dialog__actions">
            <button type="button" onClick={() => setDeleteCandidate(null)} disabled={deletingId !== null}>Cancelar</button>
            <button type="button" className="button operator-danger" onClick={() => void deleteConversation()} disabled={deletingId !== null}>
              {deletingId !== null ? "Excluindo…" : "Excluir conversa"}
            </button>
          </div>
        </OperatorDialog>
      ) : null}
    </Frame>
  );
}
