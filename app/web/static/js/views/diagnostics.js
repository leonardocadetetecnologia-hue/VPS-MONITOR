import { obter } from "../api.js";
import { cartao, dataHora, el, selo, seloNeutro, vazio } from "../dom.js";

const ROTULO_CONFIANCA = { baixa: "Confiança baixa", media: "Confiança média", alta: "Confiança alta" };

function destacar(id) {
  for (const n of document.querySelectorAll(".evidencia.destacada")) n.classList.remove("destacada");
  const alvo = document.getElementById(`ev-${id}`);
  if (alvo) {
    alvo.classList.add("destacada");
    alvo.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

export default {
  titulo: "Diagnóstico",
  async render(raiz) {
    const resp = await obter("/diagnostics", { horas: 24 });
    const d = resp.dados;

    const evidencias = d.evidencias.length
      ? d.evidencias.map((e) => el("article", { class: "evidencia", id: `ev-${e.id}` },
          el("div", { class: "lista-meta" }, selo(e.severidade), el("span", { class: "evidencia-id", text: e.id })),
          el("div", { text: e.descricao }),
          el("div", { class: "lista-meta" },
            el("span", { text: `observado ${dataHora(e.observado_em)}` }), el("span", { text: `fonte: ${e.fonte}` }))))
      : [vazio("Nenhuma evidência fora do normal.")];

    const hipoteses = d.hipoteses.length
      ? d.hipoteses.map((h) => el("article", { class: "hipotese" },
          el("div", { class: "lista-meta" }, seloNeutro(ROTULO_CONFIANCA[h.confianca]), seloNeutro("não confirmada")),
          el("h3", { text: h.titulo }),
          el("p", { text: h.explicacao }),
          el("div", { class: "hipotese-ref", text: "Apoia-se em:" }),
          el("div", { class: "refs" }, h.evidencias_ids.map((id) =>
            el("button", { type: "button", text: id, title: "Destacar evidência", onclick: () => destacar(id) }))),
          el("div", { class: "hipotese-ref", text: "Para confirmar ou descartar:" }),
          el("ul", {}, h.verificacoes_sugeridas.map((v) => el("li", { text: v })))))
      : [vazio("Nenhuma hipótese formulada.")];

    raiz.append(el("div", { class: "grade-2" },
      cartao("Evidências", `${d.evidencias.length} fatos observados`,
        el("p", { class: "explica", text: "Fatos lidos nos dados: valores medidos, estados e eventos registrados. Sem interpretação." }),
        ...evidencias),
      cartao("Hipóteses", `${d.hipoteses.length} explicações possíveis`,
        el("p", { class: "explica", text: "Interpretações que cruzam evidências. Nenhuma é confirmada pelo sistema; confirmar é trabalho de quem investiga." }),
        ...hipoteses)));
  },
};
