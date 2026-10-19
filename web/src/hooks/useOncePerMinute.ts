import { useRef } from "react";

/**
 * Segura `value` e só o troca quando o minuto do relógio vira. Serve para totais somados de N recursos,
 * que sobem N minutos por minuto: atualizando a cada poucos segundos, pareciam contar segundos.
 * Troca na hora quando `key` muda (ex.: outro filtro) ou quando ainda não havia valor.
 */
export function useOncePerMinute<T>(value: T, key: string): T {
  const minute = Math.floor(Date.now() / 60_000);
  const held = useRef<{ value: T; minute: number; key: string } | null>(null);
  const current = held.current;
  if (!current || current.value == null || current.key !== key || current.minute !== minute) {
    held.current = { value, minute, key };
  }
  return held.current!.value;
}
