import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { DatePicker } from "../components/DatePicker";
import { OperatorDialog } from "../components/OperatorDialog";

describe("gate de acessibilidade", () => {

  it("prende o foco no OperatorDialog, fecha com Escape e devolve foco ao gatilho", () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Abrir</button>
          {open ? (
            <OperatorDialog title="Confirmar operação" onCancel={() => setOpen(false)}>
              <button type="button">Confirmar</button>
            </OperatorDialog>
          ) : null}
        </>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Abrir" });
    trigger.focus();
    fireEvent.click(trigger);

    const close = screen.getByRole("button", { name: "Fechar" });
    const confirm = screen.getByRole("button", { name: "Confirmar" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("permite navegar no calendário com setas e restaura o foco ao fechar", () => {
    render(<DatePicker label="Data inicial" value="2026-09-22" onChange={() => undefined} />);
    const input = screen.getByRole("textbox", { name: "Data inicial" });
    input.focus();
    fireEvent.click(input);

    const selected = document.querySelector<HTMLButtonElement>('[data-date="2026-09-22"]');
    expect(selected).not.toBeNull();
    expect(selected).toHaveFocus();

    fireEvent.keyDown(selected!, { key: "ArrowRight" });
    const next = document.querySelector<HTMLButtonElement>('[data-date="2026-09-23"]');
    expect(next).not.toBeNull();
    expect(next).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Calendário de Data inicial" })).not.toBeInTheDocument();
    expect(input).toHaveFocus();
  });
});
