import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AsyncButton } from "../components/AsyncButton";
import { useConfirm } from "../components/ConfirmDialog";
import { Notice } from "../components/Notice";
import { OperatorDialog } from "../components/OperatorDialog";

describe("primitives da Onda 1", () => {
  it("AsyncButton não dispara a ação duas vezes enquanto a primeira não volta", async () => {
    let release!: () => void;
    const action = vi.fn(() => new Promise<void>((resolve) => { release = resolve; }));
    render(<AsyncButton onClick={action} pendingLabel="Salvando…">Salvar</AsyncButton>);
    const button = screen.getByRole("button", { name: "Salvar" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(action).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Salvando…" })).toBeDisabled();
    await act(async () => release());
    expect(screen.getByRole("button", { name: "Salvar" })).toBeEnabled();
  });

  it("useConfirm resolve pela escolha e devolve o foco a quem abriu", async () => {
    const results: boolean[] = [];
    function Harness() {
      const [confirm, dialog] = useConfirm();
      return (
        <>
          <button type="button" onClick={async () => results.push(await confirm({ title: "Remover pausa", message: "Sem volta.", confirmLabel: "Remover pausa", tone: "danger" }))}>Abrir</button>
          {dialog}
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Abrir" });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(results).toEqual([false]));
    expect(document.activeElement).toBe(opener);
    fireEvent.click(opener);
    fireEvent.click(await screen.findByRole("button", { name: "Remover pausa" }));
    await waitFor(() => expect(results).toEqual([false, true]));
  });

  it("Enter confirma o diálogo, mas não ação de risco nem campo que trata o Enter", async () => {
    const onConfirm = vi.fn();
    const onScan = vi.fn();
    const { unmount } = render(
      <OperatorDialog title="Finalizar" onCancel={() => undefined}>
        <input aria-label="Boas" />
        <input aria-label="Crachá" onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onScan(); } }} />
        <div className="operator-dialog__actions"><button type="button">Cancelar</button><button type="button" onClick={onConfirm}>Finalizar</button></div>
      </OperatorDialog>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Fechar" }), { key: "Enter" });
    fireEvent.keyDown(screen.getByLabelText("Boas"), { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledTimes(2);
    fireEvent.keyDown(screen.getByLabelText("Crachá"), { key: "Enter" });
    expect(onScan).toHaveBeenCalledTimes(1);
    expect(onConfirm).toHaveBeenCalledTimes(2);
    unmount();

    const onDelete = vi.fn();
    const { unmount: unmount2 } = render(
      <OperatorDialog title="Apagar" onCancel={() => undefined}>
        <div className="operator-dialog__actions"><button type="button">Cancelar</button><button type="button" data-enter="off" onClick={onDelete}>Apagar</button></div>
      </OperatorDialog>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Fechar" }), { key: "Enter" });
    expect(onDelete).not.toHaveBeenCalled();    unmount2();

    const onCancel = vi.fn();
    render(
      <OperatorDialog title="Parada" onCancel={onCancel}>
        <div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" disabled>Confirmar parada</button></div>
      </OperatorDialog>,
    );
    fireEvent.keyDown(screen.getByRole("button", { name: "Fechar" }), { key: "Enter" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("Enter numa opção já escolhida confirma; numa opção nova, só escolhe", () => {
    const onConfirm = vi.fn();
    render(
      <OperatorDialog title="Parada" onCancel={() => undefined}>
        <div role="listbox" aria-label="Motivos">
          <button type="button" role="option" aria-selected="false">0043 - TROCA DE EPI</button>
          <button type="button" role="option" aria-selected="true">0045 - VISITAS</button>
        </div>
        <div className="operator-dialog__actions"><button type="button">Cancelar</button><button type="button" onClick={onConfirm}>Confirmar parada</button></div>
      </OperatorDialog>,
    );
    fireEvent.keyDown(screen.getByRole("option", { name: "0043 - TROCA DE EPI" }), { key: "Enter" });
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("option", { name: "0045 - VISITAS" }), { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("diálogo com autoFocus mantém o campo focado e o foco volta ao botão de origem (AX-02)", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Registrar parada</button>
          {open ? <OperatorDialog title="Parada" onCancel={() => setOpen(false)}><input aria-label="Motivo" autoFocus /></OperatorDialog> : null}
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Registrar parada" });
    opener.focus();
    fireEvent.click(opener);
    expect(document.activeElement).toBe(screen.getByLabelText("Motivo"));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(document.activeElement).toBe(opener);
  });

  it("Notice anuncia erro como alert e o resto como status", () => {
    render(<><Notice tone="error">Falhou</Notice><Notice tone="success">Salvo</Notice></>);
    expect(screen.getByRole("alert")).toHaveTextContent("Falhou");
    expect(screen.getByRole("status")).toHaveTextContent("Salvo");
  });
});
