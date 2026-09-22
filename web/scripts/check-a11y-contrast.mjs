import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const cssPath = fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url));
const css = readFileSync(cssPath, "utf8");

function block(selector) {
  const start = css.indexOf(selector);
  if (start < 0) throw new Error(`Bloco CSS ausente: ${selector}`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open + 1);
  if (open < 0 || close < 0) throw new Error(`Bloco CSS inválido: ${selector}`);
  return css.slice(open + 1, close);
}

function variables(source) {
  return Object.fromEntries(
    [...source.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)]
      .map((match) => [match[1], match[2].toLowerCase()]),
  );
}

function luminance(hex) {
  const channels = [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(foreground, background) {
  const left = luminance(foreground);
  const right = luminance(background);
  return (Math.max(left, right) + 0.05) / (Math.min(left, right) + 0.05);
}

const pairs = [
  ["muted", "surface"],
  ["muted", "surface-alt"],
  ["muted", "bg"],
  ["on-primary", "primary"],
  ["on-accent", "accent"],
  ["on-warning", "warning"],
  ["on-danger", "danger"],
  ["on-state-setup", "state-setup"],
  ["on-state-rework", "state-rework"],
  ["on-orange", "orange"],
  ["on-operator-start", "operator-start"],
  ["on-operator-stop", "operator-stop"],
  ["on-operator-finish", "operator-finish"],
  ["success-ink", "accent-soft"],
  ["warning-ink", "warning-soft"],
  ["teal-ink", "surface"],
];

const light = variables(block(":root {"));
const dark = { ...light, ...variables(block(':root[data-theme="dark"] {')) };

let failed = false;
for (const [theme, colors] of [["light", light], ["dark", dark]]) {
  for (const [foreground, background] of pairs) {
    if (!colors[foreground] || !colors[background]) {
      console.error(`[a11y] ${theme}: token ausente --${foreground} ou --${background}`);
      failed = true;
      continue;
    }
    const ratio = contrast(colors[foreground], colors[background]);
    if (ratio < 4.5) {
      console.error(`[a11y] ${theme}: --${foreground} sobre --${background} = ${ratio.toFixed(2)}:1 (< 4.5:1)`);
      failed = true;
    }
  }
}

if (failed) process.exit(1);
console.log("[a11y] Contraste AA dos pares semânticos: OK");
