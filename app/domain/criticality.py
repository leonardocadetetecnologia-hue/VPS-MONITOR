"""Classificação de criticidade das unidades systemd.

A criticidade das aplicações corporativas AINDA NÃO FOI DEFINIDA. Por isso a
regra só classifica o que é infraestrutura reconhecível; o restante fica
`indefinida`, explicitamente, para não inventar prioridade. `CLASSIFICACAO_ACORDADA`
recebe as decisões quando forem tomadas com os responsáveis.
"""

import re

from app.models import Criticidade, Servico

# unidade -> (criticidade, quem/quando decidiu). Vazio até haver acordo.
CLASSIFICACAO_ACORDADA: dict[str, tuple[Criticidade, str]] = {}

_REGRAS_INFRA: list[tuple[re.Pattern, Criticidade, str]] = [
    (re.compile(r"^apache2\.service$"), Criticidade.ALTA, "Servidor web de entrada das aplicações"),
    (re.compile(r"^(mariadb|mysql)\.service$"), Criticidade.ALTA, "Banco de dados"),
    (re.compile(r"^postgresql(@.+)?\.service$"), Criticidade.ALTA, "Banco de dados"),
    (re.compile(r"^(docker|containerd)\.service$"), Criticidade.ALTA, "Runtime de containers"),
    (re.compile(r"^ssh\.service$"), Criticidade.MEDIA, "Acesso administrativo"),
    (re.compile(r"^(cron|systemd-journald)\.service$"), Criticidade.MEDIA, "Serviço básico do SO"),
    (
        re.compile(r"^fwupd(-refresh)?\.service$"),
        Criticidade.BAIXA,
        "Atualização de firmware; irrelevante em VPS",
    ),
]


def classificar_servico(servico: Servico) -> tuple[Criticidade, str]:
    if servico.unidade in CLASSIFICACAO_ACORDADA:
        crit, origem = CLASSIFICACAO_ACORDADA[servico.unidade]
        return crit, f"Acordado: {origem}"
    for padrao, crit, motivo in _REGRAS_INFRA:
        if padrao.match(servico.unidade):
            return crit, f"Regra de infraestrutura: {motivo}"
    return Criticidade.INDEFINIDA, "Pendente: definir com o responsável pela aplicação"


def aplicar_criticidade(servicos: list[Servico]) -> list[Servico]:
    resultado = []
    for s in servicos:
        crit, motivo = classificar_servico(s)
        resultado.append(s.model_copy(update={"criticidade": crit, "justificativa_criticidade": motivo}))
    return resultado
