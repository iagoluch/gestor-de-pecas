// Hooks do projeto no OpenCode — espelho de .claude/settings.json e
// .claude/settings.local.json do Claude Code. Não bloqueia nada: os resultados
// dos hooks são anexados à saída da ferramenta para o modelo agir sobre eles.
import { execFile, spawn } from "node:child_process"
import { existsSync, mkdirSync, openSync } from "node:fs"
import { connect } from "node:net"
import { homedir } from "node:os"
import { join, relative } from "node:path"

const BIG_OUTPUT = 12000
const SEARCH_CMD = /\b(grep|rg|find|findstr|Select-String)\b/

const PONYTAIL =
  "Lembrete automatico (hook): se o pedido envolver escrever/alterar/revisar codigo, carregue a " +
  'skill "ponytail" com a ferramenta `skill` — solucao mais simples e minima que funciona, YAGNI, ' +
  "sem over-engineering. Ignore se o pedido nao for sobre codigo."

const GRAPHIFY =
  "[hook graphify] graphify-out/graph.json existe: rode `graphify query \"<pergunta>\"` antes de " +
  "varrer arquivos com grep/glob. So use grep depois que o graphify te orientar, ou para " +
  "alterar/depurar linhas especificas."

const HEADROOM =
  "[hook headroom] Saida grande (>12k caracteres): comprima com a ferramenta " +
  "`headroom_headroom_compress` antes de continuar. Se o headroom classificar como router:noop, " +
  "siga normalmente."

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

export const ClaudeHooks = async ({ worktree, client }) => {
  const root = worktree
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
  const headroom = join(homedir(), ".local", "bin", process.platform === "win32" ? "headroom.exe" : "headroom")
  if (existsSync(headroom) && !(await portOpen(8787))) {
    const logDir = join(homedir(), ".headroom-run")
    mkdirSync(logDir, { recursive: true })
    detached(headroom, ["proxy"], root, join(logDir, "headroom_proxy.log"))
  }

  return {
    // UserPromptSubmit -> ponytail
    "experimental.chat.system.transform": async (_input, output) => {
      output.system.push(PONYTAIL)
    },

    "tool.execute.after": async (input, output) => {
      const notes = []
      const tool = input.tool
      const args = input.args ?? {}

      if ((tool === "edit" || tool === "write") && args.filePath) {
        const rel = relative(root, args.filePath).replace(/\\/g, "/")

        // PostToolUse Write|Edit -> type-check do frontend
        if (/^web\/.*\.tsx?$/.test(rel) && existsSync(tsc)) {
          const res = await run("node", [tsc, "-b", "tsconfig.json", "--pretty", "false"], { cwd: web })
          if (res.code !== 0) notes.push(`[hook type-check] Erros de type-check TypeScript (tsc -b) — corrija:\n${res.out}`)
        }

        // PostToolUse Edit|Write -> impeccable (design do frontend)
        const msg = await impeccableHook({
          hook_event_name: "PostToolUse",
          tool_name: tool === "edit" ? "Edit" : "Write",
          tool_input: { file_path: args.filePath },
          session_id: input.sessionID,
        })
        if (msg) notes.push(`[hook impeccable]\n${msg}`)
      }

      // PreToolUse Bash|Grep|Glob -> graphify primeiro
      const searching = tool === "grep" || tool === "glob" || (tool === "bash" && SEARCH_CMD.test(args.command ?? ""))
      if (searching && hasGraph()) notes.push(GRAPHIFY)

      // PostToolUse Bash|Grep -> headroom em saídas grandes
      if ((tool === "bash" || tool === "grep") && (output.output?.length ?? 0) > BIG_OUTPUT) notes.push(HEADROOM)

      if (notes.length) output.output = `${output.output ?? ""}\n\n${notes.join("\n\n")}`
    },

    // Stop -> impeccable (passe final); se pedir continuação, devolve o motivo à sessão.
    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const id = event.properties.sessionID
      const msg = await impeccableHook({
        hook_event_name: "Stop",
        session_id: id,
        stop_hook_active: stopActive.has(id),
      })
      if (!msg || stopActive.has(id)) return stopActive.delete(id)
      stopActive.add(id)
      await client.session.prompt({ path: { id }, body: { parts: [{ type: "text", text: `[hook impeccable]\n${msg}` }] } })
    },
  }
}
