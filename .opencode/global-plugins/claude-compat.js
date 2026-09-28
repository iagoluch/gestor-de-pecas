// Plugin GLOBAL do OpenCode (copiado para ~/.config/opencode/plugins/ por
// scripts/export_opencode.py). Equivale aos hooks globais do Claude Code:
// task-observer (SessionStart), memória por projeto (leitura + caixa de entrada
// revisada pelo Claude) e esforço máximo do Nemotron.
//
// Dois formatos no mesmo arquivo: `export default {id, setup}` para o OpenCode
// 2.x (Desktop) e o export nomeado `ClaudeCompat` para a CLI 1.x.
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

const PROJECTS = join(homedir(), ".claude", "projects")

const TASK_OBSERVER =
  "Antes da primeira chamada de ferramenta da sessao (e antes de propor qualquer plano): " +
  'carregue a skill "task-observer" com a ferramenta `skill` e execute seu Session Start Protocol ' +
  "(checagem de storage, varredura de frontmatter do observation-log, checagem de review trigger). " +
  "Carregar a skill e rodar o protocolo sao passos separados. Depois de concluir cada tarefa, " +
  "reporte em 1 linha as observacoes registradas nesta sessao (ids e titulos, ou 'nenhuma registrada')."

const COMPACTION =
  "Ao resumir, preserve: objetivo e restricoes do usuario; decisoes relevantes; alteracoes feitas " +
  "(com caminhos de arquivo); testes/validacoes executados e seus resultados; pendencias reais; " +
  "proximos passos. O resumo deve permitir retomar sem re-investigar do zero."

const MEMORY_RULES =
  "# Gravar memoria (ferramenta `memoria_salvar`)\n" +
  "Chame `memoria_salvar` na hora, sem pedir permissao, quando o usuario: corrigir sua abordagem; " +
  "explicar uma regra, preferencia ou fato do projeto que valha para sessoes futuras; ou confirmar " +
  "uma decisao nao obvia. Inclua o porque e como aplicar. NAO salve: detalhes so da tarefa atual, " +
  "o que ja esta no codigo/git/AGENTS.md, nem o que ja esta na memoria acima. As memorias vao para " +
  "uma caixa de entrada revisada pelo Claude; nao edite o MEMORY.md nem os arquivos de memoria diretamente.\n" +
  "No OpenCode 2.x ela fica dentro da ferramenta `execute`: " +
  "`await tools.memoria_salvar({ nome, tipo, descricao, conteudo })`."

const MEMORIA_TOOL = {
  name: "memoria_salvar",
  description:
    "Salva uma memoria duradoura do projeto (correcao, preferencia, regra ou fato que o usuario " +
    "explicou) para as proximas sessoes do OpenCode e do Claude Code.",
  fields: {
    nome: "slug curto em kebab-case, ex.: feedback-sem-botao-em-tv",
    tipo: "user | feedback | project | reference",
    descricao: "uma linha: do que se trata, para decidir relevancia",
    conteudo: "o fato; em feedback/project inclua linhas **Why:** e **How to apply:**",
  },
}

// Mesma regra do Claude Code: todo caractere fora de [A-Za-z0-9] vira "-".
function memoryDir(worktree) {
  if (!worktree) return null
  const id = worktree.replace(/[^A-Za-z0-9]/g, "-")
  const match = existsSync(PROJECTS) && readdirSync(PROJECTS).find((d) => d.toLowerCase() === id.toLowerCase())
  return join(PROJECTS, match || id, "memory")
}

function saveToInbox(memDir, { nome, tipo, descricao, conteudo }) {
  if (!memDir) return "Sem diretorio de projeto; memoria nao salva."
  const inbox = join(memDir, "inbox")
  mkdirSync(inbox, { recursive: true })
  const file = join(inbox, `${nome}.md`)
  const now = new Date().toISOString()
  if (existsSync(file)) {
    appendFileSync(file, `\n\n## Atualizacao ${now}\n\n${conteudo.trim()}\n`, "utf8")
    return `Memoria "${nome}" ja estava na caixa de entrada; conteudo acrescentado.`
  }
  const header = [
    "---",
    `name: ${nome}`,
    `description: ${JSON.stringify(descricao)}`,
    "metadata:",
    `  type: ${tipo}`,
    "  source: opencode-nemotron",
    `  created: ${now}`,
    "---",
  ].join("\n")
  writeFileSync(file, `${header}\n\n${conteudo.trim()}\n`, "utf8")
  return `Memoria "${nome}" salva na caixa de entrada (${file}); o Claude revisa e promove na proxima sessao.`
}

function systemBlocks(memDir) {
  const blocks = [TASK_OBSERVER]
  const index = memDir && join(memDir, "MEMORY.md")
  if (index && existsSync(index)) {
    blocks.push(
      `# Memoria persistente do projeto (compartilhada com o Claude Code)\n` +
        `Diretorio: ${memDir}\n` +
        `Cada linha aponta para um arquivo .md desse diretorio; leia o arquivo quando o assunto ` +
        `for relevante. Fatos podem estar desatualizados: confirme no codigo antes de agir.\n\n` +
        readFileSync(index, "utf8"),
    )
  }
  if (memDir) blocks.push(MEMORY_RULES)
  return blocks
}

// Esforço máximo: o OpenCode limita a saída a 32k por padrão; o raciocínio
// longo do Nemotron precisa de mais espaço.
function nemotronOutput(limit = {}) {
  return Math.min(limit.output ?? 32000, 128000, Math.floor((limit.context ?? 128000) / 4))
}

// ---- OpenCode 1.x (CLI) ----------------------------------------------------
export const ClaudeCompat = async ({ worktree, directory }) => {
  const { tool } = await import("@opencode-ai/plugin")
  const memDir = memoryDir(worktree) ?? memoryDir(directory)
  const { fields } = MEMORIA_TOOL

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(...systemBlocks(memDir))
    },

    tool: {
      [MEMORIA_TOOL.name]: tool({
        description: MEMORIA_TOOL.description,
        args: {
          nome: tool.schema.string().regex(/^[a-z0-9-]+$/).describe(fields.nome),
          tipo: tool.schema.enum(["user", "feedback", "project", "reference"]),
          descricao: tool.schema.string().describe(fields.descricao),
          conteudo: tool.schema.string().describe(fields.conteudo),
        },
        async execute(args) {
          return saveToInbox(memDir, args)
        },
      }),
    },

    "chat.params": async (input, output) => {
      if (!input.model?.id?.includes("nemotron")) return
      output.maxOutputTokens = Math.max(output.maxOutputTokens ?? 0, nemotronOutput(input.model.limit))
    },

    "experimental.session.compacting": async (_input, output) => {
      output.context.push(COMPACTION)
    },
  }
}

// ---- OpenCode 2.x (Desktop) ------------------------------------------------
export default {
  id: "claude-compat",
  // 1.x: com export default, a CLI exige `server` (o plugin no formato antigo).
  server: ClaudeCompat,
  setup: async (ctx) => {
    const loc = ctx.location ?? {}
    const memDir = memoryDir(loc.project?.directory) ?? memoryDir(loc.directory)
    const text = (t) => ({ type: "text", text: t })
    const limits = new Map()

    const outputLimit = async (model) => {
      const key = `${model.providerID}/${model.id}`
      if (!limits.has(key)) {
        const list = await ctx.model.list().catch(() => null)
        const info = list?.data?.find((m) => m.providerID === model.providerID && m.id === model.id)
        limits.set(key, nemotronOutput(info?.limit))
      }
      return limits.get(key)
    }

    await ctx.session.hook("context", async (p) => {
      p.system.push(...systemBlocks(memDir).map(text))
      if (p.model?.id?.includes("nemotron")) {
        p.options.maxTokens = Math.max(p.options.maxTokens ?? 0, await outputLimit(p.model))
      }
    })

    await ctx.session.hook("compaction", (p) => {
      p.system.push(text(COMPACTION))
    })

    const { fields } = MEMORIA_TOOL
    await ctx.tool.transform((tools) =>
      tools.add({
        name: MEMORIA_TOOL.name,
        description: MEMORIA_TOOL.description,
        // Fica no code mode (tools.memoria_salvar dentro de `execute`): é lá que o
        // Nemotron do Desktop procura ferramentas que não são as nativas.
        input: {
          type: "object",
          properties: {
            nome: { type: "string", pattern: "^[a-z0-9-]+$", description: fields.nome },
            tipo: { type: "string", enum: ["user", "feedback", "project", "reference"] },
            descricao: { type: "string", description: fields.descricao },
            conteudo: { type: "string", description: fields.conteudo },
          },
          required: ["nome", "tipo", "descricao", "conteudo"],
          additionalProperties: false,
        },
        execute: async (args) => ({ content: saveToInbox(memDir, args) }),
      }),
    )
  },
}
