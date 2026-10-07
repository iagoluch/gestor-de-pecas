import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import { EmptyState, LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import type { NoticeTone } from "../../components/Notice";
import { OperatorDialog } from "../../components/OperatorDialog";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { QualityDimension, QualityTemplate } from "../../types/api";
import type { QualityTemplateListResponse, QualityTemplateRow } from "../../types/qualityTemplates";
import { formatDateTime, formatNumber } from "../../utils/format";
import { TemplateEditor, formatDraftStandard } from "../operator/QualityInspectionPage";
import type { DraftDimension } from "../operator/QualityInspectionPage";

const LIST_API = "/api/v1/management/quality-templates";
const TEMPLATE_API = "/api/v1/quality/templates";
const PAGE_SIZE = 100;

const TITLE = "Produção — Qualidade";
const SUBTITLE = "Consulte e ajuste as cotas padrão de cada produto. Cada alteração gera uma nova revisão e vale para as próximas inspeções.";

/** Mensagem humana por `code`; nunca o código técnico. */
const ERROR_MESSAGES: Record<string, string> = {
  quality_templates_access_denied: "Seu perfil não tem acesso às cotas padrão. Só a Qualidade e a administração usam esta tela.",
  quality_sector_unavailable: "Seu perfil não tem acesso às cotas padrão. Só a Qualidade e a administração usam esta tela.",
  qualidade_produto_obrigatorio: "Informe o código do produto.",
  qualidade_cotas_obrigatorias: "Informe ao menos a Cota 1 com o padrão da peça.",
  qualidade_cota_sequencia_invalida: "A numeração das cotas é inválida. Feche e abra o produto de novo.",
  qualidade_cota_duplicada: "Há cotas repetidas. Feche e abra o produto de novo.",
  qualidade_cota_padrao_obrigatorio: "Informe o padrão e a tolerância de todas as cotas.",
  qualidade_template_protegido: "As cotas deste produto só podem ser alteradas pela Qualidade ou pela administração.",
  validation_error: "Alguma informação está inválida. Confira o código do produto e os valores das cotas.",
  network_error: "Não foi possível acessar o servidor. Tente novamente.",
};

export function qualityTemplateErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) return ERROR_MESSAGES[reason.code] ?? "Não foi possível concluir a operação. Tente novamente.";
  return ERROR_MESSAGES.network_error;
}

const SEPARATORS = ["+/-", "+-", "±"];
const NUMERIC = /^[+-]?\d+(?:[.,]\d+)?$/;

/**
 * Devolve a cota cadastrada ao formato do editor (padrão + tolerância). É só
 * apresentação do texto salvo: a conformidade continua sendo do backend.
 * Padrão sem margem ("453") vale margem zero, como no servidor.
 */
export function draftFromCota(cota: QualityDimension, index: number): DraftDimension {
  const padrao = (cota.padrao ?? "").trim();
  const separator = SEPARATORS.find((item) => padrao.includes(item));
  const base = { sequencia: index + 1, descricao: cota.descricao ?? "" };
  if (separator) {
    const [nominal, ...rest] = padrao.split(separator);
    return { ...base, nominal: nominal.trim(), tolerancia: rest.join(separator).trim() };
  }
  return { ...base, nominal: padrao, tolerancia: NUMERIC.test(padrao) ? "0" : "" };
}

const emptyDrafts = (): DraftDimension[] => [{ sequencia: 1, descricao: "", nominal: "", tolerancia: "" }];

interface Feedback {
  tone: NoticeTone;
  text: string;
}

/** Produto aberto no editor: `null` fecha, `""` é o cadastro de produto novo. */
type Editing = string | null;

export function QualityTemplatesPage() {
  const [produto, setProduto] = useState("");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const debouncedProduto = useDebouncedValue(produto.trim());

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (debouncedProduto) params.set("produto", debouncedProduto);
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    return `${LIST_API}?${params.toString()}`;
  }, [debouncedProduto, offset]);
  const query = useApiQuery<QualityTemplateListResponse>(path, { ignoreLiveTick: true });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  const changeProduto = (value: string) => {
    setProduto(value);
    setOffset(0);
    setFeedback(null);
  };

  const header = (
    <button type="button" className="button button--primary" onClick={() => { setFeedback(null); setEditing(""); }}>
      Cadastrar produto
    </button>
  );

  return (
    <PageFrame sectionId="production" title={TITLE} subtitle={SUBTITLE} filters={false} actions={header} staleError={query.data ? query.error : null}>
      {feedback ? <Notice tone={feedback.tone}>{feedback.text}</Notice> : null}

      <div className="record-toolbar" role="search" aria-label="Filtros das cotas padrão">
        <div className="record-toolbar__fields">
          <label htmlFor="qt-produto">
            Produto
            <input id="qt-produto" className="std-time__filter-input" value={produto} placeholder="Código do produto"
              onChange={(event) => changeProduto(event.target.value)} />
          </label>
        </div>
        <div className="record-toolbar__meta">
          <span className="record-toolbar__summary">{query.data ? `${formatNumber(total)} produto(s) com cotas` : ""}</span>
          <button type="button" className="record-toolbar__reset" onClick={() => changeProduto("")} disabled={!produto}>
            Limpar filtros
          </button>
        </div>
      </div>

      <SectionCard
        title="Produtos com cotas padrão"
        className="content-section section-card--table"
        action={<span className="section-count">{query.data ? `${formatNumber(total)} no total` : ""}</span>}
      >
        {query.loading && !query.data ? <LoadingState /> : null}
        {query.error && !query.data ? (
          <div className="state-box state-box--error" role="alert">
            <strong>Não foi possível carregar as cotas</strong>
            <span>{qualityTemplateErrorMessage(query.error)}</span>
            <button type="button" onClick={query.reload}>Tentar novamente</button>
          </div>
        ) : null}
        {query.data && !items.length ? (
          <EmptyState
            title={debouncedProduto ? "Nenhum produto neste filtro" : "Nenhum produto com cotas cadastradas"}
            detail={debouncedProduto
              ? "Confira o código do produto ou use “Cadastrar produto” para criar as cotas dele."
              : "Use “Cadastrar produto” para criar as cotas padrão do primeiro produto."}
          />
        ) : null}
        {query.data && items.length ? (
          <>
            <DataTable
              rows={items}
              rowKey={(row) => row.produto_codigo}
              columns={[
                {
                  key: "produto",
                  label: "Produto",
                  sticky: true,
                  render: (row) => (
                    <button type="button" className="qt-product" aria-label={`Abrir cotas de ${row.produto_codigo}`} onClick={() => { setFeedback(null); setEditing(row.produto_codigo); }}>
                      <strong>{row.produto_codigo}</strong>
                      {!row.ativo ? <small>Inativo</small> : null}
                    </button>
                  ),
                },
                { key: "descricao", label: "Descrição", render: (row) => row.produto_descricao || "—" },
                { key: "revisao", label: "Revisão", render: (row) => `Rev. ${row.revisao}` },
                { key: "cotas", label: "Cotas", render: (row) => formatNumber(row.quantidade_cotas) },
                { key: "por", label: "Atualizado por", render: (row) => row.atualizado_por || "—" },
                { key: "em", label: "Atualizado em", render: (row) => (row.atualizado_em ? formatDateTime(row.atualizado_em) : "—") },
                {
                  key: "acoes",
                  label: "Ações",
                  render: (row: QualityTemplateRow) => (
                    <button type="button" aria-label={`Editar cotas de ${row.produto_codigo}`} onClick={() => { setFeedback(null); setEditing(row.produto_codigo); }}>
                      Editar
                    </button>
                  ),
                },
              ]}
            />
            <Pagination offset={offset} count={items.length} total={total} onChange={setOffset} />
          </>
        ) : null}
      </SectionCard>

      {editing !== null ? (
        <TemplateDialog
          initialProduto={editing}
          onClose={() => setEditing(null)}
          onSaved={(text) => {
            setEditing(null);
            setFeedback({ tone: "success", text });
            query.reload();
          }}
        />
      ) : null}
    </PageFrame>
  );
}

function Pagination({ offset, count, total, onChange }: { offset: number; count: number; total: number; onChange: (offset: number) => void }) {
  if (total <= PAGE_SIZE) return null;
  const first = offset + 1;
  const last = offset + count;
  return (
    <nav className="insp-pagination std-time__pagination" aria-label="Paginação das cotas padrão">
      <span className="section-count">{`Mostrando ${formatNumber(first)}–${formatNumber(last)} de ${formatNumber(total)}`}</span>
      <button type="button" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>Anterior</button>
      <button type="button" disabled={last >= total} onClick={() => onChange(offset + PAGE_SIZE)}>Próxima</button>
    </nav>
  );
}

interface TemplateLookup {
  produto: string;
  template: QualityTemplate | null;
  can_edit: boolean;
}

/**
 * Editor das cotas de um produto. Com `initialProduto` vazio é o cadastro de
 * produto novo: pede o código e, se o produto já tiver cotas, abre-as para
 * edição em vez de sobrescrevê-las sem aviso.
 */
function TemplateDialog({ initialProduto, onClose, onSaved }: {
  initialProduto: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const isNew = initialProduto === "";
  const [produto, setProduto] = useState(initialProduto);
  const [code, setCode] = useState("");
  const [drafts, setDrafts] = useState<DraftDimension[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const lookup = useApiQuery<TemplateLookup>(produto ? `${TEMPLATE_API}/${encodeURIComponent(produto)}` : null, { ignoreLiveTick: true });
  const template = lookup.data?.template ?? null;

  // Os rascunhos nascem uma vez, do que está salvo; recarga em segundo plano
  // nunca apaga o que a pessoa já digitou.
  useEffect(() => {
    if (lookup.data && drafts === null) {
      setDrafts(lookup.data.template ? lookup.data.template.cotas.map(draftFromCota) : emptyDrafts());
    }
  }, [lookup.data, drafts]);

  function chooseProduto(event: FormEvent) {
    event.preventDefault();
    const value = code.trim();
    if (value) setProduto(value);
  }

  async function save() {
    if (!drafts || saving) return;
    setSaving(true);
    setError("");
    try {
      await api.post(TEMPLATE_API, {
        produto,
        cotas: drafts.map((item, index) => ({
          sequencia: index + 1,
          descricao: item.descricao.trim() || null,
          padrao: formatDraftStandard(item),
          unidade: "mm",
        })),
      });
      onSaved(template
        ? `Cotas padrão de ${produto} atualizadas: revisão ${template.revisao + 1}.`
        : `Cotas padrão de ${produto} cadastradas.`);
    } catch (reason) {
      setError(qualityTemplateErrorMessage(reason));
      setSaving(false);
    }
  }

  const title = produto ? `Cotas padrão — ${produto}` : "Cadastrar produto";
  return (
    <OperatorDialog title={title} onCancel={onClose} size="wide">
      {!produto ? (
        <form onSubmit={chooseProduto} noValidate>
          <label className="qt-code">
            Código do produto
            <input value={code} autoFocus maxLength={60} autoComplete="off" onChange={(event) => setCode(event.target.value)} />
          </label>
          <div className="operator-dialog__actions">
            <button type="button" onClick={onClose}>Cancelar</button>
            <button type="submit" className="button button--primary" disabled={!code.trim()}>Continuar</button>
          </div>
        </form>
      ) : null}

      {produto && lookup.loading && !lookup.data ? <LoadingState label="Abrindo cotas…" /> : null}
      {produto && lookup.error && !lookup.data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível abrir as cotas</strong>
          <span>{qualityTemplateErrorMessage(lookup.error)}</span>
          <button type="button" onClick={lookup.reload}>Tentar novamente</button>
        </div>
      ) : null}

      {drafts ? (
        <>
          {template ? (
            <Notice>
              {isNew ? `O produto ${produto} já tinha cotas cadastradas; você está editando. ` : ""}
              {`Revisão atual: ${template.revisao}. Ao salvar, é criada a revisão ${template.revisao + 1}, usada nas próximas inspeções.`}
            </Notice>
          ) : null}
          {error ? <Notice tone="error">{error}</Notice> : null}
          <TemplateEditor
            drafts={drafts}
            saving={saving}
            onChange={setDrafts}
            onSave={() => void save()}
            intro="Cotas padrão deste produto. Ao salvar, a revisão sobe e as próximas inspeções usam estes valores."
          />
        </>
      ) : null}
    </OperatorDialog>
  );
}
