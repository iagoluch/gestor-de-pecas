import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

function argsFrom(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) result[argv[index].replace(/^--/, "")] = argv[index + 1];
  return result;
}

const args = argsFrom(process.argv.slice(2));
const username = process.env.CAPTURE_USERNAME;
const password = process.env.CAPTURE_PASSWORD;
const output = path.resolve(args.output || "web-preview.png");
const width = Number(args.width || 1920);
const height = Number(args.height || 1080);
const route = args.route || "/operador";
// Telas que exigem navegação em etapas (escolher o recurso e só então abrir um
// diálogo) aceitam vários rótulos separados por ">", aplicados em ordem.
const clickSteps = String(args.click || "").split(">").map((item) => item.trim()).filter(Boolean);
const baseUrl = String(args["base-url"] || "http://127.0.0.1:5173").replace(/\/$/, "");
const chromePath = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

if (!username || !password) throw new Error("CAPTURE_USERNAME e CAPTURE_PASSWORD são obrigatórias.");
if (!Number.isInteger(width) || !Number.isInteger(height) || width < 640 || height < 480) throw new Error("Viewport inválido.");

const tempRoot = path.resolve(os.tmpdir());
const profile = await mkdtemp(path.join(tempRoot, "gestor-web-capture-"));
if (!path.resolve(profile).startsWith(`${tempRoot}${path.sep}`)) throw new Error("Diretório temporário fora da área autorizada.");

const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--hide-scrollbars",
  "--remote-debugging-port=0",
  `--user-data-dir=${profile}`,
  `--window-size=${width},${height}`,
  "--force-device-scale-factor=1",
  "--no-first-run",
  "--no-default-browser-check",
  `${baseUrl}/`,
], { stdio: "ignore", windowsHide: true });

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function devToolsPort() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const content = await readFile(path.join(profile, "DevToolsActivePort"), "utf8");
      const port = Number(content.split(/\r?\n/, 1)[0]);
      if (port) return port;
    } catch {}
    await wait(100);
  }
  throw new Error("Chromium não abriu a porta de depuração.");
}

let socket;
try {
  const port = await devToolsPort();
  let target;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const targets = await fetch(`http://127.0.0.1:${port}/json/list`).then((response) => response.json());
    target = targets.find((item) => item.type === "page");
    if (target) break;
    await wait(100);
  }
  if (!target) throw new Error("A página do Chromium não foi encontrada.");

  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.reject(new Error(message.error.message));
    else entry.resolve(message.result);
  });
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });

  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  let baseLoaded = false;
  for (let attempt = 0; attempt < 50; attempt += 1) {
    const locationResult = await cdp("Runtime.evaluate", {
      expression: "location.href",
      returnByValue: true,
    });
    if (String(locationResult.result?.value || "").startsWith(baseUrl)) {
      baseLoaded = true;
      break;
    }
    await wait(100);
  }
  if (!baseLoaded) throw new Error("A origem Web não carregou antes do login de captura.");
  const loginResult = await cdp("Runtime.evaluate", {
    expression: `(async () => {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(${JSON.stringify({ username, password })})
      });
      if (!response.ok) throw new Error('Falha no login de captura');
      location.href = ${JSON.stringify(route)};
      return true;
    })()`,
    awaitPromise: true,
    returnByValue: true,
  });
  if (loginResult.exceptionDetails) throw new Error(loginResult.exceptionDetails.text || "Falha no login de captura");

  let ready = false;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    await wait(250);
    const state = await cdp("Runtime.evaluate", {
      expression: `(() => ({
        path: location.pathname,
        login: location.pathname === '/login' || Boolean(document.querySelector('.login-card')),
        loading: /Carregando dados|Preparando o posto|Carregando fila/.test(document.body?.innerText || '')
      }))()`,
      returnByValue: true,
    });
    const value = state.result?.value || {};
    if (value.login) throw new Error("A sessão de captura voltou para o login.");
    if (value.path === new URL(`${baseUrl}${route}`).pathname && !value.loading) {
      ready = true;
      break;
    }
  }
  if (!ready) throw new Error("A página não concluiu o carregamento no tempo da captura.");
  await wait(500);

  for (const clickText of clickSteps) {
    const clicked = await cdp("Runtime.evaluate", {
      expression: `(() => {
        const label = ${JSON.stringify(clickText)};
        const buttons = [...document.querySelectorAll('button')];
        // Cards do operador carregam texto auxiliar; o rótulo exato vence e a
        // correspondência parcial só é usada quando ele não existe.
        const target = buttons.find((button) => button.textContent.trim() === label)
          ?? buttons.find((button) => button.textContent.includes(label));
        if (!target) throw new Error('Botão de captura não encontrado: ' + ${JSON.stringify(clickText)});
        target.click();
      })()`,
      returnByValue: true,
    });
    if (clicked.exceptionDetails) throw new Error(clicked.exceptionDetails.exception?.description || clicked.exceptionDetails.text);
    await wait(900);
  }

  const shot = await cdp("Page.captureScreenshot", { format: "png", fromSurface: true, captureBeyondViewport: false });
  await mkdir(path.dirname(output), { recursive: true });
  await writeFile(output, Buffer.from(shot.data, "base64"));
  process.stdout.write(`${output}|${width}x${height}\n`);
  await cdp("Browser.close");
} finally {
  if (socket?.readyState === WebSocket.OPEN) socket.close();
  if (!chrome.killed) chrome.kill();
  if (chrome.exitCode === null) {
    await Promise.race([
      new Promise((resolve) => chrome.once("exit", resolve)),
      wait(3_000),
    ]);
  }
  await rm(profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
}
