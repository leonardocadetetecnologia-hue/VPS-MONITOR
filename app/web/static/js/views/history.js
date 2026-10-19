import { obter } from "../api.js";
import { graficoLinha, marcasPorMomento } from "../charts.js";
import { cartao, dataHora, el, hora, pct, tabela, taxa } from "../dom.js";

const estado = { horas: 6, tabela: false };
const COR_SEVERIDADE = { critico: "--status-critico", alto: "--status-alto" };

// Eventos alto/crítico que não são de métrica (os de métrica já estão visíveis na própria curva).
const corDoEvento = (e) => (e.tipo === "metrica" ? null : COR_SEVERIDADE[e.severidade] ?? null);

export default {
  titulo: "Histórico",
  intervaloMs: 60000,
  async render(raiz, ctx) {
    const [hist, evs] = await Promise.all([
      obter("/metrics/history", { horas: estado.horas, max_pontos: 360 }),
      obter("/events", { horas: estado.horas, limite: 500 }),
    ]);
    const pontos = hist.dados;
    const marcas = marcasPorMomento(pontos, evs.dados, corDoEvento);
    const rotulos = pontos.map((p) => (estado.horas > 24 ? dataHora(p.momento) : hora(p.momento)));
    const rotulosTooltip = pontos.map((p) => dataHora(p.momento));

    const faixa = el("div", { class: "segmentado", role: "group", "aria-label": "Período" },
      [1, 6, 24].map((h) => el("button", {
        type: "button", "aria-pressed": String(estado.horas === h), text: `${h} h`,
        onclick: () => { estado.horas = h; ctx.recarregar(); },
      })));
    const alternar = el("button", {
      type: "button", class: "botao-fantasma", text: estado.tabela ? "Ver gráficos" : "Ver como tabela",
      onclick: () => { estado.tabela = !estado.tabela; ctx.recarregar(); },
    });
    raiz.append(el("div", { class: "filtros" }, faixa, alternar,
      el("span", { class: "cartao-sub", text: `${pontos.length} pontos · picos de CPU/RAM/swap preservados na redução` })));

    if (estado.tabela) {
      raiz.append(cartao("Histórico em tabela", "mais recente primeiro", tabela([
        { titulo: "Momento", valor: (p) => dataHora(p.momento) },
        { titulo: "CPU", num: true, valor: (p) => pct(p.cpu_percentual) },
        { titulo: "Memória", num: true, valor: (p) => pct(p.memoria_percentual) },
        { titulo: "Swap", num: true, valor: (p) => pct(p.swap_percentual) },
        { titulo: "Disco /", num: true, valor: (p) => pct(p.disco_percentual) },
        { titulo: "Rede ↓", num: true, valor: (p) => taxa(p.rede_rx_bytes_s) },
        { titulo: "Rede ↑", num: true, valor: (p) => taxa(p.rede_tx_bytes_s) },
      ], [...pontos].reverse())));
      return null;
    }

    const cUso = el("canvas", { role: "img", "aria-label": "Uso de CPU, memória, swap e disco ao longo do tempo" });
    const cRede = el("canvas", { role: "img", "aria-label": "Tráfego de rede recebido e enviado ao longo do tempo" });
    const legendaEventos = marcas.length
      ? el("ul", { class: "lista" }, marcas.map((m) => el("li", {},
          el("div", {}, el("span", { class: "selo", dataset: { nivel: m.item.severidade } }, m.item.severidade), " ", m.item.titulo),
          el("div", { class: "lista-meta", text: dataHora(m.item.momento) }))))
      : el("p", { class: "vazio", text: "Nenhum evento alto/crítico no período." });

    raiz.append(cartao("Uso de recursos", "%", el("div", { class: "grafico grafico-alto" }, cUso),
      el("p", { class: "legenda-nota", text: "Linhas tracejadas verticais marcam eventos de severidade alta ou crítica (lista abaixo)." })));
    raiz.append(cartao("Rede (eth0)", "bytes por segundo", el("div", { class: "grafico" }, cRede)));
    raiz.append(cartao("Eventos marcados nos gráficos", `${marcas.length} no período`, legendaEventos));

    const g1 = graficoLinha(cUso, {
      rotulos, rotulosTooltip, marcas, maxY: 100, formatoY: (v) => pct(v),
      series: [
        { rotulo: "CPU", cor: "--serie-1", dados: pontos.map((p) => p.cpu_percentual) },
        { rotulo: "Memória", cor: "--serie-2", dados: pontos.map((p) => p.memoria_percentual) },
        { rotulo: "Swap", cor: "--serie-3", dados: pontos.map((p) => p.swap_percentual) },
        { rotulo: "Disco /", cor: "--serie-4", dados: pontos.map((p) => p.disco_percentual) },
      ],
    });
    const g2 = graficoLinha(cRede, {
      rotulos, rotulosTooltip, marcas, formatoY: (v) => taxa(v),
      series: [
        { rotulo: "Recebido", cor: "--serie-1", dados: pontos.map((p) => p.rede_rx_bytes_s) },
        { rotulo: "Enviado", cor: "--serie-2", dados: pontos.map((p) => p.rede_tx_bytes_s) },
      ],
    });
    return () => { g1.destroy(); g2.destroy(); };
  },
};
