import { ErroApi, obter } from "../api.js";
import { cartao, dataHora, el, linhasTabela, num, selo, seletor, seloNeutro, tabela } from "../dom.js";

const filtros = { categoria: "" };
const NIVEL = { bloqueio: "alto", sistema: "info" };
const POR_PAGINA = 100;

const COLUNAS = [
  { titulo: "#", num: true, valor: (a) => a.id },
  { titulo: "Momento", classe: "mono-linha", valor: (a) => dataHora(a.momento) },
  { titulo: "Categoria", valor: (a) => (NIVEL[a.categoria] ? selo(NIVEL[a.categoria], a.categoria) : seloNeutro(a.categoria)) },
  { titulo: "Ação", classe: "mono-linha", valor: (a) => a.acao },
  { titulo: "Detalhe", valor: (a) => a.detalhe || "—" },
  { titulo: "Status", num: true, valor: (a) => a.status ?? "—" },
  { titulo: "Cliente", valor: (a) => a.cliente || "—" },
  { titulo: "ms", num: true, valor: (a) => (a.duracao_ms == null ? "—" : num(a.duracao_ms)) },
  { titulo: "Request ID", classe: "mono-linha", valor: (a) => a.request_id || "—" },
];

export default {
  titulo: "Auditoria",
  async render(raiz, ctx) {
    const resp = await obter("/audit", { limite: POR_PAGINA, ...filtros });
    let cursor = resp.dados.proximo_antes_id;

    raiz.append(el("div", { class: "filtros" },
      seletor({
        rotulo: "Categoria", valor: filtros.categoria, todos: "Todas",
        opcoes: ["requisicao", "bloqueio", "sistema"],
        aoMudar: (v) => { filtros.categoria = v; ctx.recarregar(); },
      })));

    const conteudo = tabela(COLUNAS, resp.dados.itens, { vazio: "Nenhum registro nesta categoria." });
    const status = el("p", { class: "cartao-sub", role: "status" });

    // Paginação por cursor: acrescenta linhas à tabela existente, sem recarregar a tela.
    const botao = el("button", {
      type: "button", class: "botao-fantasma", text: "Carregar mais",
      onclick: async () => {
        botao.disabled = true; // evita duplo clique pedir a mesma página
        status.textContent = "Carregando…";
        try {
          const prox = await obter("/audit", { limite: POR_PAGINA, antes_id: cursor, ...filtros });
          conteudo.querySelector("tbody").append(...linhasTabela(COLUNAS, prox.dados.itens));
          cursor = prox.dados.proximo_antes_id;
          status.textContent = "";
          if (cursor === null) botao.remove();
        } catch (erro) {
          status.textContent = erro instanceof ErroApi ? erro.message : "Falha ao carregar mais registros.";
        } finally {
          botao.disabled = false;
        }
      },
    });

    raiz.append(cartao("Trilha de auditoria", "consultas à API, bloqueios e ciclo de vida",
      conteudo, cursor !== null ? el("div", { class: "mais" }, botao) : null, status));
  },
};
