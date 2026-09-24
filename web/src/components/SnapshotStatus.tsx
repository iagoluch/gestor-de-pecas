const hhmm = (at: number) => new Date(at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });

/**
 * Situação do snapshot de um painel de TV (AN-05): em operação normal, um
 * carimbo discreto de "Atualizado às hh:mm"; com a atualização falhando, a
 * faixa diz de quando são os dados na tela. A reconexão já é automática
 * (tempo real + releitura periódica), então não há botão para ninguém clicar.
 */
export function SnapshotStatus({ error, updatedAt, staleClassName }: { error: unknown; updatedAt: number | null; staleClassName: string }) {
  if (error) {
    return (
      <div className={staleClassName} role="alert">
        Sem conexão com o servidor{updatedAt ? ` — dados de ${hhmm(updatedAt)}` : ""}. Reconectando automaticamente.
      </div>
    );
  }
  return updatedAt ? <p className="snapshot-stamp">Atualizado às {hhmm(updatedAt)}</p> : null;
}
