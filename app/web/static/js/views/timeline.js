import { obter } from "../api.js";
import { cartao, dia, el, hora, selo, seletor, seloNeutro, vazio } from "../dom.js";

const filtros = { horas: "24", tipo: "", severidade: "" };
const TIPOS = ["metrica", "servico", "processo", "sistema", "seguranca"];
const SEVERIDADES = ["info", "aviso", "alto", "critico"];
const PERIODOS = [["6", "6 h"], ["24", "24 h"], ["72", "3 dias"], ["240", "10 dias"]];

export default {
  titulo: "Linha do tempo",
  async render(raiz, ctx) {
    const resp = await obter("/events", { ...filtros, limite: 500 });

    const mudar = (chave) => (v) => { filtros[chave] = v; ctx.recarregar(); };
    raiz.append(el("div", { class: "filtros" },
      seletor({ rotulo: "Período", valor: filtros.horas, opcoes: PERIODOS, todos: null, aoMudar: mudar("horas") }),
      seletor({ rotulo: "Tipo", valor: filtros.tipo, opcoes: TIPOS, aoMudar: mudar("tipo") }),
      seletor({ rotulo: "Severidade", valor: filtros.severidade, opcoes: SEVERIDADES, aoMudar: mudar("severidade") })));

    if (!resp.dados.length) {
      raiz.append(cartao("Eventos", "", vazio("Nenhum evento com esses filtros.")));
      return;
    }

    const lista = el("ol", { class: "timeline" });
    let diaAtual = null;
    for (const e of resp.dados) {
      const d = dia(e.momento);
      if (d !== diaAtual) {
        lista.append(el("li", { class: "timeline-dia", text: d }));
        diaAtual = d;
      }
      lista.append(el("li", { class: "timeline-item", dataset: { nivel: e.severidade } },
        el("div", { class: "lista-meta" },
          el("span", { class: "timeline-hora", text: hora(e.momento) }), selo(e.severidade), seloNeutro(e.tipo),
          e.recurso ? el("span", { text: e.recurso }) : null),
        el("div", { class: "timeline-titulo", text: e.titulo }),
        el("div", { class: "timeline-desc", text: e.descricao })));
    }
    raiz.append(cartao("Eventos", `${resp.dados.length} eventos · mais recente primeiro`, lista));
  },
};
