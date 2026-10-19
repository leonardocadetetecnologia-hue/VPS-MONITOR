"""Geração de eventos a partir de mudanças de nível das métricas."""

from app.domain.thresholds import LIMIARES, classificar, fmt, gravidade, severidade_de
from app.models import Evento, Nivel, PontoHistorico, Severidade, TipoEvento

_CAMPOS = {
    "cpu": "cpu_percentual",
    "memoria": "memoria_percentual",
    "swap": "swap_percentual",
    "disco": "disco_percentual",
}


def eventos_de_transicao(anterior: PontoHistorico | None, atual: PontoHistorico) -> list[Evento]:
    """Um evento por métrica que mudou de nível entre duas leituras consecutivas."""
    eventos = []
    for metrica, campo in _CAMPOS.items():
        valor = getattr(atual, campo)
        novo = classificar(metrica, valor)
        velho = classificar(metrica, getattr(anterior, campo)) if anterior else Nivel.NORMAL
        if novo == velho:
            continue
        limiar = LIMIARES[metrica]
        subiu = gravidade(novo) > gravidade(velho)
        if subiu:
            titulo = f"{limiar.rotulo} entrou em nível {novo.value} ({fmt(valor)}{limiar.unidade})"
            severidade = severidade_de(novo)
            codigo = f"LIMIAR_{metrica.upper()}_SUBIU"
        else:
            titulo = f"{limiar.rotulo} recuou para nível {novo.value} ({fmt(valor)}{limiar.unidade})"
            severidade = Severidade.INFO
            codigo = f"LIMIAR_{metrica.upper()}_RECUOU"
        eventos.append(
            Evento(
                id=f"lim-{metrica}-{int(atual.momento.timestamp())}",
                momento=atual.momento,
                tipo=TipoEvento.METRICA,
                severidade=severidade,
                codigo=codigo,
                titulo=titulo,
                descricao=(
                    f"Mudança de {velho.value} para {novo.value}. Limiares: aviso {limiar.aviso}, "
                    f"alto {limiar.alto}, crítico {limiar.critico} ({limiar.unidade})."
                ),
                recurso=metrica,
                origem=atual.origem,
            )
        )
    return eventos
