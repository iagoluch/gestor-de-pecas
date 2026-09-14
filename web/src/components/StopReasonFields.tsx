import { useEffect, useMemo, useState } from "react";
import type { StopReason } from "../types/api";

export function StopReasonFields({
  reasons,
  code,
  comment,
  onCodeChange,
  onCommentChange,
}: {
  reasons: StopReason[];
  code: string;
  comment: string;
  onCodeChange: (value: string) => void;
  onCommentChange: (value: string) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("pt-BR");
    if (!needle) return reasons;
    return reasons.filter((reason) => `${reason.codigo} ${reason.nome}`.toLocaleLowerCase("pt-BR").includes(needle));
  }, [reasons, search]);
  const selected = reasons.find((reason) => reason.codigo === code);
  // A cor vem da classificação central do backend. O componente não decide
  // planejado/não planejado por grupo de catálogo nem por texto do motivo.
  const variant = (reason: StopReason, base: string) =>
    reason.cor === "warning" ? `${base} ${base}--warning` : base;

  useEffect(() => {
    const needle = search.trim().toLocaleLowerCase("pt-BR");
    if (!needle) return;
    const exact = filtered.find((reason) => reason.codigo.toLocaleLowerCase("pt-BR") === needle);
    const candidate = exact ?? (filtered.length === 1 ? filtered[0] : undefined);
    if (candidate && candidate.codigo !== code) onCodeChange(candidate.codigo);
  }, [code, filtered, onCodeChange, search]);

  return (
    <>
      <label>
        Buscar motivo
        <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Código ou descrição" autoFocus />
      </label>
      <div className="stop-reason-field">
        <strong>Motivo da parada</strong>
        {selected ? <div className={variant(selected, "stop-reason-selected")} data-stop-classification={selected.classificacao}>{selected.codigo} - {selected.nome}</div> : <div className="stop-reason-selected stop-reason-selected--empty">Selecione</div>}
        <div className="stop-reason-options" role="listbox" aria-label="Motivo da parada">
          {filtered.map((reason) => <button type="button" role="option" aria-selected={reason.codigo === code} className={variant(reason, "stop-reason-option")} data-stop-classification={reason.classificacao} key={reason.codigo} onClick={() => onCodeChange(reason.codigo)}>{reason.codigo} - {reason.nome}</button>)}
        </div>
      </div>
      {!filtered.length ? <p className="operator-help">Nenhum motivo corresponde ao filtro informado.</p> : null}
      <label>
        Comentário{selected?.requer_comentario ? " (obrigatório)" : ""}
        <textarea value={comment} onChange={(event) => onCommentChange(event.target.value)} />
      </label>
    </>
  );
}
