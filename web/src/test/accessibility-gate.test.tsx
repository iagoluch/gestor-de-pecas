import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import tokensCss from "../styles/tokens.css?raw";
import { DatePicker } from "../components/DatePicker";
import { OperatorDialog } from "../components/OperatorDialog";

type Palette = Record<string, string>;

function variables(block: string): Palette {
  return Object.fromEntries(
    Array.from(block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g), (match) => [match[1], match[2]]),
  );
}

function palette(marker: string) {
  const start = tokensCss.indexOf(marker);
  if (start < 0) throw new Error(`Bloco de tokens não encontrado: ${marker}`);
  const open = tokensCss.indexOf("{", start);
  const close = tokensCss.indexOf("}", open + 1);
  if (open < 0 || close < 0) throw new Error(`Bloco de tokens inválido: ${marker}`);
  return variables(tokensCss.slice(open + 1, close));
}

function luminance(hex: string) {
  const channels = [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground: string, background: string) {
  const left = luminance(foreground);
  const right = luminance(background);
  const light = Math.max(left, right);
  const dark = Math.min(left, right);
  return (light + 0.05) / (dark + 0.05);
}

function expectAa(paletteValues: Palette, foreground: string, background: string) {
  const ratio = contrast(paletteValues[foreground], paletteValues[background]);
  expect(ratio, `${foreground} sobre ${background}: ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5);
}

describe("gate de acessibilidade", () => {
  it("mantém contraste AA dos pares semânticos nos temas claro e escuro", () => {
    const light = palette(":root {");
    const darkOverrides = palette(':root[data-theme="dark"] {');
    const dark = { ...light, ...darkOverrides };

    for (const colors of [light, dark]) {
      expectAa(colors, "muted", "surface");
      expectAa(colors, "muted", "surface-alt");
      expectAa(colors, "muted", "bg");
      expectAa(colors, "on-primary", "primary");
      expectAa(colors, "on-warning", "warning");
      expectAa(colors, "on-danger", "danger");
      expectAa(colors, "on-state-setup", "state-setup");
      expectAa(colors, "on-state-rework", "state-rework");
      expectAa(colors, "on-orange", "orange");
      expectAa(colors, "on-operator-start", "operator-start");
      expectAa(colors, "on-operator-stop", "operator-stop");
      expectAa(colors, "on-operator-finish", "operator-finish");
      expectAa(colors, "success-ink", "accent-soft");
      expectAa(colors, "warning-ink", "warning-soft");
      expectAa(colors, "teal-ink", "surface");
    }
  });

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
