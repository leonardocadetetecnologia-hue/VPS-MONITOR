import { obter } from "../api.js";
import { cartao, el, seloNeutro } from "../dom.js";

export default {
  titulo: "Integrações futuras",
  async render(raiz) {
    const resp = await obter("/integrations");
    raiz.append(el("p", { class: "explica",
      text: "Estrutura reservada para a próxima etapa. Os modelos de dados e as interfaces de coletor já existem; nenhuma coleta está ativa." }));
    raiz.append(el("div", { class: "grade-2" }, resp.dados.map((i) =>
      cartao(i.nome, "", el("div", { class: "integracao" },
        el("div", { class: "lista-meta" }, seloNeutro(i.status), el("span", { text: `modelo ${i.modelo}` })),
        el("p", { text: i.descricao }),
        el("div", { class: "cartao-sub", text: `Fonte prevista: ${i.fonte_prevista}` }),
        el("div", { class: "campos" }, i.campos.map((c) => el("code", { text: c }))),
        el("h3", { text: "Salvaguardas", style: "margin-top:12px" }),
        el("ul", {}, i.salvaguardas.map((s) => el("li", { text: s }))))))));
  },
};
