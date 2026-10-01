import { ApiError, apiErrorMessage } from "../../api/client";
import type { OperatorStation } from "../../types/api";

/**
 * Quem decide se um posto aceita outra OP é o backend
 * (`aceita_producao_simultanea`). Estas funções só traduzem a resposta em
 * frases para o operador, sem recalcular a regra.
 */
export const STATION_EXCLUSIVE_REASON =
  "Há setup ou retrabalho em andamento neste posto. Finalize-o antes de iniciar outra OP.";

/** Aviso no seletor de postos: o card segue selecionável para retomar/finalizar. */
export const STATION_EXCLUSIVE_NOTICE =
  "Há setup ou retrabalho em andamento neste posto. Entre para retomá-lo ou finalizá-lo.";

export const OP_ALREADY_POINTED_MESSAGE = "Esta OP já foi apontada em outra estação.";

/** Posto só recusa outra OP (Iniciar) quando o backend diz que não aceita produção simultânea. */
export function stationIsBlocked(station?: Pick<OperatorStation, "aceita_producao_simultanea" | "ocupantes_total"> | null) {
  return Boolean(station && (station.ocupantes_total ?? 0) > 0 && station.aceita_producao_simultanea === false);
}

/** "Em uso por 2 OP(s)" — vazio quando o posto está livre. */
export function stationUsageLabel(station?: Pick<OperatorStation, "ocupantes_total"> | null) {
  const total = station?.ocupantes_total ?? 0;
  return total > 0 ? `Em uso por ${total} OP(s)` : "";
}

/** Mensagem de erro de ação do operador, sem códigos técnicos. */
export function operatorActionErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) {
    if (reason.code === "operator_resource_occupied") {
      return reason.details && (reason.details as { aceita_producao_simultanea?: boolean }).aceita_producao_simultanea === false
        ? STATION_EXCLUSIVE_REASON
        : reason.message;
    }
    if (reason.code === "operacao_ja_apontada_em_outra_estacao") return OP_ALREADY_POINTED_MESSAGE;
  }
  return apiErrorMessage(reason);
}
