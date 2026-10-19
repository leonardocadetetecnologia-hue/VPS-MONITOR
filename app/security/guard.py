"""Regras de segurança do MVP, concentradas e testáveis."""

METODOS_PERMITIDOS = frozenset({"GET", "HEAD", "OPTIONS"})

# CSP restritiva: nada de script/estilo externo; Chart.js é servido localmente.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)

# Exceção apenas para a documentação interativa (/docs), que carrega o Swagger UI do CDN.
CSP_DOCS = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "object-src 'none'; frame-ancestors 'none'"
)
CAMINHOS_DOCS = frozenset({"/docs", "/docs/oauth2-redirect"})

CABECALHOS_SEGURANCA = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
    "X-Data-Origin": "SIMULADO",
}


def metodo_permitido(metodo: str) -> bool:
    return metodo.upper() in METODOS_PERMITIDOS


def host_confiavel(cabecalho_host: str | None, confiaveis: tuple[str, ...]) -> bool:
    """Valida o cabeçalho Host (sem porta) contra a lista — barra DNS rebinding."""
    if not cabecalho_host:
        return False
    host = cabecalho_host.strip().lower()
    # IPv6 literal vem entre colchetes ([::1]:8765); nos demais, a porta vem após o último ":".
    host = host[: host.find("]") + 1] if host.startswith("[") else host.rsplit(":", 1)[0]
    return host in {h.lower() for h in confiaveis}
