import { FormEvent, KeyboardEvent as ReactKeyboardEvent, useCallback, useEffect, useRef, useState } from "react";
import "../styles/ai.css";
import { aiApi } from "../api/ai";
import { api, ApiError } from "../api/client";
import { AssistantMarkdown } from "../components/AssistantMarkdown";
import { EmptyState, LoadingState } from "../components/DataState";
import { OperatorDialog } from "../components/OperatorDialog";
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
        <a className="button button--primary" href={artifact.download_url} download>Baixar Excel</a>
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

export function AIPage() {
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
  const countdown = formatCountdown(cooldownSeconds);
  const requestTooLarge = error?.code === "request_token_limit";
  const regularError = error && error.code !== "rate_limit" && !requestTooLarge ? error : null;

  if (loading) {
    return <PageFrame sectionId="home" title="IA Industrial" subtitle="Consulta segura aos dados canônicos do MES." filters={false}><LoadingState label="Verificando a IA…" /></PageFrame>;
  }

  if (!status?.enabled || !status.configured) {
    const title = !status?.enabled ? "IA Industrial desabilitada" : "IA não configurada";
    const detail = !status?.enabled
      ? "A disponibilidade desta função deve ser ativada pelo responsável pelo sistema."
      : "A configuração segura da IA ainda não foi concluída pelo responsável. O restante do Gestor continua disponível.";
    return (
      <PageFrame sectionId="home" title="IA Industrial" subtitle="Consulta segura aos dados canônicos do MES." filters={false}>
        <div className="ai-unavailable"><EmptyState title={title} detail={detail} /></div>
      </PageFrame>
    );
  }

  return (
    <PageFrame
      sectionId="home"
      title="IA Industrial"
      subtitle="Pergunte sobre fábrica, setor, recurso, OP, KPI, perdas e relatórios. A IA não executa ações produtivas."
      filters={false}
      actions={<span>Somente leitura • Dados oficiais</span>}
    >
      <div className="ai-workspace">
        <aside className="ai-conversations" aria-label="Conversas da IA">
          <button className="button button--primary ai-new-conversation" type="button" onClick={startNewConversation} disabled={streaming || creatingConversation}>
            Nova conversa
          </button>
          <div className="ai-conversation-list">
            {conversations.length ? conversations.map((conversation) => (
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
                  <span>{new Date(conversation.updated_at).toLocaleString("pt-BR")}</span>
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
            )) : <p>Nenhuma conversa iniciada.</p>}
          </div>
        </aside>

        <section className="ai-chat" aria-label="Conversa com a IA Industrial">
          <div className="ai-messages" aria-live="polite">
            {loadingConversation ? <LoadingState label="Carregando conversa…" /> : null}
            {!loadingConversation && !messages.length && !draft ? (
              <EmptyState title="Inicie uma consulta" detail="A IA buscará somente os dados oficiais necessários e autorizados." />
            ) : null}
            {messages.map((message) => (
              <article key={message.id} className={`ai-message ai-message--${message.role}`}>
                <strong>{message.role === "user" ? "Você" : "IA Industrial"}</strong>
                {message.role === "assistant" ? <AssistantMarkdown content={message.content} /> : <p>{message.content}</p>}
                {messageArtifacts(message).map((artifact) => <ReportArtifactCard key={artifact.id} artifact={artifact} />)}
              </article>
            ))}
            {draft ? (
              <article className="ai-message ai-message--assistant ai-message--streaming">
                <strong>IA Industrial</strong>
                <AssistantMarkdown content={draft} />
              </article>
            ) : null}
            {liveArtifacts.map((artifact) => <ReportArtifactCard key={artifact.id} artifact={artifact} />)}
          </div>

          {progress ? <div className="ai-progress" role="status"><span className={streaming ? "loading-dot" : ""} />{humanizeAssistantText(progress)}{timerRunning ? <time aria-label="Tempo da solicitação">{formatCountdown(requestElapsed)}</time> : null}</div> : null}
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

          <div className="ai-quick-actions" aria-label="Ações rápidas da IA">
            {QUICK_ACTIONS.map(([label, prompt]) => (
              <button key={label} type="button" onClick={() => void send(prompt)} disabled={streaming || creatingConversation || cooldownActive}>
                {label}
              </button>
            ))}
          </div>

          <form className="ai-composer" onSubmit={submit}>
            <label htmlFor="ai-question">Pergunta</label>
            <div>
              <textarea
                id="ai-question"
                value={question}
                onChange={(event) => {
                  setQuestion(event.target.value);
                  if (event.target.value !== cooldownRetryQuestion) setCooldownRetryQuestion(null);
                }}
                onKeyDown={handleQuestionKeyDown}
                placeholder={cooldownActive ? `IA disponível novamente em ${countdown}` : "Ex.: Como está a fábrica agora?"}
                maxLength={4000}
                disabled={streaming || creatingConversation || cooldownActive}
                aria-disabled={streaming || creatingConversation || cooldownActive}
                aria-describedby={cooldownActive ? "ai-cooldown-hint" : undefined}
              />
              {streaming ? (
                <button className="button" type="button" onClick={() => controllerRef.current?.abort()}>Cancelar</button>
              ) : (
                <button className="button button--primary" type="submit" disabled={!question.trim() || creatingConversation || cooldownActive}>Enviar</button>
              )}
            </div>
            <small id={cooldownActive ? "ai-cooldown-hint" : undefined}>{cooldownActive ? `IA disponível novamente em ${countdown} • ` : ""}Enter envia • Shift+Enter quebra a linha • {question.length}/4000 • Nenhuma alteração produtiva pode ser executada pela IA.</small>
          </form>
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
    </PageFrame>
  );
}
