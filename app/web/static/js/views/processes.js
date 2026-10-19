// Processos: onde está o consumo agora (por grupo), lista com busca e, ao escolher um
// grupo, a análise dele no tempo. O grupo analisado fica na URL
// (#/processos?grupo=...&horas=6), então dá para atualizar a página ou compartilhar o link.
import { ErroApi, obter } from "../api.js";
import { graficoLinha, marcasPorMomento } from "../charts.js";
import { bytes, cartao, dataHora, el, hora, num, pct, selo, seletor, seloNeutro, tabela, vazio } from "../dom.js";

const filtros = { ordenar_por: "cpu", limite: 15, busca: "", categoria: "" };
const CATEGORIAS = [["web", "Web"], ["aplicacao", "Aplicação"], ["banco", "Banco"], ["container", "Container"], ["sistema", "Sistema"]];
const PERIODOS = [1, 6, 24];
const PERIODO_PADRAO = 6;
const COR_SINAL = { REINICIO: "--status-alto", PICO_MEMORIA: "--status-critico" };
let esperaBusca = null;

function parametrosDaUrl() {
  const p = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const horas = Number(p.get("horas"));
  return { grupo: p.get("grupo"), horas: PERIODOS.includes(horas) ? horas : PERIODO_PADRAO };
}

function abrirAnalise(grupo, horas = PERIODO_PADRAO) {
  window.scrollTo({ top: 0 });
  window.location.hash = `#/processos?${new URLSearchParams({ grupo, horas: String(horas) })}`;
}

function botaoAnalisar(grupo, selecionado) {
  return el("button", {
    type: "button",
    class: "botao-fantasma botao-pequeno",
    text: selecionado ? "Em análise" : "Analisar",
    disabled: selecionado,
    "aria-label": `Analisar ${grupo}`,
    onclick: () => abrirAnalise(grupo),
  });
}

function barra(valor, texto, tipo) {
  return el("div", { class: "celula-barra" },
    el("span", { text: texto }),
    el("span", { class: `barra barra-${tipo}`, role: "presentation" }, el("span", { style: `width:${Math.min(100, valor)}%` })));
}

function estatistica(rotulo, valor, detalhe) {
  return el("section", { class: "cartao kpi" },
    el("div", { class: "kpi-rotulo" }, el("span", { text: rotulo })),
    el("div", { class: "kpi-valor", text: valor }),
    el("div", { class: "kpi-detalhe", text: detalhe }));
}

// --- Análise do grupo ------------------------------------------------------

async function buscarAnalise(grupo, horas) {
  try {
    return { dados: (await obter("/processes/analysis", { grupo, horas })).dados };
  } catch (erro) {
    if (erro instanceof ErroApi && erro.status === 404) return { naoEncontrado: erro.message };
    throw erro;
  }
}

function montarAnalise(grupo, horas, resultado) {
  const fechar = el("button", {
    type: "button", class: "botao-fantasma", text: "Fechar análise",
    onclick: () => { window.location.hash = "#/processos"; },
  });

  if (resultado.naoEncontrado) {
    return { no: cartao(`Análise: ${grupo}`, "", vazio(resultado.naoEncontrado), fechar), graficos: () => null };
  }

  const a = resultado.dados;
  const periodo = el("div", { class: "segmentado", role: "group", "aria-label": "Período da análise" },
    PERIODOS.map((h) => el("button", {
      type: "button", "aria-pressed": String(h === horas), text: `${h} h`, onclick: () => abrirAnalise(grupo, h),
    })));

  const sinais = a.sinais.length
    ? el("ul", { class: "lista" }, a.sinais.map((s) => el("li", {},
        el("div", { class: "lista-meta" }, selo(s.severidade), el("span", { text: dataHora(s.momento) })),
        el("strong", { text: s.titulo }),
        el("div", { class: "timeline-desc", text: s.descricao }))))
    : vazio("Nenhum sinal fora do comum no período: sem reinício, crescimento contínuo de memória ou CPU sustentada.");

  const cMem = el("canvas", { role: "img", "aria-label": `Memória residente de ${grupo} ao longo do tempo` });
  const cCpu = el("canvas", { role: "img", "aria-label": `Uso de CPU de ${grupo} ao longo do tempo` });

  const instancias = tabela([
    { titulo: "PID", num: true, valor: (i) => i.pid },
    { titulo: "Processo", valor: (i) => i.nome },
    { titulo: "Iniciado", num: true, valor: (i) => dataHora(i.iniciado_em) },
    { titulo: "Última leitura", num: true, valor: (i) => dataHora(i.ultima_amostra) },
    { titulo: "Leituras", num: true, valor: (i) => i.amostras },
    { titulo: "Situação", valor: (i) => (i.encerrado ? selo("aviso", "encerrado") : selo("normal", "ativo")) },
    { titulo: "RSS", num: true, valor: (i) => bytes(i.rss_atual_bytes) },
    {
      titulo: "Tendência da RSS", num: true,
      valor: (i) => (i.tendencia_rss_mib_h == null
        ? "—"
        : `${i.tendencia_rss_mib_h > 0 ? "+" : ""}${num(i.tendencia_rss_mib_h)} MiB/h · R² ${pct(i.tendencia_r2 * 100)}`),
    },
  ], a.instancias);

  const no = el("section", { class: "cartao analise", "aria-label": `Análise de ${grupo}` },
    el("div", { class: "cartao-cabecalho" },
      el("div", {}, el("h2", { text: `Análise: ${grupo}` }),
        el("span", { class: "cartao-sub", text: `${a.instancias.length} instância(s) · leituras das últimas ${horas} h` })),
      el("div", { class: "filtros sem-margem" }, periodo, fechar)),
    el("div", { class: "grade-kpi" },
      estatistica("CPU do grupo", pct(a.cpu.atual), `média ${pct(a.cpu.media)} · pico ${pct(a.cpu.maximo)} às ${hora(a.cpu.momento_maximo)}`),
      estatistica("Memória do grupo (% da RAM)", pct(a.memoria.atual), `média ${pct(a.memoria.media)} · pico ${pct(a.memoria.maximo)} às ${hora(a.memoria.momento_maximo)}`),
      estatistica("Memória residente (RSS)", bytes(a.rss.atual), `pico ${bytes(a.rss.maximo)} às ${hora(a.rss.momento_maximo)}`)),
    el("h3", { class: "subtitulo", text: `Sinais medidos (${a.sinais.length})` }),
    sinais,
    el("div", { class: "grade-2" },
      el("div", {}, el("h3", { class: "subtitulo", text: "Memória residente (RSS)" }), el("div", { class: "grafico" }, cMem)),
      el("div", {}, el("h3", { class: "subtitulo", text: "CPU (%)" }), el("div", { class: "grafico" }, cCpu))),
    el("p", { class: "legenda-nota", text: "Marcas verticais: reinício (laranja) e pico de memória (vermelho). Picos são preservados mesmo nos períodos longos." }),
    el("h3", { class: "subtitulo", text: "Instâncias no período" }),
    instancias);

  // Gráficos só são criados depois que toda a tela carregou (evita gráfico órfão se algo falhar).
  const graficos = () => {
    const rotulos = a.serie.map((p) => hora(p.momento));
    const rotulosTooltip = a.serie.map((p) => dataHora(p.momento));
    const marcas = marcasPorMomento(a.serie, a.sinais, (s) => COR_SINAL[s.codigo] ?? null);
    const comum = { rotulos, rotulosTooltip, marcas, legenda: false };
    const g1 = graficoLinha(cMem, { ...comum, formatoY: (v) => bytes(v),
      series: [{ rotulo: "RSS", cor: "--serie-2", dados: a.serie.map((p) => p.memoria_rss_bytes) }] });
    const g2 = graficoLinha(cCpu, { ...comum, formatoY: (v) => pct(v),
      series: [{ rotulo: "CPU", cor: "--serie-1", dados: a.serie.map((p) => p.cpu_percentual) }] });
    return () => { g1.destroy(); g2.destroy(); };
  };
  return { no, graficos };
}

// --- Tela --------------------------------------------------------------------

export default {
  titulo: "Processos",
  intervaloMs: 15000,
  async render(raiz, ctx) {
    const { grupo, horas } = parametrosDaUrl();
    const [lista, resumo, analise] = await Promise.all([
      obter("/processes", filtros),
      obter("/processes/summary"),
      grupo ? buscarAnalise(grupo, horas) : null,
    ]);

    const secaoAnalise = analise ? montarAnalise(grupo, horas, analise) : null;
    if (secaoAnalise) raiz.append(secaoAnalise.no);

    // Onde está o consumo agora, por grupo.
    const r = resumo.dados;
    const chave = filtros.ordenar_por === "memoria" ? "memoria_percentual" : "cpu_percentual";
    const grupos = [...r.grupos].sort((x, y) => y[chave] - x[chave]);
    raiz.append(cartao("Consumo por grupo agora", "grupo = unidade systemd, ou o nome do processo",
      el("div", { class: "chips" },
        el("div", { class: "chip" }, el("strong", { text: String(r.total_processos) }), el("span", { text: `processos em ${r.total_grupos} grupos` })),
        el("div", { class: "chip" }, el("strong", { text: pct(r.concentracao_top3_cpu) }), el("span", { text: "da CPU nos 3 maiores grupos" })),
        el("div", { class: "chip" }, el("strong", { text: pct(r.concentracao_top3_memoria) }), el("span", { text: "da memória nos 3 maiores grupos" }))),
      tabela([
        { titulo: "Grupo", valor: (g) => el("div", {}, el("strong", { text: g.grupo }), " ", seloNeutro(g.categoria)) },
        { titulo: "Proc.", num: true, valor: (g) => g.processos },
        { titulo: "CPU · participação", valor: (g) => barra(g.participacao_cpu, `${pct(g.cpu_percentual)} · ${pct(g.participacao_cpu)} do total`, "cpu") },
        { titulo: "RAM · participação", valor: (g) => barra(g.participacao_memoria, `${pct(g.memoria_percentual)} · ${pct(g.participacao_memoria)} do total`, "ram") },
        { titulo: "RSS", num: true, valor: (g) => bytes(g.memoria_rss_bytes) },
        { titulo: "", valor: (g) => botaoAnalisar(g.grupo, g.grupo === grupo) },
      ], grupos, { classeLinha: (g) => (g.grupo === grupo ? "linha-selecionada" : null) })));

    // Lista de processos com busca e filtros.
    const busca = el("input", {
      id: "busca-processos", type: "search", class: "campo-busca", maxlength: 100, autocomplete: "off",
      placeholder: "nome, comando, usuário, unidade ou PID", "aria-label": "Buscar processo",
      oninput: (e) => {
        filtros.busca = e.target.value;
        clearTimeout(esperaBusca);
        esperaBusca = setTimeout(() => ctx.recarregar(), 350); // debounce: uma consulta por pausa na digitação
      },
    });
    busca.value = filtros.busca;

    raiz.append(cartao("Processos com maior consumo", `${lista.dados.length} processos · atualiza a cada 15 s`,
      el("div", { class: "filtros" },
        el("label", {}, "Buscar", busca),
        seletor({ id: "filtro-categoria", rotulo: "Tipo", valor: filtros.categoria, opcoes: CATEGORIAS,
          aoMudar: (v) => { filtros.categoria = v; ctx.recarregar(); } }),
        seletor({ id: "filtro-ordem", rotulo: "Ordenar por", valor: filtros.ordenar_por, todos: null,
          opcoes: [["cpu", "CPU"], ["memoria", "Memória"]],
          aoMudar: (v) => { filtros.ordenar_por = v; ctx.recarregar(); } }),
        seletor({ id: "filtro-limite", rotulo: "Mostrar", valor: filtros.limite, todos: null, opcoes: ["10", "15", "30", "100"],
          aoMudar: (v) => { filtros.limite = Number(v); ctx.recarregar(); } })),
      tabela([
        { titulo: "PID", num: true, valor: (p) => p.pid },
        { titulo: "Processo", valor: (p) => el("strong", { text: p.nome }) },
        { titulo: "Usuário", valor: (p) => p.usuario },
        { titulo: "CPU", num: true, valor: (p) => pct(p.cpu_percentual) },
        { titulo: "RAM", num: true, valor: (p) => pct(p.memoria_percentual) },
        { titulo: "RSS", num: true, valor: (p) => bytes(p.memoria_rss_bytes) },
        { titulo: "Estado", valor: (p) => p.estado },
        { titulo: "Tipo", valor: (p) => seloNeutro(p.categoria) },
        { titulo: "Grupo", valor: (p) => p.grupo },
        { titulo: "Iniciado", num: true, valor: (p) => dataHora(p.iniciado_em) },
        { titulo: "Comando", classe: "cmd", valor: (p) => p.comando },
        { titulo: "", valor: (p) => botaoAnalisar(p.grupo, p.grupo === grupo) },
      ], lista.dados, {
        classeLinha: (p) => (p.grupo === grupo ? "linha-selecionada" : null),
        vazio: filtros.busca || filtros.categoria ? "Nenhum processo corresponde à busca e aos filtros." : "Nenhum processo retornado pelo coletor.",
      })));

    return secaoAnalise ? secaoAnalise.graficos() : null;
  },
};
