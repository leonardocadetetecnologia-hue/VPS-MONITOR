// Utilitários de DOM e formatação. Todo texto entra via textContent (sem innerHTML com dados).

export function el(tag, attrs = {}, ...filhos) {
  const no = document.createElement(tag);
  for (const [chave, valor] of Object.entries(attrs)) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (chave === "class") no.className = valor;
    else if (chave === "text") no.textContent = valor;
    // Via CSSOM: a CSP (style-src 'self') bloquearia o atributo style inline.
    else if (chave === "style") no.style.cssText = valor;
    else if (chave.startsWith("on") && typeof valor === "function") no.addEventListener(chave.slice(2), valor);
    else if (chave === "dataset") Object.assign(no.dataset, valor);
    else no.setAttribute(chave, valor === true ? "" : String(valor));
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    no.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return no;
}

const ROTULO_NIVEL = { normal: "Normal", info: "Info", aviso: "Aviso", alto: "Alto", critico: "Crítico" };

export function selo(nivel, texto) {
  return el("span", { class: "selo", dataset: { nivel } }, texto ?? ROTULO_NIVEL[nivel] ?? nivel);
}

export function seloNeutro(texto) {
  return el("span", { class: "selo selo-neutro" }, texto);
}

export function cartao(titulo, sub, ...conteudo) {
  return el("section", { class: "cartao" },
    el("div", { class: "cartao-cabecalho" }, el("h2", { text: titulo }), sub ? el("span", { class: "cartao-sub", text: sub }) : null),
    ...conteudo);
}

export function linhasTabela(colunas, linhas, { classeLinha } = {}) {
  return linhas.map((linha) =>
    el("tr", { class: classeLinha ? classeLinha(linha) : null },
      colunas.map((c) => {
        const v = c.valor(linha);
        const classe = [c.num ? "num" : "", c.classe || ""].join(" ").trim() || null;
        return el("td", { class: classe }, v instanceof Node ? v : String(v ?? "—"));
      })));
}

// `vazio`: texto mostrado no lugar da tabela quando não há linhas (estado vazio explícito).
export function tabela(colunas, linhas, { classeLinha, vazio: textoVazio = "Nenhum registro." } = {}) {
  if (!linhas.length) return vazio(textoVazio);
  const cab = el("tr", {}, colunas.map((c) => el("th", { class: c.num ? "num" : null, scope: "col", text: c.titulo })));
  return el("div", { class: "tabela-rolagem" },
    el("table", {}, el("thead", {}, cab), el("tbody", {}, linhasTabela(colunas, linhas, { classeLinha }))));
}

// Filtro padrão das telas. `opcoes`: valores ou pares [valor, rótulo];
// `todos`: rótulo da opção vazia (null para não ter).
export function seletor({ id, rotulo, valor, opcoes, todos = "Todos", aoMudar }) {
  const s = el("select", { id, onchange: (e) => aoMudar(e.target.value) },
    todos ? el("option", { value: "", text: todos }) : null,
    opcoes.map((o) => {
      const [v, r] = Array.isArray(o) ? o : [o, o];
      return el("option", { value: v, text: r });
    }));
  s.value = String(valor ?? "");
  return el("label", {}, rotulo, s);
}

export function vazio(texto) {
  return el("p", { class: "vazio", text: texto });
}

// --- formatação ---------------------------------------------------------

const fmtNum = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const fmtHora = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const fmtDataHora = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const fmtDia = new Intl.DateTimeFormat("pt-BR", { weekday: "long", day: "2-digit", month: "long" });

export const pct = (v) => `${fmtNum.format(v)}%`;
export const num = (v) => fmtNum.format(v);
export const hora = (iso) => fmtHora.format(new Date(iso));
export const dataHora = (iso) => fmtDataHora.format(new Date(iso));
// Só a primeira letra em maiúscula ("Sexta-feira, 16 de outubro"); CSS capitalize
// produziria "16 De Outubro", errado em pt-BR.
export function dia(iso) {
  const texto = fmtDia.format(new Date(iso));
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export function bytes(v) {
  if (v === null || v === undefined) return "—";
  const unidades = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (v >= 1024 && i < unidades.length - 1) { v /= 1024; i++; }
  return `${fmtNum.format(v)} ${unidades[i]}`;
}

export const taxa = (v) => `${bytes(v)}/s`;

export function relativo(iso) {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "agora";
  const m = Math.round(s / 60);
  if (m < 60) return `há ${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `há ${h} h ${m % 60 ? `${m % 60} min` : ""}`.trim();
  return `há ${Math.floor(h / 24)} dias`;
}

export function cssVar(nome) {
  return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
}
