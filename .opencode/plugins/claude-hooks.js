// Hooks do projeto no OpenCode — espelho de .claude/settings.json e
// .claude/settings.local.json do Claude Code. Não bloqueia nada: os resultados
// dos hooks são anexados à saída da ferramenta para o modelo agir sobre eles.
//
// Dois formatos no mesmo arquivo: `export default {id, setup}` para o OpenCode
// 2.x (Desktop) e o export nomeado `ClaudeHooks` para a CLI 1.x.
import { execFile, spawn } from "node:child_process"
import { existsSync, mkdirSync, openSync } from "node:fs"
import { connect } from "node:net"
import { homedir } from "node:os"
import { isAbsolute, join, relative } from "node:path"

const BIG_OUTPUT = 12000
const SEARCH_CMD = /\b(grep|rg|find|findstr|Select-String)\b/

const PONYTAIL =
  "Lembrete automatico (hook): se o pedido envolver escrever/alterar/revisar codigo, carregue a " +
  'skill "ponytail" com a ferramenta `skill` — solucao mais simples e minima que funciona, YAGNI, ' +
  "sem over-engineering. Ignore se o pedido nao for sobre codigo."

const GRAPHIFY =
  "[hook graphify] graphify-out/graph.json existe: rode `graphify query \"<pergunta>\"` antes de " +
  "varrer arquivos com grep/glob. `graphify` e um programa de linha de comando: execute-o com a " +
  "ferramenta de shell (`shell`/`bash`), nao e ferramenta nem MCP. So use grep depois que o " +
  "graphify te orientar, ou para alterar/depurar linhas especificas."

const HEADROOM =
  "[hook headroom] Saida grande (>12k caracteres): comprima com a ferramenta `headroom_compress` " +
  "do servidor MCP headroom antes de continuar (no OpenCode 2.x as ferramentas MCP ficam dentro de " +
  "`execute`: procure a que termina em `headroom_compress` e chame por ela). Se o headroom " +
  "classificar como router:noop, siga normalmente."

function run(cmd, args, opts = {}) {
  return new Promise((resolve) => {
    const child = execFile(cmd, args, { timeout: 180000, maxBuffer: 16 << 20, ...opts }, (err, stdout, stderr) =>
      resolve({ code: err ? (err.code ?? 1) : 0, out: `${stdout ?? ""}${stderr ?? ""}`.trim() }),
    )
    if (opts.input !== undefined) child.stdin.end(opts.input)
  })
}

function detached(cmd, args, cwd, logFile) {
  const out = logFile ? openSync(logFile, "a") : "ignore"
  spawn(cmd, args, { cwd, detached: true, stdio: ["ignore", out, out], windowsHide: true }).unref()
}

function portOpen(port) {
  return new Promise((resolve) => {
    const sock = connect(port, "127.0.0.1")
    sock.setTimeout(1000)
    sock.once("connect", () => (sock.destroy(), resolve(true)))
    sock.once("error", () => resolve(false))
    sock.once("timeout", () => (sock.destroy(), resolve(false)))
  })
}

// Saída de hook no formato Claude: JSON (reason/additionalContext/systemMessage) ou texto puro.
function hookMessage(raw) {
  if (!raw) return ""
  try {
    const data = JSON.parse(raw)
    return [data.reason, data.hookSpecificOutput?.additionalContext, data.systemMessage].filter(Boolean).join("\n")
  } catch {
    return raw
  }
}

// Lógica comum às duas versões do OpenCode, com nomes de ferramenta neutros:
// edição = {path}, busca = grep/glob/comando de shell.
async function createHooks(root) {
  const web = join(root, "web")
  const tsc = join(web, "node_modules", "typescript", "bin", "tsc")
  const hasGraph = () => existsSync(join(root, "graphify-out", "graph.json"))
  const impeccableDir = join(root, ".claude", "skills", "impeccable", "scripts")
  const impeccable =
    process.platform === "win32"
      ? join(impeccableDir, "bin", "windows-x64", "impeccable.exe")
      : join(impeccableDir, "impeccable")
  const stopActive = new Set()

  const impeccableHook = async (payload) => {
    if (!existsSync(impeccable)) return ""
    const res = await run(impeccable, ["hook"], {
      cwd: root,
      input: JSON.stringify({ cwd: root, ...payload }),
      env: { ...process.env, CLAUDE_PROJECT_DIR: root },
    })
    return hookMessage(res.out)
  }

  // SessionStart: sincroniza a workforce/exportação e sobe o proxy headroom (sem bloquear).
  const python = process.platform === "win32" ? "python" : "python3"
  // Em sequência (a exportação lê os agentes que a instalação escreve), sem await.
  const sync = (script) => run(python, [join("scripts", script), "--quiet"], { cwd: root })
  sync("install_global_workforce.py").then(() => sync("export_opencode.py"))
  // ~/.local/share/uv/bin primeiro: o de ~/.local/bin pode apontar para um venv que
  // só existe dentro do Claude Desktop (MSIX) — ver shared_launcher em export_opencode.py.
  const exe = process.platform === "win32" ? "headroom.exe" : "headroom"
  const headroom = [join(homedir(), ".local", "share", "uv", "bin", exe), join(homedir(), ".local", "bin", exe)].find(existsSync)
  if (headroom && !(await portOpen(8787))) {
    const logDir = join(homedir(), ".headroom-run")
    mkdirSync(logDir, { recursive: true })
    detached(headroom, ["proxy"], root, join(logDir, "headroom_proxy.log"))
  }

  return {
    // PostToolUse Edit|Write -> type-check + impeccable
    async afterEdit({ path, kind, sessionID }) {
      const notes = []
      const abs = isAbsolute(path) ? path : join(root, path)
      const rel = relative(root, abs).replace(/\\/g, "/")

      if (/^web\/.*\.tsx?$/.test(rel) && existsSync(tsc)) {
        const res = await run("node", [tsc, "-b", "tsconfig.json", "--pretty", "false"], { cwd: web })
        if (res.code !== 0) notes.push(`[hook type-check] Erros de type-check TypeScript (tsc -b) — corrija:\n${res.out}`)
      }

      const msg = await impeccableHook({
        hook_event_name: "PostToolUse",
        tool_name: kind,
        tool_input: { file_path: abs },
        session_id: sessionID,
      })
      if (msg) notes.push(`[hook impeccable]\n${msg}`)
      return notes
    },

    // PreToolUse Bash|Grep|Glob -> graphify primeiro
    searchNotes({ tool, command }) {
      const searching = tool === "grep" || tool === "glob" || (command !== undefined && SEARCH_CMD.test(command))
      return searching && hasGraph() ? [GRAPHIFY] : []
    },

    // PostToolUse Bash|Grep -> headroom em saídas grandes
    sizeNotes(outputLength) {
      return outputLength > BIG_OUTPUT ? [HEADROOM] : []
    },

    // Stop -> impeccable (passe final); devolve a mensagem para reenviar à sessão, ou "".
    async onStop(sessionID) {
      const msg = await impeccableHook({
        hook_event_name: "Stop",
        session_id: sessionID,
        stop_hook_active: stopActive.has(sessionID),
      })
      if (!msg || stopActive.has(sessionID)) {
        stopActive.delete(sessionID)
        return ""
      }
      stopActive.add(sessionID)
      return `[hook impeccable]\n${msg}`
    },
  }
}

// ---- OpenCode 1.x (CLI) ----------------------------------------------------
export const ClaudeHooks = async ({ worktree, client }) => {
  const hooks = await createHooks(worktree)

  return {
    // UserPromptSubmit -> ponytail
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(PONYTAIL)
    },

    "tool.execute.after": async (input, output) => {
      const tool = input.tool
      const args = input.args ?? {}
      const notes = []
      if ((tool === "edit" || tool === "write") && args.filePath) {
        notes.push(
          ...(await hooks.afterEdit({ path: args.filePath, kind: tool === "edit" ? "Edit" : "Write", sessionID: input.sessionID })),
        )
      }
      notes.push(...hooks.searchNotes({ tool, command: tool === "bash" ? (args.command ?? "") : undefined }))
      if (tool === "bash" || tool === "grep") notes.push(...hooks.sizeNotes(output.output?.length ?? 0))
      if (notes.length) output.output = `${output.output ?? ""}\n\n${notes.join("\n\n")}`
    },

    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const id = event.properties.sessionID
      const text = await hooks.onStop(id)
      if (text) await client.session.prompt({ path: { id }, body: { parts: [{ type: "text", text }] } })
    },
  }
}

// ---- OpenCode 2.x (Desktop) ------------------------------------------------
const EDIT_KIND = { edit: "Edit", patch: "Edit", write: "Write" }

export default {
  id: "claude-hooks",
  // 1.x: com export default, a CLI exige `server` (o plugin no formato antigo).
  server: ClaudeHooks,
  setup: async (ctx) => {
    const loc = ctx.location ?? {}
    const hooks = await createHooks(loc.project?.directory ?? loc.directory)
    const abort = new AbortController()

    // UserPromptSubmit -> ponytail
    await ctx.session.hook("context", (p) => {
      p.system.push({ type: "text", text: PONYTAIL })
    })

    await ctx.tool.hook("execute.after", async (s) => {
      // `execute` (code mode) só agrega as ferramentas internas, que já passam por aqui.
      if (s.tool === "execute" || s.status !== "completed" || !s.result) return
      const input = s.input ?? {}
      const content = s.result.content ?? []
      const notes = []
      if (EDIT_KIND[s.tool] && typeof input.path === "string") {
        notes.push(...(await hooks.afterEdit({ path: input.path, kind: EDIT_KIND[s.tool], sessionID: s.sessionID })))
      }
      notes.push(...hooks.searchNotes({ tool: s.tool, command: s.tool === "shell" ? (input.command ?? "") : undefined }))
      if (s.tool === "shell" || s.tool === "grep") {
        const length = content.reduce((n, part) => n + (part.type === "text" ? part.text.length : 0), 0)
        notes.push(...hooks.sizeNotes(length))
      }
      if (notes.length) s.result.content = [...content, { type: "text", text: notes.join("\n\n") }]
    })

    // Stop: o fim de cada execução da sessão equivale ao session.idle da 1.x.
    ;(async () => {
      for await (const event of ctx.event.subscribe(undefined, { signal: abort.signal })) {
        if (event.type !== "session.execution.succeeded") continue
        const sessionID = event.data?.sessionID
        if (!sessionID) continue
        const text = await hooks.onStop(sessionID)
        if (text) await ctx.session.prompt({ sessionID, text })
      }
    })().catch(() => {})

    return () => abort.abort()
  },
}
