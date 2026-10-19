"""Catálogo das integrações planejadas. Não há coleta: só o contrato previsto."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import envelope
from app.models import Envelope
from app.models.integrations import ContainerDocker, EstatisticaBanco, IntegracaoPlanejada, RegistroHttp

router = APIRouter(prefix="/integrations", tags=["integracoes-futuras"])


def _campos(modelo: type[BaseModel]) -> list[str]:
    return [n for n in modelo.model_fields if n != "origem"]


PLANEJADAS = [
    IntegracaoPlanejada(
        chave="http",
        nome="Logs HTTP (Apache)",
        descricao="Volume, latência e taxa de erro 4xx/5xx por vhost, correlacionados com a linha do tempo.",
        modelo="RegistroHttp",
        campos=_campos(RegistroHttp),
        fonte_prevista="/var/log/apache2/*access.log (leitura via grupo adm, sem root)",
        salvaguardas=[
            "IP do cliente armazenado apenas como hash",
            "Sem corpo de requisição, cookies ou query string com dados pessoais",
            "Leitura incremental (tail), sem rotacionar nem truncar arquivos",
        ],
    ),
    IntegracaoPlanejada(
        chave="docker",
        nome="Docker",
        descricao="Estado, saúde, reinícios e consumo por container.",
        modelo="ContainerDocker",
        campos=_campos(ContainerDocker),
        fonte_prevista="API do Docker através de proxy de socket somente-GET",
        salvaguardas=[
            "Sem container privilegiado e sem montar o socket com escrita",
            "Apenas endpoints de listagem e estatísticas",
        ],
    ),
    IntegracaoPlanejada(
        chave="bancos",
        nome="Bancos de dados (PostgreSQL 16 e MariaDB)",
        descricao="Conexões, consultas lentas e tamanho, sem acesso a dados de negócio.",
        modelo="EstatisticaBanco",
        campos=_campos(EstatisticaBanco),
        fonte_prevista="pg_stat_activity / pg_stat_statements; SHOW GLOBAL STATUS",
        salvaguardas=[
            "Usuário dedicado com papel pg_monitor / PROCESS, sem SELECT em tabelas de negócio",
            "Somente leitura, timeout curto por consulta",
            "Texto de consulta normalizado (sem parâmetros literais)",
        ],
    ),
]


@router.get("", response_model=Envelope[list[IntegracaoPlanejada]])
def listar() -> Envelope[list[IntegracaoPlanejada]]:
    return envelope(PLANEJADAS)
