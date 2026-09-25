import { useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorState, LoadingState } from "../components/DataState";
import { AndonSidebarNav } from "../components/AndonSidebarNav";
import { useApiQuery } from "../hooks/useApiQuery";
import { SnapshotStatus } from "../components/SnapshotStatus";
import { useForceLightTheme } from "../hooks/useForceLightTheme";
import { useRealtimeStatus } from "../hooks/useRealtimeStatus";
import { useTvRotation } from "../hooks/useTvRotation";
import type {
  WeldingMacroRow,
  WeldingManagementSnapshot,
  WeldingOrderRow,
  WeldingStationGroup,
} from "../types/welding";
import { formatDateTime, formatHours, formatNumber } from "../utils/format";
import { reportedValueText } from "../utils/systemState";

/**
 * Acompanhamento gerencial da Solda (Wave 6D).
 *
 * Tela de leitura para PCP, Liderança, Supervisão e Diretoria. Não é posto: não
 * existe comando, seleção de estação nem login por estação. O modelo de
 * informação é o da planilha da PCP — ESTAÇÃO, OP, PRODUTO/CONJUNTO,
 * MÁQUINA/MODELO, DATA e STATUS — e a estação continua sendo o agrupamento.
 *
 * Nenhuma regra é recalculada aqui: estado de prazo, estação observada e
 * ausência de dado chegam prontos do backend. O que a tela faz é somar,
 * ordenar e medir o intervalo entre duas datas que o backend já entregou.
 */

/**
 * Frases de ausência de cada coluna. Elas dizem o que a falta significa para
 * quem lê a tela; a tradução dos estados técnicos continua centralizada em
 * `utils/systemState`.
 */
const MODEL_ABSENT = "Modelo não identificado.";
const STATION_ABSENT = "Estação ainda não definida.";
const DEADLINE_ABSENT = "Prazo ainda não informado pelo planejamento.";
const MACRO_ABSENT = "Produto não cadastrado na OP.";

/**
 * As três situações de prazo, na ordem em que a PCP lê. Cores pedidas
 * explicitamente pela PCP para esta tela, replicando a planilha de
 * referência: atrasado = vermelho, a vencer = verde, finalizado = azul. Os
 * tokens reaproveitados (`--danger`/`--accent`/`--primary`) já existem no
 * resto do sistema; nenhuma cor nova é criada. Isso diverge de propósito da
 * convenção do resumo do cabeçalho desta mesma tela (que usa âmbar para "a
 * vencer") — a PCP pediu exatamente essas três cores para o pivô/pizza/barra.
 */
const MACRO_SLICES = [
  { key: "atrasadas", tone: "late", label: "Atrasadas", status: "ATRASADA" },
  { key: "a_vencer", tone: "due", label: "A vencer", status: "A VENCER" },
  { key: "finalizadas", tone: "done", label: "Finalizadas", status: "FINALIZADA" },
] as const;

type MacroSliceKey = (typeof MACRO_SLICES)[number]["key"];
type StatusTotals = Record<MacroSliceKey, number>;

const STATUS_TONE: Record<string, string> = {
  "A VENCER": "due",
  ATRASADA: "late",
  FINALIZADA: "done",
};

const DAY_MS = 86_400_000;

function macroName(row: WeldingMacroRow) {
  return row.nome ?? MACRO_ABSENT;
}

function statusTone(row: WeldingOrderRow) {
  return STATUS_TONE[row.status.value ?? ""] ?? "unknown";
}

function stationLabel(group: WeldingStationGroup) {
  return reportedValueText({ value: group.nome, availability: group.availability }, STATION_ABSENT);
}

function share(value: number, total: number) {
  return total > 0 ? Math.round((value / total) * 100) : 0;
}

function countByStatus(rows: WeldingOrderRow[]): StatusTotals {
  return MACRO_SLICES.reduce(
    (acc, slice) => ({
      ...acc,
      [slice.key]: rows.filter((row) => row.status.value === slice.status).length,
    }),
    {} as StatusTotals,
  );
}

/**
 * Dias inteiros entre o vencimento do prazo e a leitura do backend. Não é uma
 * regra nova: a classificação ATRASADA já veio pronta e o instante de
 * referência é o `generated_at` do próprio snapshot, não o relógio do
 * navegador. A OP atrasada pela semana de criação não tem prazo vencido e
 * devolve `null` — a tela mostra o motivo textual nesse caso.
 */
function daysOverdue(row: WeldingOrderRow, reference: number) {
  const deadline = row.datas.referencia_prazo.value;
  if (!deadline) return null;
  const elapsed = reference - new Date(deadline).getTime();
  return elapsed > 0 ? Math.floor(elapsed / DAY_MS) : null;
}

/** Intervalo entre o início e o fim do apontamento real, quando existem os dois. */
function executionSeconds(row: WeldingOrderRow) {
  const { inicio_real: inicio, fim_real: fim } = row.datas;
  if (!inicio || !fim) return null;
  const seconds = (new Date(fim).getTime() - new Date(inicio).getTime()) / 1000;
  return seconds > 0 ? seconds : null;
}

/** Tabela pivô MACRO × situação de prazo — o mesmo modelo da planilha da PCP. */
function MacroPivotTable({ macros, totals, semPrazo }: {
  macros: WeldingMacroRow[];
  totals: StatusTotals;
  semPrazo: number;
}) {
  return (
    <div className="welding-macros__table-scroll">
      <table className="welding-macro-table">
        <caption className="visually-hidden">
          Contagem de OPs de conjunto soldado por MACRO e situação de prazo
        </caption>
        <thead>
          <tr>
            <th scope="col">MACRO</th>
            {MACRO_SLICES.map((slice) => (
              <th key={slice.key} scope="col" data-tone={slice.tone}>{slice.label}</th>
            ))}
            <th scope="col">Sem prazo</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {macros.map((row) => (
            <tr key={row.nome ?? "sem-macro"} data-availability={row.availability}>
              <th scope="row">
                <strong>{macroName(row)}</strong>
                {row.codigo && row.nome ? <small>{row.codigo}</small> : null}
              </th>
              {MACRO_SLICES.map((slice) => (
                <td key={slice.key} data-tone={slice.tone}>{row[slice.key]}</td>
              ))}
              <td>{row.sem_prazo}</td>
              <td><strong>{row.total}</strong></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Total geral</th>
            {MACRO_SLICES.map((slice) => (
              <td key={slice.key} data-tone={slice.tone}>{totals[slice.key]}</td>
            ))}
            <td>{semPrazo}</td>
            <td><strong>{MACRO_SLICES.reduce((sum, slice) => sum + totals[slice.key], 0) + semPrazo}</strong></td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/**
 * Pizza da composição total — fatias cheias (sem furo central), como a PCP
 * pediu. Sem biblioteca de gráfico: cada fatia é um `<path>` de arco, a mesma
 * abordagem em SVG puro já usada no resto do sistema.
 */
function StatusPie({ totals, semPrazo }: { totals: StatusTotals; semPrazo: number }) {
  const total = MACRO_SLICES.reduce((sum, slice) => sum + totals[slice.key], 0);
  const radius = 60;
  const center = 64;
  let angle = 0;
  const point = (deg: number) => {
    const rad = ((deg - 90) * Math.PI) / 180;
    return [center + radius * Math.cos(rad), center + radius * Math.sin(rad)];
  };
  const wedges = total > 0 ? MACRO_SLICES.map((slice) => {
    const value = totals[slice.key];
    if (value === 0) return null;
    const sweep = (value / total) * 360;
    const [x1, y1] = point(angle);
    const [x2, y2] = point(angle + sweep);
    const largeArc = sweep > 180 ? 1 : 0;
    angle += sweep;
    const solo = value === total;
    const d = solo
      ? `M ${center} ${center - radius} A ${radius} ${radius} 0 1 1 ${center - 0.01} ${center - radius} Z`
      : `M ${center} ${center} L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`;
    return <path key={slice.key} data-tone={slice.tone} d={d} />;
  }) : null;
  return (
    <figure className="welding-pie">
      <svg viewBox="0 0 128 128" role="img" aria-label={
        `Composição das OPs de Solda: ${MACRO_SLICES
          .map((slice) => `${slice.label} ${totals[slice.key]}`)
          .join(", ")}.`
      }>
        {total > 0 ? wedges : <circle cx={center} cy={center} r={radius} className="welding-pie__empty" />}
      </svg>
      <figcaption>
        {MACRO_SLICES.map((slice) => (
          <span key={slice.key} data-tone={slice.tone}>
            <i aria-hidden="true" />
            <b>{slice.label}</b>
            <em>{totals[slice.key]} • {share(totals[slice.key], total)}%</em>
          </span>
        ))}
        {semPrazo > 0 ? (
          <span data-tone="unknown">
            <i aria-hidden="true" />
            <b>Sem prazo</b>
            <em>{semPrazo}</em>
          </span>
        ) : null}
      </figcaption>
    </figure>
  );
}

/**
 * Barra 100% empilhada, uma por MACRO, com eixo de 0 a 100%. Mesmo papel da
 * "Contagem de MACRO" da planilha de referência: mostra a proporção de cada
 * situação dentro de cada produto, lado a lado.
 */
function MacroBarChart({ macros }: { macros: WeldingMacroRow[] }) {
  const marks = [100, 75, 50, 25, 0];
  return (
    <div className="welding-barchart">
      <h3>Contagem de MACRO</h3>
      <div className="welding-barchart__plot">
        {marks.map((mark) => (
          <div key={mark} className="welding-barchart__gridline" style={{ bottom: `${mark}%` }}>
            <span>{mark}%</span>
          </div>
        ))}
        {macros.map((row) => {
          const total = MACRO_SLICES.reduce((sum, slice) => sum + row[slice.key], 0);
          return (
            <div className="welding-barchart__group" key={row.nome ?? "sem-macro"}>
              <div className="welding-barchart__bar">
                {total === 0 ? null : MACRO_SLICES.map((slice) => (
                  row[slice.key] > 0 ? (
                    <i
                      key={slice.key}
                      data-tone={slice.tone}
                      style={{ height: `${(row[slice.key] / total) * 100}%` }}
                      title={`${slice.label}: ${row[slice.key]} de ${total}`}
                    >
                      {row[slice.key]}
                    </i>
                  ) : null
                ))}
              </div>
              <span className="welding-barchart__label" title={macroName(row)}>{macroName(row)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Pivô: tabela + pizza à esquerda, barra 100% empilhada por MACRO à direita. */
function MacroPivot({ macros }: { macros: WeldingMacroRow[] }) {
  const totals = MACRO_SLICES.reduce(
    (acc, slice) => ({ ...acc, [slice.key]: macros.reduce((sum, row) => sum + row[slice.key], 0) }),
    {} as StatusTotals,
  );
  const semPrazo = macros.reduce((sum, row) => sum + row.sem_prazo, 0);
  return (
    <section className="welding-macros">
      <header>
        <h2>Acompanhamento por MACRO</h2>
        <p>Produto/conjunto planejado da OP cruzado com a situação de prazo.</p>
      </header>
      <div className="welding-macros__body">
        <div className="welding-macros__left">
          <MacroPivotTable macros={macros} totals={totals} semPrazo={semPrazo} />
          <StatusPie totals={totals} semPrazo={semPrazo} />
        </div>
        <MacroBarChart macros={macros} />
      </div>
    </section>
  );
}

/** DATA da linha: a referência de prazo e, quando houver, a execução real. */
function DateCell({ row }: { row: WeldingOrderRow }) {
  const deadline = row.datas.referencia_prazo;
  const started = row.datas.inicio_real;
  const finished = row.datas.fim_real;
  return (
    <div className="welding-dates">
      {deadline.value ? (
        <span className="welding-dates__main">
          <small>{deadline.label}</small>
          <strong>{formatDateTime(deadline.value)}</strong>
        </span>
      ) : (
        <span className="welding-dates__absent">{DEADLINE_ABSENT}</span>
      )}
      {finished ? (
        <span className="welding-dates__real">Soldada em {formatDateTime(finished)}</span>
      ) : started ? (
        <span className="welding-dates__real">Em execução desde {formatDateTime(started)}</span>
      ) : null}
    </div>
  );
}

function StatusBadge({ row }: { row: WeldingOrderRow }) {
  return (
    <span className={`welding-badge welding-badge--${statusTone(row)}`} data-availability={row.status.availability}>
      {row.status.value ?? "Prazo não informado"}
    </span>
  );
}

function OrderRows({ rows }: { rows: WeldingOrderRow[] }) {
  return (
    <table className="welding-table">
      <caption className="visually-hidden">
        Ordens de produção de conjuntos soldados desta estação
      </caption>
      <thead>
        <tr>
          <th scope="col">OP</th>
          <th scope="col">Produto / Conjunto</th>
          <th scope="col">Máquina / Modelo</th>
          <th scope="col">Data</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={`${row.op}-${row.operacao ?? index}`} data-status={statusTone(row)}>
            <td className="welding-op">
              <strong>{row.op}</strong>
              {row.operacao ? <small>Operação {row.operacao}</small> : null}
            </td>
            <td className="welding-product">
              <strong>{row.produto.descricao ?? row.produto.codigo}</strong>
              {row.produto.codigo && row.produto.descricao ? <small>{row.produto.codigo}</small> : null}
            </td>
            <td className="welding-machine">
              <strong>{row.maquina.nome ?? row.maquina.operacao}</strong>
              <small data-availability={row.modelo.availability}>
                {reportedValueText(row.modelo, MODEL_ABSENT)}
              </small>
            </td>
            <td><DateCell row={row} /></td>
            <td className="welding-status">
              <StatusBadge row={row} />
              <small>{row.status.reason}</small>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Uma estação por vez. `<details>` nativo: a estação fechada continua no
 * documento (e no Ctrl+F do navegador) sem ocupar a tela, e não é preciso
 * estado de abertura em React para uma lista de leitura.
 */
function StationDisclosure({ group, open }: { group: WeldingStationGroup; open: boolean }) {
  const counts = countByStatus(group.ops);
  return (
    <details className="welding-station" open={open} data-availability={group.availability}>
      <summary className="welding-station__summary">
        <span className="welding-station__name">{stationLabel(group)}</span>
        <span className="welding-station__count">
          {group.op_count === 1 ? "1 OP" : `${group.op_count} OPs`}
        </span>
        <span className="welding-station__tally">
          {MACRO_SLICES.map((slice) => (
            counts[slice.key] > 0 ? (
              <i key={slice.key} data-tone={slice.tone} title={`${slice.label}: ${counts[slice.key]}`}>
                {counts[slice.key]}
              </i>
            ) : null
          ))}
        </span>
      </summary>
      <OrderRows rows={group.ops} />
    </details>
  );
}

function StationList({ groups }: { groups: WeldingStationGroup[] }) {
  // Poucas estações cabem abertas; a partir daí a tela abre fechada, que é o
  // pedido de "não poluir a visão".
  const open = groups.length <= 2;
  return (
    <div className="welding-table-scroll">
      {groups.map((group) => (
        <StationDisclosure key={group.nome ?? "sem-estacao"} group={group} open={open} />
      ))}
    </div>
  );
}

/** Uma linha já achatada com a estação em que ela foi observada. */
interface FlatRow {
  row: WeldingOrderRow;
  station: string;
}

function flatten(groups: WeldingStationGroup[]): FlatRow[] {
  return groups.flatMap((group) => group.ops.map((row) => ({ row, station: stationLabel(group) })));
}

/** Ranking horizontal reaproveitando a mesma barra de composição da tela. */
function StationRanking({ entries, tone }: { entries: [string, number][]; tone: string }) {
  const max = entries.reduce((peak, [, value]) => Math.max(peak, value), 0);
  return (
    <ol className="welding-ranking">
      {entries.map(([station, value]) => (
        <li key={station}>
          <span className="welding-ranking__label" title={station}>{station}</span>
          <span className="welding-ranking__bar">
            <i data-tone={tone} style={{ width: `${max > 0 ? (value / max) * 100 : 0}%` }} />
          </span>
          <strong>{value}</strong>
        </li>
      ))}
    </ol>
  );
}

/**
 * Sub-aba "Atrasos": só o que já está classificado como ATRASADA pelo backend,
 * ordenado pelo tempo de vencimento do prazo. Responde "onde está o atraso" —
 * por estação e por OP — sem inventar nenhuma métrica nova.
 */
function LatePanel({ rows, reference }: { rows: FlatRow[]; reference: number }) {
  const late = rows
    .filter((item) => item.row.status.value === "ATRASADA")
    .sort((a, b) => (daysOverdue(b.row, reference) ?? -1) - (daysOverdue(a.row, reference) ?? -1));
  if (late.length === 0) {
    return <EmptyState title="Nenhuma OP de conjunto soldado atrasada nesta leitura." />;
  }
  const porEstacao = Object.entries(
    late.reduce<Record<string, number>>((acc, item) => {
      acc[item.station] = (acc[item.station] ?? 0) + 1;
      return acc;
    }, {}),
  ).sort((a, b) => b[1] - a[1]);
  return (
    <div className="welding-panel">
      <section className="welding-card welding-card--narrow">
        <h3>Atraso por estação</h3>
        <p>OPs atrasadas por estação observada no apontamento.</p>
        <StationRanking entries={porEstacao} tone="late" />
      </section>
      <section className="welding-card">
        <h3>OPs atrasadas</h3>
        <p>Da mais vencida para a mais recente, com o motivo que o acompanhamento registrou.</p>
        <div className="welding-card__scroll">
          <table className="welding-table welding-table--flat">
            <thead>
              <tr>
                <th scope="col">OP</th>
                <th scope="col">Produto / Conjunto</th>
                <th scope="col">Estação</th>
                <th scope="col">Prazo</th>
                <th scope="col">Atraso</th>
              </tr>
            </thead>
            <tbody>
              {late.map(({ row, station }, index) => {
                const days = daysOverdue(row, reference);
                return (
                  <tr key={`${row.op}-${row.operacao ?? index}`} data-status="late">
                    <td className="welding-op">
                      <strong>{row.op}</strong>
                      {row.operacao ? <small>Operação {row.operacao}</small> : null}
                    </td>
                    <td className="welding-product">
                      <strong>{row.produto.descricao ?? row.produto.codigo}</strong>
                      {row.produto.codigo && row.produto.descricao ? <small>{row.produto.codigo}</small> : null}
                    </td>
                    <td>{station}</td>
                    <td>
                      {row.datas.referencia_prazo.value ? (
                        <>
                          <strong>{formatDateTime(row.datas.referencia_prazo.value)}</strong>
                          <small>{row.datas.referencia_prazo.label}</small>
                        </>
                      ) : (
                        <small>{DEADLINE_ABSENT}</small>
                      )}
                    </td>
                    <td className="welding-late">
                      {days === null ? (
                        <span className="welding-badge welding-badge--late">Sem apontamento</span>
                      ) : (
                        <span className="welding-badge welding-badge--late">
                          {days === 0 ? "Vence hoje" : days === 1 ? "1 dia" : `${formatNumber(days)} dias`}
                        </span>
                      )}
                      <small>{row.status.reason}</small>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/**
 * Sub-aba "Entregas": o que a Solda concluiu, pelo apontamento operacional —
 * a mesma prova de conclusão que o domínio usa para dizer FINALIZADA. O tempo
 * é o intervalo entre o início e o fim do apontamento; a OP finalizada sem os
 * dois instantes entra na contagem e fica fora da média, declarada na tela.
 */
function DeliveryPanel({ rows }: { rows: FlatRow[] }) {
  const done = rows.filter((item) => item.row.status.value === "FINALIZADA");
  if (done.length === 0) {
    return <EmptyState title="Nenhuma solda concluída e apontada nesta leitura." />;
  }
  const porEstacao = Object.values(
    done.reduce<Record<string, { station: string; total: number; seconds: number[]; last: string | null }>>(
      (acc, { row, station }) => {
        const entry = acc[station] ?? { station, total: 0, seconds: [], last: null };
        entry.total += 1;
        const seconds = executionSeconds(row);
        if (seconds !== null) entry.seconds.push(seconds);
        const finished = row.datas.fim_real;
        if (finished && (!entry.last || finished > entry.last)) entry.last = finished;
        acc[station] = entry;
        return acc;
      },
      {},
    ),
  ).sort((a, b) => b.total - a.total);
  const medidas = done.map(({ row }) => executionSeconds(row)).filter((value): value is number => value !== null);
  const media = medidas.length ? medidas.reduce((sum, value) => sum + value, 0) / medidas.length : null;
  const recentes = [...done]
    .filter((item) => item.row.datas.fim_real)
    .sort((a, b) => String(b.row.datas.fim_real).localeCompare(String(a.row.datas.fim_real)))
    .slice(0, 8);
  return (
    <div className="welding-panel">
      <section className="welding-card welding-card--narrow">
        <h3>Entregue por estação</h3>
        <p>
          {medidas.length === done.length
            ? "Tempo é o intervalo entre o início e o fim do apontamento."
            : `Tempo medido em ${medidas.length} de ${done.length} entregas — as demais não têm início e fim apontados.`}
        </p>
        <dl className="welding-metrics">
          <div><dt>Entregas</dt><dd>{done.length}</dd></div>
          <div><dt>Tempo médio</dt><dd>{media === null ? "Não disponível" : formatHours(media)}</dd></div>
        </dl>
        <table className="welding-table welding-table--flat">
          <thead>
            <tr>
              <th scope="col">Estação</th>
              <th scope="col">Entregas</th>
              <th scope="col">Tempo médio</th>
            </tr>
          </thead>
          <tbody>
            {porEstacao.map((entry) => (
              <tr key={entry.station}>
                <td>{entry.station}</td>
                <td><strong>{entry.total}</strong></td>
                <td>
                  {entry.seconds.length
                    ? formatHours(entry.seconds.reduce((sum, value) => sum + value, 0) / entry.seconds.length)
                    : "Não disponível"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="welding-card">
        <h3>Últimas entregas</h3>
        <p>Conjuntos soldados concluídos e apontados, do mais recente para o mais antigo.</p>
        <div className="welding-card__scroll">
          <table className="welding-table welding-table--flat">
            <thead>
              <tr>
                <th scope="col">OP</th>
                <th scope="col">Produto / Conjunto</th>
                <th scope="col">Estação</th>
                <th scope="col">Concluída em</th>
                <th scope="col">Tempo</th>
              </tr>
            </thead>
            <tbody>
              {recentes.map(({ row, station }, index) => {
                const seconds = executionSeconds(row);
                return (
                  <tr key={`${row.op}-${row.operacao ?? index}`} data-status="done">
                    <td className="welding-op"><strong>{row.op}</strong></td>
                    <td className="welding-product">
                      <strong>{row.produto.descricao ?? row.produto.codigo}</strong>
                    </td>
                    <td>{station}</td>
                    <td><strong>{formatDateTime(row.datas.fim_real)}</strong></td>
                    <td>{seconds === null ? "Não disponível" : formatHours(seconds)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/**
 * Só o que o pivô por MACRO não repete: total de OPs distintas e quantas
 * estações têm alguma. Atrasadas/A vencer/Finalizadas já aparecem — com mais
 * precisão, por MACRO — na rosca e nos cartões logo abaixo; duplicar aqui só
 * competia visualmente com o mesmo número.
 */
function Summary({ data }: { data: WeldingManagementSnapshot }) {
  const { resumo } = data;
  return (
    <dl className="welding-summary">
      <div><dt>OPs de conjunto soldado</dt><dd>{resumo.ops}</dd></div>
      <div><dt>Estações com OP</dt><dd>{resumo.estacoes}</dd></div>
    </dl>
  );
}

const MANAGER_TABS = [
  { id: "geral", label: "Visão geral" },
  { id: "atrasos", label: "Atrasos" },
  { id: "entregas", label: "Entregas" },
] as const;

type ManagerTabId = (typeof MANAGER_TABS)[number]["id"];

export function WeldingManagementPage() {
  useForceLightTheme();
  useDocumentTitle("Acompanhamento da Solda");
  const { user } = useAuth();
  const query = useApiQuery<WeldingManagementSnapshot>("/api/v1/welding", { ignoreLiveTick: true, keepLastSnapshot: true });
  const realtime = useRealtimeStatus();
  const [tab, setTab] = useState<ManagerTabId>("geral");
  // Padrão WAI-ARIA de abas: setas/Home/End movem a seleção e o foco.
  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = MANAGER_TABS.findIndex((item) => item.id === tab);
    const last = MANAGER_TABS.length - 1;
    const next = event.key === "ArrowRight" ? (index === last ? 0 : index + 1)
      : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (next === null) return;
    event.preventDefault();
    const target = MANAGER_TABS[next].id;
    setTab(target);
    document.getElementById(`welding-tab-${target}`)?.focus();
  }
  // O ciclo da TV é o mesmo mecanismo do Andon: só o perfil dedicado alterna.
  const isTelevision = useTvRotation("/welding-management");
  const pageClass = `welding-page ${isTelevision || user?.role === "andon" ? "welding-page--tv" : "welding-page--manager"}`;
  // Mesma correção do Andon: página cheia, fora da barra de abas da gestão —
  // sem isso, ninguém alcançava Metas/Pausas/Chamadas sem o "voltar" do
  // navegador (decisão do usuário, 15/09/2026). A TV dedicada nunca vê isso.
  const showPanelsNav = Boolean(user?.management_access) && !isTelevision;

  // Mesma atualização automática do Andon: o canal em tempo real recarrega a
  // projeção e a varredura periódica só entra quando ele não está conectado.
  useEffect(() => {
    if (realtime === "connected") return undefined;
    const fallback = window.setInterval(query.reload, 30_000);
    return () => window.clearInterval(fallback);
  }, [query.reload, realtime]);

  const estacoes = query.data?.estacoes;
  const linhas = useMemo(() => flatten(estacoes ?? []), [estacoes]);

  if (query.loading && !query.data) {
    return <main className={pageClass}>{showPanelsNav ? <AndonSidebarNav /> : null}<LoadingState label="Carregando acompanhamento da Solda…" /></main>;
  }
  if (query.error && !query.data) {
    return <main className={pageClass}>{showPanelsNav ? <AndonSidebarNav /> : null}<ErrorState error={query.error} onRetry={query.reload} /></main>;
  }
  if (!query.data) {
    return <main className={pageClass}>{showPanelsNav ? <AndonSidebarNav /> : null}<EmptyState title="Nenhuma ordem de conjunto soldado disponível." /></main>;
  }

  const data = query.data;
  // O instante da leitura é o do backend: as contagens de atraso da tela e a
  // classificação do domínio olham para o mesmo relógio.
  const reference = data.generated_at ? new Date(data.generated_at).getTime() : Date.now();
  const counts: Record<ManagerTabId, number | null> = {
    geral: null,
    atrasos: data.resumo.atrasadas,
    entregas: data.resumo.finalizadas,
  };
  const macros = data.macros?.length ? <MacroPivot macros={data.macros} /> : null;
  return (
    <main className={pageClass} data-simulation={data.simulation_only ? "true" : undefined}>
      {showPanelsNav ? <AndonSidebarNav /> : null}
      <header className="welding-header">
        <div>
          <h1>Acompanhamento da Solda</h1>
          <p>Conjuntos soldados por estação, com prazo e situação de cada ordem.</p>
        </div>
        <Summary data={data} />
      </header>
      <SnapshotStatus error={query.error} updatedAt={query.updatedAt} staleClassName="welding-stale" />
      {isTelevision ? macros : (
        <>
          <div className="welding-tabs" role="tablist" aria-label="Visões do acompanhamento da Solda" onKeyDown={onTabKeyDown}>
            {MANAGER_TABS.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                id={`welding-tab-${item.id}`}
                aria-controls={`welding-panel-${item.id}`}
                aria-selected={tab === item.id}
                tabIndex={tab === item.id ? 0 : -1}
                className={tab === item.id ? "welding-tab welding-tab--active" : "welding-tab"}
                onClick={() => setTab(item.id)}
              >
                {item.label}
                {counts[item.id] === null ? null : <span>{counts[item.id]}</span>}
              </button>
            ))}
          </div>
          <div
            className="welding-tabpanel"
            role="tabpanel"
            id={`welding-panel-${tab}`}
            aria-labelledby={`welding-tab-${tab}`}
          >
            {tab === "geral" ? (
              <>
                {macros}
                {data.estacoes.length === 0 ? (
                  <EmptyState title="Nenhuma ordem de conjunto soldado para acompanhar." state={data.availability} />
                ) : (
                  <StationList groups={data.estacoes} />
                )}
              </>
            ) : null}
            {tab === "atrasos" ? <LatePanel rows={linhas} reference={reference} /> : null}
            {tab === "entregas" ? <DeliveryPanel rows={linhas} /> : null}
          </div>
        </>
      )}
      {isTelevision || !data.generated_at ? null : (
        <footer className="welding-footer">Leitura de {formatDateTime(data.generated_at)}</footer>
      )}
    </main>
  );
}
