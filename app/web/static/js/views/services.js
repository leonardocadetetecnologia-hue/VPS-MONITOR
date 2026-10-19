import { obter } from "../api.js";
import { bytes, cartao, dataHora, el, relativo, selo, seletor, seloNeutro, tabela } from "../dom.js";

const filtros = { estado: "", criticidade: "" };
const NIVEL_ESTADO = { active: "normal", inactive: null, failed: "critico", activating: "aviso" };
const ESTADOS = ["active", "failed", "inactive", "activating"];
const CRITICIDADES = ["critica", "alta", "media", "baixa", "indefinida"];

export default {
  titulo: "Serviços",
  async render(raiz, ctx) {
    const resp = await obter("/services", filtros);
    const inv = resp.dados;

    raiz.append(el("div", { class: "chips" },
      el("div", { class: "chip" }, el("strong", { text: String(inv.total) }), el("span", { text: "unidades" })),
      Object.entries(inv.por_estado).map(([k, v]) =>
        el("div", { class: "chip" }, el("strong", { text: String(v) }), el("span", { text: k }))),
      el("div", { class: "chip" },
        el("strong", { text: String(inv.por_criticidade.indefinida || 0) }),
        el("span", { text: "sem criticidade definida" }))));

    const mudar = (chave) => (v) => { filtros[chave] = v; ctx.recarregar(); };
    raiz.append(el("div", { class: "filtros" },
      seletor({ rotulo: "Estado", valor: filtros.estado, opcoes: ESTADOS, aoMudar: mudar("estado") }),
      seletor({ rotulo: "Criticidade", valor: filtros.criticidade, opcoes: CRITICIDADES, aoMudar: mudar("criticidade") })));

    raiz.append(cartao("Inventário de unidades systemd", "falhas primeiro",
      tabela([
        { titulo: "Unidade", valor: (s) => el("div", {}, el("strong", { text: s.unidade }), el("div", { class: "cartao-sub", text: s.descricao })) },
        { titulo: "Estado", valor: (s) => (NIVEL_ESTADO[s.estado_ativo] ? selo(NIVEL_ESTADO[s.estado_ativo], s.estado_ativo) : seloNeutro(s.estado_ativo)) },
        { titulo: "Sub", valor: (s) => s.sub_estado },
        { titulo: "Criticidade", valor: (s) => el("div", {}, seloNeutro(s.criticidade), el("div", { class: "cartao-sub", text: s.justificativa_criticidade })) },
        { titulo: "Tipo", valor: (s) => s.categoria },
        { titulo: "Habilitado", valor: (s) => (s.habilitado ? "sim" : "não") },
        { titulo: "Desde", num: true, valor: (s) => el("div", {}, dataHora(s.desde), el("div", { class: "cartao-sub", text: relativo(s.desde) })) },
        { titulo: "Reinícios 24h", num: true, valor: (s) => s.reinicios_24h },
        { titulo: "PID", num: true, valor: (s) => s.pid_principal ?? "—" },
        { titulo: "Memória", num: true, valor: (s) => bytes(s.memoria_bytes) },
      ], inv.servicos, {
        classeLinha: (s) => (s.estado_ativo === "failed" ? "linha-falha" : null),
        vazio: "Nenhuma unidade com esses filtros.",
      })));

    raiz.append(el("p", { class: "legenda-nota",
      text: "Criticidade “indefinida” é proposital: as aplicações corporativas ainda não tiveram prioridade acordada. "
        + "Só a infraestrutura reconhecível é classificada por regra (app/domain/criticality.py)." }));
  },
};
