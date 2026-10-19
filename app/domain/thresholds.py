"""Limiares de classificação das métricas.

Valores iniciais conservadores para uma VPS de 4 vCPU / 15 GiB. Ficam aqui,
num só lugar, para serem revisados com o time quando houver dados reais.
"""

from dataclasses import dataclass

from app.models import Nivel, Severidade


@dataclass(frozen=True)
class Limiar:
    metrica: str
    rotulo: str
    aviso: float
    alto: float
    critico: float
    unidade: str = "%"

    def classificar(self, valor: float) -> Nivel:
        if valor >= self.critico:
            return Nivel.CRITICO
        if valor >= self.alto:
            return Nivel.ALTO
        if valor >= self.aviso:
            return Nivel.AVISO
        return Nivel.NORMAL


LIMIARES: dict[str, Limiar] = {
    "cpu": Limiar("cpu", "CPU", aviso=70, alto=85, critico=95),
    "memoria": Limiar("memoria", "Memória", aviso=75, alto=85, critico=93),
    "swap": Limiar("swap", "Swap", aviso=20, alto=50, critico=80),
    "disco": Limiar("disco", "Disco /", aviso=80, alto=90, critico=95),
}

# Load por núcleo acima disso indica fila de execução (saturação), não só uso.
LOAD_POR_NUCLEO_ALTO = 1.0

_ORDEM = [Nivel.NORMAL, Nivel.AVISO, Nivel.ALTO, Nivel.CRITICO]


def fmt(valor: float) -> str:
    """Número com uma casa no padrão pt-BR (1.234,5), só para texto exibido.
    Nunca usar o resultado em cálculo."""
    return f"{valor:,.1f}".translate(str.maketrans(",.", ".,"))


def classificar(metrica: str, valor: float) -> Nivel:
    return LIMIARES[metrica].classificar(valor)


def gravidade(nivel: Nivel) -> int:
    return _ORDEM.index(nivel)


def severidade_de(nivel: Nivel) -> Severidade:
    return {
        Nivel.NORMAL: Severidade.INFO,
        Nivel.AVISO: Severidade.AVISO,
        Nivel.ALTO: Severidade.ALTO,
        Nivel.CRITICO: Severidade.CRITICO,
    }[nivel]
