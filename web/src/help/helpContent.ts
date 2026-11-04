/**
 * Conteúdo do manual: cada tópico é um arquivo .md em `content/<manual>/`.
 * Cabeçalho do arquivo (entre `---`):
 *   titulo: nome do tópico na árvore
 *   grupo:  pasta da árvore (opcional)
 *   ordem:  número para ordenar (menor primeiro)
 *   rotas:  telas do sistema que abrem este tópico (separadas por vírgula)
 * O id do tópico é o nome do arquivo sem extensão (ex.: `10-ordens`).
 */
export type ManualId = "operador" | "gestao";

export interface HelpTopic {
  manual: ManualId;
  id: string;
  titulo: string;
  grupo: string;
  ordem: number;
  rotas: string[];
  corpo: string;
}

export const MANUAIS: Record<ManualId, { titulo: string; subtitulo: string }> = {
  operador: { titulo: "Manual do Operador", subtitulo: "Tela de apontamento do chão de fábrica" },
  gestao: { titulo: "Manual da Gestão", subtitulo: "Telas de acompanhamento, análise e administração" },
};

const arquivos = import.meta.glob("./content/**/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

function lerCabecalho(texto: string): { meta: Record<string, string>; corpo: string } {
  const normal = texto.replace(/^﻿/, "").replace(/\r\n/g, "\n");
  const achou = /^---\n([\s\S]*?)\n---\n?/.exec(normal);
  if (!achou) return { meta: {}, corpo: normal };
  const meta: Record<string, string> = {};
  for (const linha of achou[1].split("\n")) {
    const i = linha.indexOf(":");
    if (i > 0) meta[linha.slice(0, i).trim()] = linha.slice(i + 1).trim();
  }
  return { meta, corpo: normal.slice(achou[0].length) };
}

function montar(): HelpTopic[] {
  const lista: HelpTopic[] = [];
  for (const [caminho, texto] of Object.entries(arquivos)) {
    const partes = /\.\/content\/(operador|gestao)\/([^/]+)\.md$/.exec(caminho);
    if (!partes) continue;
    const { meta, corpo } = lerCabecalho(texto);
    lista.push({
      manual: partes[1] as ManualId,
      id: partes[2],
      titulo: meta.titulo || partes[2],
      grupo: meta.grupo || "",
      ordem: Number(meta.ordem) || 0,
      rotas: (meta.rotas || "").split(",").map((r) => r.trim()).filter(Boolean),
      corpo,
    });
  }
  return lista.sort((a, b) => a.ordem - b.ordem || a.id.localeCompare(b.id));
}

export const HELP_TOPICS: HelpTopic[] = montar();

export function topicosDoManual(manual: ManualId): HelpTopic[] {
  return HELP_TOPICS.filter((t) => t.manual === manual);
}

export function acharTopico(manual: ManualId, id?: string): HelpTopic | undefined {
  const lista = topicosDoManual(manual);
  return lista.find((t) => t.id === id) ?? lista[0];
}

/** Tópico mais específico (maior prefixo de rota) que cobre a tela atual. */
export function topicoParaRota(manual: ManualId, pathname: string): HelpTopic | undefined {
  let melhor: HelpTopic | undefined;
  let tamanho = -1;
  for (const t of topicosDoManual(manual)) {
    for (const rota of t.rotas) {
      const bate = pathname === rota || pathname.startsWith(`${rota}/`);
      if (bate && rota.length > tamanho) { melhor = t; tamanho = rota.length; }
    }
  }
  return melhor;
}

export function normalizar(texto: string): string {
  return texto.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

export function buscarTopicos(manual: ManualId, termo: string): HelpTopic[] {
  const q = normalizar(termo.trim());
  if (!q) return [];
  return topicosDoManual(manual).filter((t) => normalizar(`${t.titulo} ${t.corpo}`).includes(q));
}
