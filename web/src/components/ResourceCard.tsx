import { Link } from "react-router-dom";
import type { ResourceRow } from "../types/management";
import { formatDateTime, formatDuration } from "../utils/format";
import { StatusBadge } from "./StatusBadge";

export function ResourceCard({ resource }: { resource: ResourceRow }) {
  const operation = resource.ops_ativas[0];
  return (
    <article className="resource-card">
      <header>
        <div><strong>{resource.recurso}</strong><span>{resource.setor ?? "Setor não informado"}</span></div>
        <StatusBadge value={resource.categoria ?? resource.codigo_status} />
      </header>
      <dl>
        <div><dt>OP</dt><dd>{operation?.op ? <Link to={`/rastreabilidade/op-produto?op=${encodeURIComponent(operation.op)}`}>{operation.op}</Link> : "Não disponível"}</dd></div>
        <div><dt>Operação</dt><dd>{operation?.operacao ?? "Não disponível"}</dd></div>
        <div><dt>Produto</dt><dd>{operation?.produto ?? "Não disponível"}</dd></div>
        <div><dt>Operador</dt><dd>{operation?.operador_inicio ?? "Não disponível"}</dd></div>
        <div><dt>Início</dt><dd>{formatDateTime(resource.inicio ?? operation?.inicio)}</dd></div>
        <div><dt>Duração</dt><dd>{formatDuration(resource.duracao_segundos)}</dd></div>
      </dl>
      {resource.motivo ? <p>{resource.motivo}</p> : null}
    </article>
  );
}

