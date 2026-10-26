import { useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import { EmptyState, LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { SpcPonto, SpcResponse, SpcSerie } from "../../types/qualitySpc";
import { formatDateTime, formatNumber } from "../../utils/format";
import { SpcControlChart, signalText } from "./SpcControlChart";
import type { SpcChartPoint } from "./SpcControlChart";

const API = "/api/v1/quality/spc";
const TITLE = "Qualidade — SPC";
const SUBTITLE = "Cartas de controle e Cpk das cotas já medidas. Somente consulta: os números vêm prontos do servidor.";

const ACCESS_DENIED = "Seu perfil não tem acesso ao SPC. Só a Qualidade e a administração usam esta tela.";

/** Mensagem humana por `code`; nunca o código técnico. */
const ERROR_MESSAGES: Record<string, string> = {
  quality_templates_access_denied: ACCESS_DENIED,
  invalid_date: "O período informado é inválido. Confira as datas.",
  validation_error: "Algum filtro está inválido. Confira o produto, a cota e as datas.",
  network_error: "Não foi possível acessar o servidor. Tente novamente.",
};

export function spcErrorMessage(reason: unknown) {
  if (!(reason instanceof ApiError)) return ERROR_MESSAGES.network_error;
  if (reason.status === 403) return ACCESS_DENIED;
  return ERROR_MESSAGES[reason.code] ?? "Não foi possível carregar o SPC. Tente novamente.";
}

const CHART_KIND: Record<string, { name: string; x: string; dispersion: string }> = {
  xbar_r: { name: "X-barra e R (média e amplitude de cada subgrupo)", x: "Médias dos subgrupos (X-barra)", dispersion: "Amplitudes dos subgrupos (R)" },
  i_mr: { name: "Valores individuais e amplitude móvel (cada medida é um ponto)", x: "Valores individuais (I)", dispersion: "Amplitude móvel (AM)" },
};

function pointTip(point: SpcPonto, value: number | null, signals: SpcPonto["fora_de_controle"]) {
  const parts = [`Ponto ${point.indice + 1}`];
  if (point.codigo_op) parts.push(`OP ${point.codigo_op}`);
  parts.push(`${point.n} peça(s)`);
  if (point.fim) parts.push(formatDateTime(point.fim));
  parts.push(`valor ${formatNumber(value, 4)}`);
  if (signals.length) parts.push(`sinal: ${signalText(signals)}`);
  return parts.join(" · ");
}

function chartPoints(serie: SpcSerie, graph: "x" | "dispersao"): SpcChartPoint[] {
  return serie.pontos.map((point) => {
    const signals = point.fora_de_controle.filter((signal) => signal.grafico === graph);
    const value = graph === "x" ? point.media : point.amplitude;
    return {
      key: point.indice,
      label: point.indice + 1,
      value,
      limits: graph === "x" ? point.limites_x : point.limites_dispersao,
      signals,
      tip: pointTip(point, value, signals),
    };
  });
}

function countSignals(serie: SpcSerie) {
  return serie.pontos.filter((point) => point.fora_de_controle.length > 0).length;
}

function SerieCard({ serie }: { serie: SpcSerie }) {
  const kind = CHART_KIND[serie.tipo_grafico];
  const cota = serie.cota;
  const cotaLabel = `Cota ${cota.sequencia}${cota.descricao ? ` — ${cota.descricao}` : ""}`;
  const unit = cota.unidade;
  const spec = serie.especificacao;
  const flagged = countSignals(serie);
  const hasLimits = serie.pontos.some((point) => point.limites_x);
  return (
    <SectionCard
      title={`${serie.produto} · ${cotaLabel}`}
      className="content-section spc-serie"
      action={<span className="section-count">{`${formatNumber(serie.n_medidas)} medidas · ${formatNumber(serie.n_subgrupos)} subgrupos`}</span>}
    >
      <dl className="spc-serie__facts">
        <div><dt>Padrão da cota</dt><dd>{serie.padrao_snapshot}</dd></div>
        <div><dt>Especificação</dt><dd>{`${formatNumber(spec.lsl, 4)} a ${formatNumber(spec.usl, 4)} ${unit}`}</dd></div>
        <div><dt>Tipo de carta</dt><dd>{kind?.name ?? serie.tipo_grafico}</dd></div>
        <div>
          <dt>Cpk</dt>
          <dd className="spc-serie__cpk" data-testid="spc-cpk">
            {serie.cpk.value !== null ? formatNumber(serie.cpk.value, 2) : (serie.cpk.reason ?? "Cpk indisponível")}
          </dd>
        </div>
        <div><dt>Cpk superior (CPU)</dt><dd>{serie.cpu !== null ? formatNumber(serie.cpu, 2) : "Não calculado"}</dd></div>
        <div><dt>Cpk inferior (CPL)</dt><dd>{serie.cpl !== null ? formatNumber(serie.cpl, 2) : "Não calculado"}</dd></div>
      </dl>
      <p className="spc-serie__label" data-testid="spc-rotulo-cpk">{serie.rotulo_cpk}</p>

      {!serie.suficiente && serie.motivo_insuficiente ? <Notice tone="stale">{serie.motivo_insuficiente}</Notice> : null}
      {serie.suficiente && serie.motivo_sem_limites ? <Notice tone="stale">{serie.motivo_sem_limites}</Notice> : null}
      {serie.subgrupos_unitarios_descartados > 0 ? (
        <p className="spc-serie__note">{`${formatNumber(serie.subgrupos_unitarios_descartados)} subgrupo(s) de 1 peça ficaram fora da carta.`}</p>
      ) : null}

      <SpcControlChart title={kind?.x ?? "Carta de controle"} points={chartPoints(serie, "x")} unit={unit} />
      <SpcControlChart title={kind?.dispersion ?? "Dispersão"} points={chartPoints(serie, "dispersao")} unit={unit} />

      <ul className="spc-legend" aria-label="Legenda da carta">
        <li><span className="spc-legend__mark spc-legend__mark--dot" aria-hidden="true" />Ponto normal</li>
        <li><span className="spc-legend__mark spc-legend__mark--outside" aria-hidden="true" />Fora dos limites</li>
        <li><span className="spc-legend__mark spc-legend__mark--run" aria-hidden="true" />Sequência de 7 do mesmo lado</li>
        {hasLimits ? <li>LSC / LC / LIC: limites superior, central e inferior de controle</li> : null}
      </ul>
      <p className="spc-serie__note" data-testid="spc-sinais">
        {flagged ? `${formatNumber(flagged)} ponto(s) com sinal nesta série.` : "Nenhum ponto com sinal nesta série."}
      </p>
    </SectionCard>
  );
}

export function QualitySpcPage() {
  const [produto, setProduto] = useState("");
  const [cota, setCota] = useState("");
  const [inicio, setInicio] = useState("");
  const [fim, setFim] = useState("");
  const debouncedProduto = useDebouncedValue(produto.trim());
  const debouncedCota = useDebouncedValue(cota.trim());

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (debouncedProduto) params.set("product", debouncedProduto);
    if (debouncedCota) params.set("cota", debouncedCota);
    if (inicio) params.set("start", `${inicio}T00:00:00`);
    if (fim) params.set("end", `${fim}T23:59:59`);
    const query = params.toString();
    return query ? `${API}?${query}` : API;
  }, [debouncedProduto, debouncedCota, inicio, fim]);
  const query = useApiQuery<SpcResponse>(path, { ignoreLiveTick: true });

  const data = query.data;
  const series = data?.series ?? [];
  const filtered = Boolean(debouncedProduto || debouncedCota || inicio || fim);
  const reset = () => {
    setProduto("");
    setCota("");
    setInicio("");
    setFim("");
  };

  return (
    <PageFrame sectionId="quality" title={TITLE} subtitle={SUBTITLE} filters={false} staleError={data ? query.error : null}>
      <div className="record-toolbar" role="search" aria-label="Filtros do SPC">
        <div className="record-toolbar__fields">
          <label htmlFor="spc-produto">
            Produto
            <input id="spc-produto" className="std-time__filter-input" value={produto} placeholder="Código do produto" onChange={(event) => setProduto(event.target.value)} />
          </label>
          <label htmlFor="spc-cota">
            Cota
            <input id="spc-cota" className="std-time__filter-input spc-filter--narrow" type="number" min={1} max={200} value={cota} placeholder="Nº" onChange={(event) => setCota(event.target.value)} />
          </label>
          <label htmlFor="spc-inicio">
            De
            <input id="spc-inicio" className="std-time__filter-input" type="date" value={inicio} max={fim || undefined} onChange={(event) => setInicio(event.target.value)} />
          </label>
          <label htmlFor="spc-fim">
            Até
            <input id="spc-fim" className="std-time__filter-input" type="date" value={fim} min={inicio || undefined} onChange={(event) => setFim(event.target.value)} />
          </label>
        </div>
        <div className="record-toolbar__meta">
          <span className="record-toolbar__summary">{data ? `${formatNumber(series.length)} série(s)` : ""}</span>
          <button type="button" className="record-toolbar__reset" onClick={reset} disabled={!(produto || cota || inicio || fim)}>
            Limpar filtros
          </button>
        </div>
      </div>

      {query.loading && !data ? <LoadingState /> : null}
      {query.error && !data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar o SPC</strong>
          <span>{spcErrorMessage(query.error)}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {data ? (
        <>
          <p className="spc-intro" data-testid="spc-amostra-minima">
            {`Cada série precisa de pelo menos ${formatNumber(data.amostra_minima.medidas)} medidas e ${formatNumber(data.amostra_minima.subgrupos)} subgrupos para ter limites de controle e Cpk.`}
          </p>
          {data.truncado ? (
            <Notice tone="stale">Há medições demais para o filtro: só as mais recentes foram analisadas. Use produto, cota ou período para reduzir.</Notice>
          ) : null}
          {data.ignoradas.padrao_nao_numerico + data.ignoradas.medida_invalida > 0 ? (
            <Notice tone="info">
              {`Medidas fora da análise: ${formatNumber(data.ignoradas.padrao_nao_numerico)} de cota com padrão não numérico e ${formatNumber(data.ignoradas.medida_invalida)} com valor inválido.`}
            </Notice>
          ) : null}
          {!series.length ? (
            <EmptyState
              title="Sem medições suficientes"
              detail={filtered
                ? "Nenhuma cota medida neste filtro. Confira o produto, a cota e o período, ou use “Limpar filtros”."
                : "Ainda não há cotas medidas pela Qualidade para montar as cartas de controle."}
            />
          ) : (
            <div className="spc-list">
              {series.map((serie) => (
                <SerieCard key={`${serie.produto}|${serie.cota.sequencia}|${serie.padrao_snapshot}`} serie={serie} />
              ))}
            </div>
          )}
        </>
      ) : null}
    </PageFrame>
  );
}
