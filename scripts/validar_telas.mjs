// Validação de telas num Chrome headless (protocolo DevTools, sem dependências npm).
//
// Para cada largura × tela, verifica:
//   - sem rolagem horizontal da página (scrollWidth <= innerWidth);
//   - nenhum cartão passando da borda direita;
//   - nenhum cartão de erro na tela;
//   - console limpo: sem console.error, exceção não tratada ou violação de CSP.
//
// Uso: node scripts/validar_telas.mjs <chrome.exe> <url-base> <pasta-saida> [--capturas]
// Só acessa a URL local indicada (o dashboard em 127.0.0.1).
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [chrome, base, saida, ...flags] = process.argv.slice(2);
if (!chrome || !base || !saida) {
  console.error("uso: node validar_telas.mjs <chrome> <url-base> <pasta-saida> [--capturas]");
  process.exit(2);
}
const capturas = flags.includes("--capturas");
const LARGURAS = [320, 375, 768, 1024, 1366, 1920];
const ROTAS = [
  "visao-geral", "processos", "processos?grupo=app-web-next.service&horas=6", "servicos", "historico",
  "linha-do-tempo", "diagnostico", "integracoes", "auditoria",
];
const PORTA_DEPURACAO = 9334;

mkdirSync(saida, { recursive: true });
const navegador = spawn(chrome, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORTA_DEPURACAO}`, `--user-data-dir=${join(saida, "perfil")}`, "about:blank",
], { stdio: "ignore" });

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

async function conectar() {
  for (let i = 0; i < 60; i++) {
    await esperar(250);
    try {
      const alvos = await (await fetch(`http://127.0.0.1:${PORTA_DEPURACAO}/json`)).json();
      const pagina = alvos.find((t) => t.type === "page");
      if (pagina) return pagina.webSocketDebuggerUrl;
    } catch {
      // Chrome ainda subindo
    }
  }
  throw new Error("Chrome não respondeu ao protocolo de depuração");
}

let ws;
let falhas = 0;
try {
  ws = new WebSocket(await conectar());
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let seq = 0;
  const pendentes = new Map();
  const problemasConsole = [];
  ws.addEventListener("message", (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pendentes.has(d.id)) {
      pendentes.get(d.id)(d);
      pendentes.delete(d.id);
    } else if (d.method === "Runtime.exceptionThrown") {
      problemasConsole.push(`exceção: ${d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text}`);
    } else if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") {
      problemasConsole.push(`console.error: ${d.params.args.map((a) => a.value ?? a.description).join(" ")}`);
    } else if (d.method === "Log.entryAdded" && ["error", "warning"].includes(d.params.entry.level)) {
      problemasConsole.push(`${d.params.entry.source}: ${d.params.entry.text}`);
    }
  });
  const cdp = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pendentes.set(id, (d) => (d.error ? reject(new Error(`${method}: ${d.error.message}`)) : resolve(d.result)));
    ws.send(JSON.stringify({ id, method, params }));
  });
  const avaliar = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;

  await cdp("Runtime.enable");
  await cdp("Log.enable");
  await cdp("Page.enable");

  for (const largura of LARGURAS) {
    await cdp("Emulation.setDeviceMetricsOverride", {
      width: largura, height: 900, deviceScaleFactor: 1, mobile: largura < 768,
    });
    // Carga completa por largura: começa de página limpa.
    await cdp("Page.navigate", { url: `${base}/#/visao-geral` });
    await esperar(1500);

    for (const rota of ROTAS) {
      problemasConsole.length = 0;
      await cdp("Page.navigate", { url: `${base}/#/${rota}` });
      let pronto = false;
      for (let i = 0; i < 40 && !pronto; i++) {
        await esperar(150);
        pronto = await avaliar(`(() => { const t = document.getElementById("tela");
          return !!t && !t.hasAttribute("aria-busy") && !t.querySelector(".carregando"); })()`);
      }
      await esperar(300); // gráficos terminam de dimensionar
      const r = await avaliar(`(() => {
        const vw = window.innerWidth;
        const cartoesFora = [...document.querySelectorAll(".cartao")]
          .filter((c) => c.getBoundingClientRect().right > vw + 1).length;
        return { sw: document.documentElement.scrollWidth, vw, cartoesFora,
                 erroNaTela: !!document.querySelector("#tela .erro") };
      })()`);
      const problemas = [];
      if (!pronto) problemas.push("tela não terminou de carregar em 6 s");
      if (r.sw > r.vw) problemas.push(`rolagem horizontal (${r.sw}px > ${r.vw}px)`);
      if (r.cartoesFora) problemas.push(`${r.cartoesFora} cartão(ões) além da borda`);
      if (r.erroNaTela) problemas.push("cartão de erro exibido");
      problemas.push(...problemasConsole);
      if (capturas) {
        const shot = await cdp("Page.captureScreenshot", { format: "png" });
        writeFileSync(join(saida, `${largura}-${rota.replace(/[^a-z0-9-]+/gi, "_")}.png`), Buffer.from(shot.data, "base64"));
      }
      const marca = problemas.length ? "FALHA" : "ok   ";
      console.log(`${marca} ${String(largura).padStart(4)}px  ${rota.padEnd(15)} ${problemas.join("; ")}`);
      if (problemas.length) falhas++;
    }
  }
} catch (erro) {
  console.error(`Erro na validação: ${erro.message}`);
  falhas++;
} finally {
  ws?.close();
  navegador.kill();
}
console.log(falhas ? `\n${falhas} verificação(ões) com problema.` : `\nTodas as ${LARGURAS.length * ROTAS.length} verificações passaram.`);
process.exit(falhas ? 1 : 0);
