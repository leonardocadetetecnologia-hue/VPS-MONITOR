import { obter } from "../api.js";
import { graficoLinha } from "../charts.js";
import { bytes, cartao, el, hora, num, pct, relativo, selo, taxa, vazio } from "../dom.js";

function kpi(rotulo, valor, nivel, detalhe, percentual) {
  return el("section", { class: "cartao kpi" },
    el("div", { class: "kpi-rotulo" }, el("span", { text: rotulo }), nivel ? selo(nivel) : null),
    el("div", { class: "kpi-valor", text: valor }),
    percentual !== undefined
      ? el("div", { class: "medidor", dataset: { nivel: nivel || "" }, role: "presentation" },
          el("span", { style: `width:${Math.min(100, percentual)}%` }))
      : null,
    el("div", { class: "kpi-detalhe", text: detalhe }));
}

export default {
  titulo: "Visão geral",
  intervaloMs: 15000,
  async render(raiz) {
    const [atual, hist, procs, servs, evs] = await Promise.all([
      obter("/metrics/current"),
      obter("/metrics/history", { horas: 1, max_pontos: 120 }),
      obter("/processes", { limite: 5 }),
      obter("/services"),
      obter("/events", { horas: 24, limite: 6 }),
    ]);
    const { snapshot: s, niveis } = atual.dados;
    // Mesma regra do backend (SnapshotMetricas.disco_principal): raiz, senão o primeiro.
    const raizDisco = s.discos.find((d) => d.ponto_montagem === "/") ?? s.discos[0];
    const eth = s.rede[0];

    raiz.append(el("div", { class: "grade-kpi" },
      kpi("CPU", pct(s.cpu.uso_percentual), niveis.cpu,
        `load ${num(s.cpu.load_1)} · ${num(s.cpu.load_5)} · ${num(s.cpu.load_15)} (${s.cpu.nucleos} núcleos)`, s.cpu.uso_percentual),
      kpi("Memória", pct(s.memoria.uso_percentual), niveis.memoria,
        `${bytes(s.memoria.usado_bytes)} de ${bytes(s.memoria.total_bytes)}`, s.memoria.uso_percentual),
      kpi("Swap", pct(s.memoria.swap_percentual), niveis.swap,
        `${bytes(s.memoria.swap_usado_bytes)} de ${bytes(s.memoria.swap_total_bytes)}`, s.memoria.swap_percentual),
      kpi("Disco /", pct(raizDisco.uso_percentual), niveis.disco,
        `${bytes(raizDisco.usado_bytes)} de ${bytes(raizDisco.total_bytes)}`, raizDisco.uso_percentual),
      kpi("Rede eth0", taxa(eth.rx_bytes_s + eth.tx_bytes_s), null,
        `↓ ${taxa(eth.rx_bytes_s)} · ↑ ${taxa(eth.tx_bytes_s)} · ${eth.conexoes_estabelecidas} conexões`),
    ));

    const canvas = el("canvas", { role: "img", "aria-label": "Uso de CPU, memória e swap na última hora" });
    raiz.append(cartao("Última hora", "CPU, memória e swap (%)", el("div", { class: "grafico" }, canvas)));

    const falhas = servs.dados.servicos.filter((x) => x.estado_ativo === "failed");
    const listaFalhas = falhas.length
      ? el("ul", { class: "lista" }, falhas.map((f) => el("li", {},
          el("div", {}, el("strong", { text: f.unidade })),
          el("div", { class: "lista-meta" }, selo("critico", "failed"),
            el("span", { text: `criticidade: ${f.criticidade}` }), el("span", { text: `desde ${relativo(f.desde)}` })))))
      : vazio("Nenhuma unidade em falha.");

    const listaEventos = evs.dados.length
      ? el("ul", { class: "lista" }, evs.dados.map((e) => el("li", {},
          el("div", { text: e.titulo }),
          el("div", { class: "lista-meta" }, selo(e.severidade), el("span", { text: `${hora(e.momento)} · ${relativo(e.momento)}` })))))
      : vazio("Sem eventos nas últimas 24 h.");

    const listaProcs = el("ul", { class: "lista" }, procs.dados.map((p) => el("li", {},
      el("div", {},
        el("a", { href: `#/processos?${new URLSearchParams({ grupo: p.grupo, horas: "6" })}`, text: p.nome, title: `Analisar ${p.grupo}` }),
        ` · pid ${p.pid}`),
      el("div", { class: "lista-meta" },
        el("span", { text: `CPU ${pct(p.cpu_percentual)}` }), el("span", { text: `RAM ${pct(p.memoria_percentual)}` }),
        p.unidade_systemd ? el("span", { text: p.unidade_systemd }) : null))));

    raiz.append(el("div", { class: "grade-2" },
      cartao("Unidades em falha", `${falhas.length} de ${servs.dados.total}`, listaFalhas),
      cartao("Eventos recentes", "últimas 24 h", listaEventos),
      cartao("Maiores consumidores de CPU", "agora", listaProcs),
    ));

    const pontos = hist.dados;
    const grafico = graficoLinha(canvas, {
      rotulos: pontos.map((p) => hora(p.momento)),
      formatoY: (v) => pct(v),
      maxY: 100,
      series: [
        { rotulo: "CPU", cor: "--serie-1", dados: pontos.map((p) => p.cpu_percentual) },
        { rotulo: "Memória", cor: "--serie-2", dados: pontos.map((p) => p.memoria_percentual) },
        { rotulo: "Swap", cor: "--serie-3", dados: pontos.map((p) => p.swap_percentual) },
      ],
    });
    return () => grafico.destroy();
  },
};
