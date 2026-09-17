import fs from "node:fs/promises";
import path from "node:path";

// Ferramenta auxiliar de homologação: renderiza prévias das abas do workbook.
// A dependência de renderização é opcional e NÃO faz parte do runtime do Gestor
// de Peças. Sem ela o script encerra com aviso e código 0, para não reprovar
// pipelines por uma capacidade que é só de inspeção visual.
let FileBlob;
let SpreadsheetFile;
try {
  ({ FileBlob, SpreadsheetFile } = await import("@oai/artifact-tool"));
} catch (error) {
  if (error?.code !== "ERR_MODULE_NOT_FOUND") throw error;
  console.warn(
    "[previa-indisponivel] O pacote opcional '@oai/artifact-tool' não está instalado. " +
    "A geração de prévias foi ignorada; a validação do workbook não depende dela.",
  );
  process.exit(0);
}

const [inputPath, outputDir] = process.argv.slice(2);
if (!inputPath || !outputDir) {
  throw new Error("Uso: verify_report_artifact.mjs INPUT.xlsx OUTPUT_DIR");
}

await fs.mkdir(outputDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheetInspection = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 8000,
});
const expectedSheets = [
  "Visão Geral", "Indicadores", "Produção", "OPs", "Paradas", "Setup",
  "Qualidade", "Recursos", "Setores", "Nestings", "Exceções", "Auditoria",
];
const previews = [];
for (const sheetName of expectedSheets) {
  const preview = await workbook.render({
    sheetName,
    range: "A1:H20",
    scale: 1,
    format: "png",
  });
  const safeName = sheetName.normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_|_$/g, "")
    .toLowerCase();
  const target = path.join(outputDir, `${safeName}.png`);
  await fs.writeFile(target, new Uint8Array(await preview.arrayBuffer()));
  previews.push(target);
}
const formulaInspection = await workbook.inspect({
  kind: "formula",
  maxChars: 4000,
  options: { maxResults: 100 },
});
console.log(JSON.stringify({
  input: inputPath,
  sheets: sheetInspection.ndjson,
  formulas: formulaInspection.ndjson,
  previews,
}, null, 2));
