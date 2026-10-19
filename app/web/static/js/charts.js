// Gráficos de linha (Chart.js) no padrão do projeto: linhas de 2px, sem pontos,
// tooltip único com todas as séries, cursor vertical e marcadores de evento.
import { cssVar } from "./dom.js";

const cursorVertical = {
  id: "cursorVertical",
  afterDatasetsDraw(chart) {
    const ativos = chart.tooltip?.getActiveElements?.() ?? [];
    if (!ativos.length) return;
    const x = ativos[0].element.x;
    const { top, bottom } = chart.chartArea;
    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = cssVar("--eixo");
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
    ctx.restore();
  },
};

// Marcadores verticais tracejados nos índices onde ocorreram eventos relevantes.
const marcadoresEvento = {
  id: "marcadoresEvento",
  afterDraw(chart, _args, opcoes) {
    const marcas = opcoes?.marcas ?? [];
    if (!marcas.length) return;
    const { top, bottom } = chart.chartArea;
    const escalaX = chart.scales.x;
    const ctx = chart.ctx;
    ctx.save();
    for (const m of marcas) {
      const x = escalaX.getPixelForValue(m.indice);
      ctx.strokeStyle = m.cor;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = m.cor;
      ctx.beginPath();
      ctx.moveTo(x - 5, top - 1);
      ctx.lineTo(x + 5, top - 1);
      ctx.lineTo(x, top + 6);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  },
};

// Quantos rótulos de horário (~5 caracteres) cabem no eixo X sem se sobrepor.
const rotulosQueCabem = (largura) => Math.max(3, Math.min(8, Math.floor(largura / 75)));

// Marcadores de ocorrência: posiciona cada item (com `momento`) no ponto mais próximo
// no tempo; itens fora do intervalo do gráfico são descartados.
// `corDe(item)` devolve o nome da variável CSS da cor, ou null para não marcar.
export function marcasPorMomento(pontos, itens, corDe) {
  if (!pontos.length) return [];
  const tempos = pontos.map((p) => new Date(p.momento).getTime());
  return itens
    .map((item) => {
      const cor = corDe(item);
      const t = new Date(item.momento).getTime();
      if (!cor || t < tempos[0] || t > tempos[tempos.length - 1]) return null;
      let indice = 0;
      for (let i = 1; i < tempos.length; i++) if (Math.abs(tempos[i] - t) < Math.abs(tempos[indice] - t)) indice = i;
      return { indice, cor: cssVar(cor), item };
    })
    .filter(Boolean);
}

// `legenda: false` para série única: o título do cartão já diz o que é a linha.
export function graficoLinha(canvas, { rotulos, series, formatoY, maxY, marcas = [], rotulosTooltip, legenda = true }) {
  if (!window.Chart) throw new Error("Chart.js não carregou (static/vendor/chart.umd.min.js)");
  const tinta2 = cssVar("--tinta-2");
  const suave = cssVar("--tinta-suave");
  const grade = cssVar("--grade");
  const superficie = cssVar("--superficie");
  const tinta = cssVar("--tinta");

  return new window.Chart(canvas, {
    type: "line",
    data: {
      labels: rotulos,
      datasets: series.map((s) => ({
        label: s.rotulo,
        data: s.dados,
        borderColor: cssVar(s.cor),
        backgroundColor: cssVar(s.cor),
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBorderWidth: 2,
        pointHoverBorderColor: superficie,
        tension: 0.25,
        spanGaps: true,
      })),
    },
    plugins: [cursorVertical, marcadoresEvento],
    options: {
      animation: false,
      // O autoSkip do Chart.js não evita sobreposição em telas estreitas: o limite
      // acompanha a largura real do gráfico a cada redimensionamento.
      onResize: (grafico, tamanho) => {
        grafico.options.scales.x.ticks.maxTicksLimit = rotulosQueCabem(tamanho.width);
      },
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      layout: { padding: { top: 8 } },
      plugins: {
        marcadoresEvento: { marcas },
        legend: {
          display: legenda,
          position: "top",
          align: "start",
          labels: { color: tinta2, usePointStyle: true, pointStyle: "line", boxWidth: 18, font: { size: 12 } },
        },
        tooltip: {
          backgroundColor: superficie,
          titleColor: tinta,
          bodyColor: tinta,
          borderColor: grade,
          borderWidth: 1,
          padding: 10,
          usePointStyle: true,
          callbacks: {
            title: (itens) => (rotulosTooltip ? rotulosTooltip[itens[0].dataIndex] : itens[0].label),
            label: (item) => ` ${formatoY(item.parsed.y)}  ${item.dataset.label}`,
            labelPointStyle: () => ({ pointStyle: "line", rotation: 0 }),
          },
        },
      },
      scales: {
        x: {
          ticks: { color: suave, maxTicksLimit: rotulosQueCabem(window.innerWidth - 120), autoSkip: true, maxRotation: 0 },
          grid: { display: false },
          border: { color: cssVar("--eixo") },
        },
        y: {
          min: 0,
          max: maxY,
          ticks: { color: suave, callback: (v) => formatoY(v), maxTicksLimit: 6 },
          grid: { color: grade },
          border: { display: false },
        },
      },
    },
  });
}
