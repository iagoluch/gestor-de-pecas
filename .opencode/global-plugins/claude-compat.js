// Plugin GLOBAL do OpenCode (copiado para ~/.config/opencode/plugins/ por
// scripts/export_opencode.py). Equivale aos hooks globais do Claude Code:
// task-observer (SessionStart), memória por projeto e esforço máximo do Nemotron.
import { existsSync, readdirSync, readFileSync } from "node:fs"
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

// Mesma regra do Claude Code: todo caractere fora de [A-Za-z0-9] vira "-".
function memoryDir(worktree) {
  if (!worktree || !existsSync(PROJECTS)) return null
  const id = worktree.replace(/[^A-Za-z0-9]/g, "-").toLowerCase()
  const match = readdirSync(PROJECTS).find((d) => d.toLowerCase() === id)
  const dir = match && join(PROJECTS, match, "memory")
  return dir && existsSync(join(dir, "MEMORY.md")) ? dir : null
}

export const ClaudeCompat = async ({ worktree, directory }) => {
  const memDir = memoryDir(worktree) ?? memoryDir(directory)

  return {
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(TASK_OBSERVER)
      if (memDir) {
        const index = readFileSync(join(memDir, "MEMORY.md"), "utf8")
        output.system.push(
          `# Memoria persistente do projeto (exportada do Claude Code)\n` +
            `Diretorio: ${memDir}\n` +
            `Cada linha aponta para um arquivo .md desse diretorio; leia o arquivo quando o assunto ` +
            `for relevante. Fatos podem estar desatualizados: confirme no codigo antes de agir.\n\n${index}`,
        )
      }
    },

    // Esforço máximo: o OpenCode limita a saída a 32k por padrão; o raciocínio
    // longo do Nemotron precisa de mais espaço.
    "chat.params": async (input, output) => {
      if (!input.model?.id?.includes("nemotron")) return
      const limit = input.model.limit ?? {}
      const room = Math.min(limit.output ?? 32000, 128000, Math.floor((limit.context ?? 128000) / 4))
      output.maxOutputTokens = Math.max(output.maxOutputTokens ?? 0, room)
    },

    "experimental.session.compacting": async (_input, output) => {
      output.context.push(COMPACTION)
    },
  }
}
