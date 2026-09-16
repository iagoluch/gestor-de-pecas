import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { OperatorDialog } from "./OperatorDialog";

interface ChamadaContato {
  id: number;
  nome: string;
  funcao: string;
}

interface ChamadaResult {
  ok: boolean;
  telegram_enviado: boolean;
}

type Passo = "form" | "enviando" | "sucesso" | "erro";
type Variante = "operador" | "gestao";

interface ChamadaButtonProps {
  variant?: Variante;
  sector?: string | null;
  /** Valores contextuais sugeridos pelo posto; continuam editáveis no formulário. */
  defaultReason?: string;
  defaultComment?: string;
  /** Uso dentro de um diálogo operacional, sem o botão flutuante. */
  inline?: boolean;
  label?: string;
}

const DEBOUNCE_MS = 250;

/**
 * Botão de chamada — mesmo componente para o operador e para a gestão
 * (decisão do usuário, 14/09/2026). Fica fixo no canto, sobre o conteúdo da
 * tela, sem disputar espaço com a navegação.
 *
 * A variante muda dois pontos, porque o login costuma ser compartilhado dos
 * dois lados e alguém precisa saber quem de fato chamou:
 * - "gestao": pré-seleciona o contato padrão (cadastrado na tela de
 *   Contatos de chamada — ainda dá pra trocar) e pede nome + e-mail de quem
 *   está chamando;
 * - "operador" (padrão): abre a busca vazia e pede o crachá de quem chama.
 */
export function ChamadaButton({
  variant = "operador",
  sector,
  defaultReason = "",
  defaultComment = "",
  inline = false,
  label,
}: ChamadaButtonProps) {
  const gestao = variant === "gestao";
  const [aberto, setAberto] = useState(false);
  const [passo, setPasso] = useState<Passo>("form");
  const [motivos, setMotivos] = useState<string[]>([]);
  const [busca, setBusca] = useState("");
  const [opcoes, setOpcoes] = useState<ChamadaContato[]>([]);
  const [buscando, setBuscando] = useState(false);
  const [contato, setContato] = useState<ChamadaContato | null>(null);
  const [motivo, setMotivo] = useState("");
  const [comentario, setComentario] = useState("");
  const [cracha, setCracha] = useState("");
  const [nomeSolicitante, setNomeSolicitante] = useState("");
  const [emailSolicitante, setEmailSolicitante] = useState("");
  const [avisoEnviado, setAvisoEnviado] = useState(false);
  const [erro, setErro] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!aberto) return;
    api.get<{ items: string[] }>("/api/v1/chamadas/motivos")
      .then((response) => setMotivos(response.items))
      .catch(() => setMotivos([]));
  }, [aberto]);

  useEffect(() => {
    if (!aberto || !gestao) return;
    api.get<{ item: ChamadaContato | null }>("/api/v1/chamadas/contato-padrao-gestao")
      .then((response) => {
        if (response.item) setContato(response.item);
      })
      .catch(() => undefined);
    // Só na abertura: se o gestor trocar o contato depois, não queremos
    // sobrescrever a escolha dele.
  }, [aberto, gestao]);

  useEffect(() => {
    if (!aberto || contato) return undefined;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setBuscando(true);
    debounceRef.current = setTimeout(() => {
      const params = new URLSearchParams();
      if (busca.trim()) params.set("q", busca.trim());
      if (sector) params.set("setor", sector);
      const query = params.toString() ? `?${params.toString()}` : "";
      api.get<{ items: ChamadaContato[] }>(`/api/v1/chamadas/contatos${query}`)
        .then((response) => setOpcoes(response.items))
        .catch(() => setOpcoes([]))
        .finally(() => setBuscando(false));
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [aberto, busca, contato, sector]);

  function reiniciar() {
    setPasso("form");
    setBusca("");
    setOpcoes([]);
    setContato(null);
    setMotivo(defaultReason);
    setComentario(defaultComment);
    setCracha("");
    setNomeSolicitante("");
    setEmailSolicitante("");
    setErro("");
  }

  function abrir() {
    reiniciar();
    setAberto(true);
  }

  function fechar() {
    setAberto(false);
    reiniciar();
  }

  async function enviar() {
    if (!podeEnviar || !contato) return;
    setPasso("enviando");
    setErro("");
    try {
      const resultado = await api.post<ChamadaResult>("/api/v1/chamadas", {
        contato_id: contato.id,
        motivo,
        comentario: comentario.trim(),
        ...(gestao
          ? { solicitante_nome_manual: nomeSolicitante.trim(), solicitante_email: emailSolicitante.trim() }
          : { solicitante_cracha: cracha.trim() }),
      });
      setAvisoEnviado(resultado.telegram_enviado);
      setPasso("sucesso");
    } catch (reason) {
      setErro(reason instanceof ApiError ? reason.message : "Não foi possível registrar a chamada.");
      setPasso("erro");
    }
  }

  const identificacaoOk = gestao
    ? Boolean(nomeSolicitante.trim() && emailSolicitante.trim())
    : Boolean(cracha.trim());
  const podeEnviar = Boolean(contato && motivo && comentario.trim() && identificacaoOk);

  return (
    <>
      <button
        type="button"
        className={inline ? "button chamada-trigger" : "chamada-fab"}
        onClick={abrir}
        aria-label={label ?? "Chamar alguém"}
        title={label ?? "Chamar alguém"}
      >
        <ChamadaIcon />
        <span className={inline ? undefined : "chamada-fab__label"}>{label ?? "Chamar"}</span>
      </button>

      {aberto ? (
        <OperatorDialog title="Chamar alguém" onCancel={fechar} size="compact">
          {passo === "sucesso" ? (
            <div className="chamada-feedback chamada-feedback--ok">
              <strong>Chamada registrada.</strong>
              <p>
                {avisoEnviado
                  ? "O aviso foi enviado pelo Telegram."
                  : "O aviso pelo Telegram não pôde ser enviado agora, mas a chamada ficou registrada — avise pessoalmente se for urgente."}
              </p>
              <div className="operator-dialog__actions">
                <button type="button" className="button button--primary" onClick={fechar}>Fechar</button>
              </div>
            </div>
          ) : (
            <form
              className="chamada-form"
              onSubmit={(event) => {
                event.preventDefault();
                void enviar();
              }}
            >
              <div className="chamada-field">
                <span className="chamada-field__label">Quem você quer chamar?</span>
                {contato ? (
                  <div className="chamada-selected">
                    <span>{contato.nome} <small>({contato.funcao})</small></span>
                    <button type="button" onClick={() => setContato(null)} disabled={passo === "enviando"}>
                      Trocar
                    </button>
                  </div>
                ) : (
                  <>
                    <input
                      value={busca}
                      onChange={(event) => setBusca(event.target.value)}
                      placeholder="Buscar por nome ou função…"
                      aria-label="Quem você quer chamar?"
                      autoFocus
                      autoComplete="off"
                    />
                    <div className="chamada-options" role="listbox" aria-label="Contatos encontrados">
                      {buscando ? (
                        <span className="chamada-options__empty">Buscando…</span>
                      ) : opcoes.length ? (
                        opcoes.map((item) => (
                          <button
                            type="button"
                            key={item.id}
                            className="chamada-option"
                            role="option"
                            onClick={() => setContato(item)}
                          >
                            {item.nome} <small>({item.funcao})</small>
                          </button>
                        ))
                      ) : (
                        <span className="chamada-options__empty">
                          {busca.trim() ? "Ninguém encontrado com esse termo." : "Nenhum contato cadastrado ainda."}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>

              <label>
                Motivo
                <select value={motivo} onChange={(event) => setMotivo(event.target.value)} required>
                  <option value="" disabled>Selecione um motivo</option>
                  {motivos.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </label>

              <label>
                Comentário
                <textarea
                  value={comentario}
                  onChange={(event) => setComentario(event.target.value)}
                  placeholder="Descreva rapidamente o que está acontecendo…"
                  required
                />
              </label>

              {gestao ? (
                <div className="chamada-identificacao">
                  <label>
                    Seu nome
                    <input
                      value={nomeSolicitante}
                      onChange={(event) => setNomeSolicitante(event.target.value)}
                      placeholder="Nome de quem está chamando"
                      required
                    />
                  </label>
                  <label>
                    Seu e-mail
                    <input
                      type="email"
                      value={emailSolicitante}
                      onChange={(event) => setEmailSolicitante(event.target.value)}
                      placeholder="seu.email@empresa.com"
                      required
                    />
                  </label>
                </div>
              ) : (
                <label>
                  Seu crachá
                  <input
                    value={cracha}
                    onChange={(event) => setCracha(event.target.value)}
                    placeholder="Número do crachá"
                    required
                  />
                </label>
              )}

              {passo === "erro" ? <p className="operator-notice operator-notice--danger" role="alert">{erro}</p> : null}

              <div className="operator-dialog__actions">
                <button type="button" onClick={fechar} disabled={passo === "enviando"}>Cancelar</button>
                <button type="submit" className="button button--primary" disabled={!podeEnviar || passo === "enviando"}>
                  {passo === "enviando" ? "Enviando…" : "Chamar"}
                </button>
              </div>
            </form>
          )}
        </OperatorDialog>
      ) : null}
    </>
  );
}

function ChamadaIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" aria-hidden="true">
      <path
        d="M9 18a3 3 0 0 0 6 0M4.5 9.5a7.5 7.5 0 0 1 15 0c0 4 1.5 5 1.5 5h-18s1.5-1 1.5-5Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
