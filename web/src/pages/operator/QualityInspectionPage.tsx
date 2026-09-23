import { useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { QualityDimension, QualityInspection } from "../../types/api";
import { formatMeasurement } from "../../utils/format";

export type MeasureStatus = "" | "CONFORME" | "NAO_CONFORME";
interface MeasureState { medida: string; status: MeasureStatus }

const NUMERO = /^[+-]?\d+(\.\d+)?$/;

/**
 * Wave 5.1 - a conformidade da cota e decidida pelo backend
 * (`limite_inferior <= medida <= limite_superior`). O operador informa apenas a
 * medida. Esta funcao NAO e uma segunda regra: ela apenas aplica os limites que
 * o backend ja enviou, para antecipar na tela o que sera gravado e para saber
 * se a RNC precisa ser aberta antes de salvar. O status persistido e sempre o
 * que o backend calcula ao registrar a peca.
 */
export function previewStatus(cota: QualityDimension, medida: string): MeasureStatus {
  if (!cota.conformidade_automatica) return "";
  const texto = medida.trim().replace(",", ".");
  if (!texto || !NUMERO.test(texto)) return "";
  const minimo = cota.limite_inferior;
  const maximo = cota.limite_superior;
  if (minimo === null || maximo === null) return "";
  const valor = Number(texto);
  return valor >= minimo && valor <= maximo ? "CONFORME" : "NAO_CONFORME";
}

export function rangeLabel(cota: QualityDimension): string {
  if (cota.limite_inferior === null || cota.limite_superior === null) return "";
  const minimo = formatMeasurement(String(cota.limite_inferior));
  const maximo = formatMeasurement(String(cota.limite_superior));
  return minimo + " a " + maximo + " mm";
}
type PieceResult = "" | "APROVADA" | "RETRABALHO" | "REFUGO";

export interface DraftDimension { sequencia: number; descricao: string; nominal: string; tolerancia: string }

export function formatDraftStandard(item: DraftDimension): string {
  return `${item.nominal.trim()} ± ${item.tolerancia.trim()}`;
}
interface OperatorBadge { cracha: string; nome: string; ativo?: boolean }

const RESULTS: { value: Exclude<PieceResult, "">; label: string; tone: string }[] = [
  { value: "APROVADA", label: "Aprovada", tone: "approved" },
  { value: "RETRABALHO", label: "Retrabalho", tone: "rework" },
  { value: "REFUGO", label: "Refugo", tone: "scrap" },
];

export function QualityInspectionPage({
  inspectionId,
  onBack,
  onFinished,
}: {
  inspectionId: number;
  onBack: () => void;
  onFinished: (message: string) => void;
}) {
  const inspection = useApiQuery<QualityInspection>(
    `/api/v1/quality/inspections/${inspectionId}`,
    { ignoreLiveTick: true },
  );
  const operators = useApiQuery<{ items: OperatorBadge[] }>("/api/v1/operator/operators");
  const [measures, setMeasures] = useState<Record<number, MeasureState>>({});
  const [result, setResult] = useState<PieceResult>("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [rnc, setRnc] = useState<{ motivo: string; observacao: string } | null>(null);
  const [rncOpen, setRncOpen] = useState(false);
  const [badgeDialog, setBadgeDialog] = useState(false);
  const [drafts, setDrafts] = useState<DraftDimension[] | null>(null);

  const data = inspection.data;
  const cotas = useMemo(() => data?.template?.cotas ?? [], [data]);
  const piece = data?.peca_atual ?? null;

  // O que o operador digitou é dado dele, não da tela. NADA vindo do servidor
  // limpa o checklist: só uma ação explícita do próprio operador faz isso —
  // salvar a peça (que avança para a próxima unidade) ou abrir outra inspeção.
  // Recarga em segundo plano, tick de realtime e revalidação nunca apagam.
  function limparChecklist() {
    setMeasures({});
    setResult("");
    setRnc(null);
  }

  useEffect(() => {
    limparChecklist();
    // Trocar de inspeção é a única mudança de contexto que zera o checklist.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inspectionId]);

  if (inspection.loading && !data) return <LoadingState label="Abrindo inspeção…" />;
  if (inspection.error && !data) return <ErrorState error={inspection.error} onRetry={inspection.reload} />;
  if (!data) return null;

  // Produto sem cotas cadastradas abre direto no cadastro, sem piscar o
  // checklist vazio. A primeira cota já vem montada, como manda a regra.
  const cadastrandoCotas = !data.template;
  const rascunhos = drafts ?? [{ sequencia: 1, descricao: "", nominal: "", tolerancia: "" }];

  const statusDaCota = (cota: QualityDimension): MeasureStatus => {
    const state = measures[cota.sequencia];
    if (!state?.medida.trim()) return "";
    return cota.conformidade_automatica ? previewStatus(cota, state.medida) : state.status;
  };
  const hasNonConforming = cotas.some((cota) => statusDaCota(cota) === "NAO_CONFORME");
  const allFilled = cotas.length > 0 && cotas.every((cota) => {
    const state = measures[cota.sequencia];
    if (!state?.medida.trim()) return false;
    // Com faixa numerica quem decide e o backend; sem faixa (template legado em
    // texto livre) o operador ainda precisa marcar o status.
    return cota.conformidade_automatica ? Boolean(statusDaCota(cota)) : Boolean(state.status);
  });
  const isLast = piece !== null && piece >= data.quantidade_total;
  const canSave = allFilled && result !== "" && (!hasNonConforming || Boolean(rnc)) && !saving;

  async function saveTemplate() {
    if (rascunhos.some((item) => !item.nominal.trim() || !item.tolerancia.trim())) {
      setMessage("Informe o padrão e a tolerância de todas as cotas antes de salvar.");
      return;
    }
    const rows = rascunhos.map((item, index) => ({
      sequencia: index + 1,
      descricao: item.descricao.trim() || null,
      padrao: formatDraftStandard(item),
      unidade: "mm",
    }));
    setSaving(true);
    try {
      await api.post("/api/v1/quality/templates", { produto: data!.produto, cotas: rows });
      setDrafts(null);
      setMessage("Cotas padrão salvas para este produto.");
      inspection.reload();
    } catch (reason) {
      setMessage(apiErrorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  async function savePiece(badges: string[]) {
    if (piece === null) return;
    setSaving(true);
    setMessage("");
    try {
      const response = await api.post<{ message: string; code: string }>(
        `/api/v1/quality/inspections/${inspectionId}/pieces`,
        {
          numero_peca: piece,
          resultado: result,
          medidas: cotas.map((cota) => ({
            sequencia: cota.sequencia,
            medida: measures[cota.sequencia].medida.trim(),
            status: statusDaCota(cota),
          })),
          rnc: rnc ? { motivo: rnc.motivo, observacao: rnc.observacao || null } : null,
          badges,
        },
      );
      setBadgeDialog(false);
      if (response.code === "inspecao_concluida") {
        onFinished(response.message);
        return;
      }
      // A peça foi gravada: agora sim o checklist da PRÓXIMA unidade começa
      // limpo, por decisão do operador que salvou — nunca por atualização.
      limparChecklist();
      setMessage(response.message);
      inspection.reload();
    } catch (reason) {
      setMessage(apiErrorMessage(reason));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="insp-inspection">
      <header className="insp-context">
        <div><small>OP</small><strong>{data.op}</strong></div>
        <div><small>Produto</small><strong>{data.produto_descricao || data.produto}</strong></div>
        <div><small>Progresso</small><strong>{piece === null ? `${data.pecas_registradas} de ${data.quantidade_total}` : `Peça ${piece} de ${data.quantidade_total}`}</strong></div>
      </header>

      <div className="insp-inspection__columns">
        <div className="insp-panel">
          {cadastrandoCotas ? (
            <TemplateEditor
              drafts={rascunhos}
              saving={saving}
              onChange={setDrafts}
              onSave={() => void saveTemplate()}
            />
          ) : (
            <>
              <h2>Checklist de cotas</h2>
              {cotas.length === 0 ? <EmptyState title="Produto sem cotas cadastradas" /> : (
                <div className="insp-table-wrapper">
                  <table className="insp-table insp-table--checklist">
                    <thead>
                      <tr>
                        <th scope="col">Cota</th>
                        <th scope="col">Padrão</th>
                        <th scope="col">Medida</th>
                        <th scope="col">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cotas.map((cota) => {
                        const state = measures[cota.sequencia] ?? { medida: "", status: "" as MeasureStatus };
                        const status = statusDaCota(cota);
                        const faixa = rangeLabel(cota);
                        return (
                          <tr key={cota.sequencia} className={status === "NAO_CONFORME" ? "is-non-conforming" : ""}>
                            <th scope="row">
                              <span className="insp-cota-number" aria-hidden="true">{cota.sequencia}</span>
                              <span>Cota {cota.sequencia}{cota.descricao ? <small>{cota.descricao}</small> : null}</span>
                            </th>
                            <td className="insp-standard">
                              {formatMeasurement(cota.padrao)} mm
                              {faixa ? <small className="insp-range">Faixa {faixa}</small> : null}
                            </td>
                            <td>
                              <input
                                aria-label={`Medida da cota ${cota.sequencia}`}
                                inputMode="decimal"
                                value={state.medida}
                                onChange={(event) => setMeasures({ ...measures, [cota.sequencia]: { ...state, medida: event.target.value } })}
                              />
                            </td>
                            <td>
                              {cota.conformidade_automatica ? (
                                <span
                                  aria-label={`Status da cota ${cota.sequencia}`}
                                  className={`insp-status-badge insp-status-badge--${status.toLowerCase() || "empty"}`}
                                >
                                  {status === "CONFORME" ? "Conforme" : status === "NAO_CONFORME" ? "Não conforme" : "Informe a medida"}
                                </span>
                              ) : (
                                <select
                                  aria-label={`Status da cota ${cota.sequencia}`}
                                  className={`insp-status-select insp-status-select--${state.status.toLowerCase() || "empty"}`}
                                  value={state.status}
                                  onChange={(event) => setMeasures({ ...measures, [cota.sequencia]: { ...state, status: event.target.value as MeasureStatus } })}
                                >
                                  <option value="">Selecionar</option>
                                  <option value="CONFORME">Conforme</option>
                                  <option value="NAO_CONFORME">Não conforme</option>
                                </select>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
              {data.template ? (
                <p className="insp-template-note">
                  Cotas padrão do produto (revisão {data.template.revisao}). O operador informa apenas a medida — a conformidade é calculada automaticamente pela faixa do padrão; alterar o padrão é atribuição de Supervisor ou Líder.
                </p>
              ) : null}

              <div className="insp-rnc-row">
                <button
                  type="button"
                  className="insp-rnc-button"
                  disabled={!hasNonConforming}
                  onClick={() => setRncOpen(true)}
                >
                  {rnc ? "RNC registrada — editar" : "Abrir RNC"}
                </button>
                <small>{hasNonConforming ? "Existe cota não conforme: a RNC é obrigatória para concluir a peça." : "RNC disponível somente quando houver cota não conforme."}</small>
              </div>

              <h2>Resultado da peça</h2>
              <div className="insp-results" role="group" aria-label="Resultado da peça">
                {RESULTS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    aria-pressed={result === option.value}
                    disabled={hasNonConforming && option.value === "APROVADA"}
                    className={`insp-result-button insp-result-button--${option.tone} ${result === option.value ? "is-selected" : ""}`}
                    onClick={() => setResult(option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              {message ? <p className="operator-notice" role="status">{message}</p> : null}

              <button
                type="button"
                className="insp-primary"
                disabled={!canSave}
                onClick={() => (isLast ? setBadgeDialog(true) : void savePiece([]))}
              >
                {isLast ? "Finalizar inspeção" : "Salvar e próxima peça"}
              </button>
              <button type="button" className="insp-back" onClick={onBack}>← Voltar</button>
            </>
          )}
        </div>

        <div className="insp-panel insp-panel--drawing">
          <h2>Desenho / PDF da peça</h2>
          {data.desenho ? (
            <>
              <div className="insp-drawing__meta">
                <strong>{data.desenho.filename}</strong>
                <small>Versão {data.desenho.versao}</small>
              </div>
              <object
                className="insp-drawing__viewer"
                data={`/api/v1/quality/drawings/${encodeURIComponent(data.produto)}/file#view=FitH`}
                type="application/pdf"
                aria-label={`Desenho do produto ${data.produto}`}
              >
                {/* Fallback só entra quando o dispositivo não possui visualizador
                    de PDF nativo. A inspeção nunca fica sem acesso ao desenho. */}
                <div className="insp-drawing__fallback">
                  <strong>Este dispositivo não possui visualizador de PDF embutido.</strong>
                  <a
                    className="insp-drawing__link"
                    href={`/api/v1/quality/drawings/${encodeURIComponent(data.produto)}/file`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Abrir o desenho em nova guia
                  </a>
                </div>
              </object>
            </>
          ) : (
            <EmptyState title="Nenhum desenho/PDF disponível para este produto." detail="A inspeção continua liberada." />
          )}
        </div>
      </div>

      {rncOpen ? (
        <RncDialog
          inspection={data}
          piece={piece}
          cotas={cotas.filter((cota) => statusDaCota(cota) === "NAO_CONFORME")}
          measures={measures}
          initial={rnc}
          onCancel={() => setRncOpen(false)}
          onConfirm={(value) => {
            setRnc(value);
            setRncOpen(false);
            if (result === "APROVADA") setResult("");
          }}
        />
      ) : null}

      {badgeDialog ? (
        <BadgeDialog
          operators={operators.data?.items ?? []}
          saving={saving}
          onCancel={() => setBadgeDialog(false)}
          onConfirm={(badges) => void savePiece(badges)}
        />
      ) : null}
    </section>
  );
}

export function TemplateEditor({
  drafts,
  saving,
  onChange,
  onSave,
}: {
  drafts: DraftDimension[];
  saving: boolean;
  onChange: (value: DraftDimension[]) => void;
  onSave: () => void;
}) {
  return (
    <>
      <h2>Cadastro das cotas do produto</h2>
      <p className="insp-template-note">
        Este produto ainda não possui cotas cadastradas. Informe os padrões que a peça deveria possuir; eles serão reutilizados nas próximas inspeções.
      </p>
      <div className="insp-template-editor">
        {drafts.map((item, index) => (
          <fieldset key={index}>
            <legend>Cota {index + 1}</legend>
            <label>Descrição (opcional)<input value={item.descricao} onChange={(event) => onChange(drafts.map((row, position) => position === index ? { ...row, descricao: event.target.value } : row))} /></label>
            <label>Padrão
              <span className="insp-tolerance-input">
                <input aria-label={`Padrão nominal da cota ${index + 1}`} placeholder="125,0" value={item.nominal} onChange={(event) => onChange(drafts.map((row, position) => position === index ? { ...row, nominal: event.target.value } : row))} />
                <span aria-hidden="true">±</span>
                <input aria-label={`Tolerância da cota ${index + 1}`} placeholder="0,5" value={item.tolerancia} onChange={(event) => onChange(drafts.map((row, position) => position === index ? { ...row, tolerancia: event.target.value } : row))} />
              </span>
            </label>
            <div className="insp-fixed-unit"><span>Unidade</span><strong>mm</strong></div>
            {drafts.length > 1 ? <button type="button" className="insp-remove" onClick={() => onChange(drafts.filter((_row, position) => position !== index))}>Remover</button> : null}
          </fieldset>
        ))}
      </div>
      <button
        type="button"
        className="insp-add"
        onClick={() => onChange([...drafts, { sequencia: drafts.length + 1, descricao: "", nominal: "", tolerancia: "" }])}
      >
        + Adicionar cota
      </button>
      <button type="button" className="insp-primary" disabled={saving} onClick={onSave}>Salvar cotas do produto</button>
    </>
  );
}

function RncDialog({
  inspection,
  piece,
  cotas,
  measures,
  initial,
  onCancel,
  onConfirm,
}: {
  inspection: QualityInspection;
  piece: number | null;
  cotas: QualityDimension[];
  measures: Record<number, MeasureState>;
  initial: { motivo: string; observacao: string } | null;
  onCancel: () => void;
  onConfirm: (value: { motivo: string; observacao: string }) => void;
}) {
  const [motivo, setMotivo] = useState(initial?.motivo ?? "");
  const [observacao, setObservacao] = useState(initial?.observacao ?? "");
  return (
    <OperatorDialog title="RNC — Relatório de Não Conformidade" size="wide" onCancel={onCancel}>
      <div className="insp-rnc-summary">
        <div><small>OP</small><strong>{inspection.op}</strong></div>
        <div><small>Produto</small><strong>{inspection.produto}</strong></div>
        <div><small>Peça</small><strong>{piece ?? "—"} de {inspection.quantidade_total}</strong></div>
        <div><small>Recurso</small><strong>{inspection.recurso}</strong></div>
        <div><small>Operador</small><strong>{inspection.operador}</strong></div>
      </div>
      <table className="insp-table">
        <thead><tr><th scope="col">Cota</th><th scope="col">Padrão</th><th scope="col">Medida adquirida</th></tr></thead>
        <tbody>
          {cotas.map((cota) => (
            <tr key={cota.sequencia}>
              <td>Cota {cota.sequencia}{cota.descricao ? ` — ${cota.descricao}` : ""}</td>
              <td>{formatMeasurement(cota.padrao)} mm</td>
              <td>{measures[cota.sequencia]?.medida}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <label>Motivo / descrição da não conformidade<textarea value={motivo} onChange={(event) => setMotivo(event.target.value)} /></label>
      <label>Observação (opcional)<textarea value={observacao} onChange={(event) => setObservacao(event.target.value)} /></label>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>Cancelar</button>
        <button type="button" className="button button--primary" disabled={motivo.trim().length < 3} onClick={() => onConfirm({ motivo: motivo.trim(), observacao: observacao.trim() })}>Registrar RNC</button>
      </div>
    </OperatorDialog>
  );
}

function BadgeDialog({
  operators,
  saving,
  onCancel,
  onConfirm,
}: {
  operators: OperatorBadge[];
  saving: boolean;
  onCancel: () => void;
  onConfirm: (badges: string[]) => void;
}) {
  const [badge, setBadge] = useState("");
  const [badges, setBadges] = useState<string[]>([]);
  const [error, setError] = useState("");
  function add() {
    const value = badge.trim();
    if (!value) return;
    if (!operators.find((item) => item.cracha === value && item.ativo !== false)) {
      setError("Crachá não cadastrado ou inativo.");
      return;
    }
    setBadges((current) => current.includes(value) ? current : [...current, value]);
    setBadge("");
    setError("");
  }
  return (
    <OperatorDialog title="Finalizar inspeção" onCancel={onCancel}>
      <p className="operator-help">A última peça fecha a operação de inspeção no roteiro. Informe o crachá do operador responsável.</p>
      <label>Crachá do operador<div className="operator-badge-entry"><input value={badge} autoFocus onChange={(event) => setBadge(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} /><button type="button" aria-label="Adicionar operador" onClick={add}>+</button></div></label>
      {error ? <p className="form-error">{error}</p> : null}
      <div className="operator-badge-list" aria-label="Operadores adicionados">
        {badges.length ? badges.map((item) => {
          const operator = operators.find((candidate) => candidate.cracha === item);
          return <div key={item}><span><strong>{operator?.nome ?? item}</strong><small>Crachá {item}</small></span><button type="button" aria-label={`Remover ${operator?.nome ?? item}`} onClick={() => setBadges((current) => current.filter((value) => value !== item))}>×</button></div>;
        }) : <p>Nenhum operador adicionado.</p>}
      </div>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>Cancelar</button>
        <button type="button" className="button button--primary" disabled={!badges.length || saving} onClick={() => onConfirm(badges)}>Concluir inspeção</button>
      </div>
    </OperatorDialog>
  );
}
