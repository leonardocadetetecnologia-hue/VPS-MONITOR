// Roteador por hash + ciclo de vida das telas.
//
// Cada tela exporta { titulo, intervaloMs?, render(container, ctx) } e pode
// devolver uma função de limpeza (ex.: destruir gráficos). Garantias daqui:
// - uma resposta atrasada de tela anterior nunca sobrescreve a atual (geração);
// - atualização automática não se sobrepõe a uma carga em andamento;
// - se a atualização falha, os últimos dados ficam na tela com um aviso.
import { el } from "./dom.js";
import auditoria from "./views/audit.js";
import diagnostico from "./views/diagnostics.js";
import historico from "./views/history.js";
import integracoes from "./views/integrations.js";
import visaoGeral from "./views/overview.js";
import processos from "./views/processes.js";
import servicos from "./views/services.js";
import linhaDoTempo from "./views/timeline.js";

const TELAS = {
  "visao-geral": visaoGeral,
  processos,
  servicos,
  historico,
  "linha-do-tempo": linhaDoTempo,
  diagnostico,
  integracoes,
  auditoria,
};

const container = document.getElementById("tela");
const titulo = document.getElementById("titulo-tela");
const atualizado = document.getElementById("atualizado-em");
const aviso = document.getElementById("aviso-atualizacao");
const botaoAtualizar = document.getElementById("atualizar");

const estado = { rota: null, geracao: 0, carregando: false, limpeza: null, timer: null, ultimoSucesso: null };
const ctx = { recarregar: () => desenhar() };

function rotaAtual() {
  const r = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  return Object.hasOwn(TELAS, r) ? r : "visao-geral";
}

function limpar() {
  if (estado.limpeza) estado.limpeza();
  estado.limpeza = null;
}

// A tela é redesenhada inteira (inclusive pela atualização automática). Para não
// tirar o foco de quem está digitando ou navegando por teclado, o elemento focado
// (identificado pelo `id`) volta a receber foco e cursor na versão nova.
function capturarFoco() {
  const ativo = document.activeElement;
  if (!ativo?.id || !container.contains(ativo)) return null;
  const temCursor = typeof ativo.selectionStart === "number";
  return { id: ativo.id, cursor: temCursor ? [ativo.selectionStart, ativo.selectionEnd] : null };
}

function restaurarFoco(foco) {
  if (!foco) return;
  const alvo = document.getElementById(foco.id);
  if (!alvo) return;
  alvo.focus({ preventScroll: true });
  if (foco.cursor && typeof alvo.setSelectionRange === "function") alvo.setSelectionRange(...foco.cursor);
}

function cartaoErro(erro) {
  return el("div", { class: "erro", role: "alert" },
    el("strong", { text: "Não foi possível carregar esta tela." }),
    el("p", { text: erro.message || "Falha inesperada." }),
    erro.requestId ? el("p", { class: "cartao-sub", text: `Código para suporte: ${erro.requestId}` }) : null,
    el("button", { type: "button", class: "botao", text: "Tentar novamente", onclick: () => desenhar() }));
}

async function desenhar({ automatico = false } = {}) {
  if (automatico && estado.carregando) return;
  const geracao = ++estado.geracao;
  const tela = TELAS[estado.rota];
  estado.carregando = true;
  botaoAtualizar.disabled = true;
  container.setAttribute("aria-busy", "true");

  try {
    const nova = el("div");
    const limpeza = await tela.render(nova, ctx);
    if (geracao !== estado.geracao) {
      // Outra carga começou depois desta (troca de tela ou novo clique): descarta.
      if (typeof limpeza === "function") limpeza();
      return;
    }
    const foco = capturarFoco();
    limpar();
    container.replaceChildren(...nova.childNodes);
    restaurarFoco(foco);
    estado.limpeza = typeof limpeza === "function" ? limpeza : null;
    estado.ultimoSucesso = new Date();
    aviso.hidden = true;
    atualizado.textContent = `Atualizado às ${estado.ultimoSucesso.toLocaleTimeString("pt-BR")}`;
  } catch (erro) {
    if (geracao !== estado.geracao) return;
    console.error(erro);
    if (estado.ultimoSucesso) {
      aviso.textContent = `Falha ao atualizar: ${erro.message} Exibindo os dados de ${estado.ultimoSucesso.toLocaleTimeString("pt-BR")}.`;
      aviso.hidden = false;
    } else {
      limpar();
      container.replaceChildren(cartaoErro(erro));
    }
  } finally {
    if (geracao === estado.geracao) {
      estado.carregando = false;
      botaoAtualizar.disabled = false;
      container.removeAttribute("aria-busy");
    }
  }
}

function navegar() {
  const rota = rotaAtual();
  const tela = TELAS[rota];
  clearInterval(estado.timer);
  limpar();
  estado.rota = rota;
  estado.ultimoSucesso = null;
  aviso.hidden = true;
  titulo.textContent = tela.titulo;
  document.title = `${tela.titulo} · VPS Insight`;
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.rota === rota) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  container.replaceChildren(el("p", { class: "carregando", role: "status", text: "Carregando…" }));
  desenhar();
  if (tela.intervaloMs) {
    estado.timer = setInterval(() => document.hidden || desenhar({ automatico: true }), tela.intervaloMs);
  }
}

// Tema: segue o sistema; o botão grava a preferência (se o navegador permitir).
function aplicarTema(tema) {
  if (tema === "light" || tema === "dark") document.documentElement.dataset.theme = tema;
  else delete document.documentElement.dataset.theme;
}
try {
  aplicarTema(localStorage.getItem("vps-insight-tema"));
} catch {
  // sem storage (janela privada, bloqueio): segue o tema do sistema
}
document.getElementById("alternar-tema").addEventListener("click", () => {
  const escuroAgora = getComputedStyle(document.documentElement).colorScheme === "dark";
  const novo = escuroAgora ? "light" : "dark";
  aplicarTema(novo);
  try {
    localStorage.setItem("vps-insight-tema", novo);
  } catch {
    // preferência só vale nesta visita
  }
  desenhar(); // gráficos releem as cores do tema
});

botaoAtualizar.addEventListener("click", () => desenhar());
window.addEventListener("hashchange", navegar);
navegar();
