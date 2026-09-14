import fs from "node:fs/promises";
import {
  FileBlob,
  SpreadsheetFile,
} from "file:///C:/Users/logistica.unidade4/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const outputDir = "C:/Users/logistica.unidade4/Documents/Sistema - Iago/Gestor de Peças - Area de Testes/outputs/01a02016-6015-7eb2-b9a8-392d9a67d455";
const inputPath = `${outputDir}/intermediate_report.xlsx`;
const outputPath = `${outputDir}/Gestor_de_Pecas_Relatorio_Producao.xlsx`;
const previewsDir = `${outputDir}/previews`;
const verifyOnly = process.env.GESTOR_ARTIFACT_VERIFY_ONLY === "1";

const input = await FileBlob.load(verifyOnly ? outputPath : inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheetNames = [
  "Resumo",
  "Produção por setor",
  "Resumo por setor",
  "Produção por produto",
  "Motivos de refugo",
  "Motivos de retrabalho",
];

const sheets = await workbook.inspect({
  kind: "sheet",
  include: "id,name",
  maxChars: 4000,
});
console.log("SHEETS");
console.log(sheets.ndjson);

for (const sheetName of sheetNames) {
  const region = await workbook.inspect({
    kind: "region",
    sheetId: sheetName,
    range: sheetName === "Resumo" ? "A1:H25" : "A1:N16",
    maxChars: 8000,
    tableMaxRows: 16,
    tableMaxCols: 11,
    tableMaxCellChars: 120,
  });
  console.log(`REGION ${sheetName}`);
  console.log(region.ndjson);
}

const formulas = await workbook.inspect({
  kind: "formula",
  maxChars: 4000,
  options: { maxResults: 200 },
});
console.log("FORMULAS");
console.log(formulas.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#(REF!|DIV/0!|VALUE!|NAME\\?|N/A|NUM!|NULL!)",
  maxChars: 4000,
  options: { useRegex: true, matchFormulas: true, maxResults: 200 },
});
console.log("FORMULA_ERRORS");
console.log(formulaErrors.ndjson);

await fs.mkdir(previewsDir, { recursive: true });
for (const [index, sheetName] of sheetNames.entries()) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const bytes = new Uint8Array(await preview.arrayBuffer());
  const fileName = `${String(index + 1).padStart(2, "0")}_${sheetName.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9]+/g, "_")}.png`;
  await fs.writeFile(`${previewsDir}/${fileName}`, bytes);
}

if (verifyOnly) {
  console.log(`VERIFIED ${outputPath}`);
} else {
  const exported = await SpreadsheetFile.exportXlsx(workbook);
  await exported.save(outputPath);
  console.log(`OUTPUT ${outputPath}`);
}
