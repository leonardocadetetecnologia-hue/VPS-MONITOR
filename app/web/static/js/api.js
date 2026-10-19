// Cliente da API local. Converte toda falha técnica em mensagem compreensível
// e exige que a resposta declare a origem do dado.

export class ErroApi extends Error {
  constructor(mensagem, { status = null, requestId = null } = {}) {
    super(mensagem);
    this.name = "ErroApi";
    this.status = status;
    this.requestId = requestId;
  }
}

export async function obter(caminho, params = {}) {
  const url = new URL(`/api${caminho}`, window.location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
  }

  let resp;
  try {
    resp = await fetch(url, { headers: { Accept: "application/json" } });
  } catch {
    throw new ErroApi("Sem conexão com o servidor local. Verifique se o VPS Insight está em execução.");
  }

  let corpo = null;
  try {
    corpo = await resp.json();
  } catch {
    // corpo não-JSON: tratado abaixo com mensagem genérica
  }

  if (!resp.ok) {
    const erro = corpo?.erro;
    throw new ErroApi(erro?.mensagem || `O servidor respondeu com erro (HTTP ${resp.status}).`, {
      status: resp.status,
      requestId: erro?.request_id ?? resp.headers.get("X-Request-ID"),
    });
  }
  if (!corpo?.origem) throw new ErroApi("Resposta inesperada do servidor: origem do dado não declarada.");
  return corpo;
}
