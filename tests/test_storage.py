from datetime import datetime, timedelta

import pytest

from app.models import Evento, Origem, PontoHistorico, Severidade, TipoEvento
from app.models.audit import CategoriaAuditoria
from app.storage.repositories import AuditoriaRepository, EventosRepository, MetricasRepository, reduzir
from tests.conftest import AGORA


def _ponto(minutos_atras: int, cpu: float = 10.0) -> PontoHistorico:
    return PontoHistorico(
        momento=AGORA - timedelta(minutes=minutos_atras),
        origem=Origem.SIMULADO,
        cpu_percentual=cpu,
        memoria_percentual=40,
        swap_percentual=5,
        disco_percentual=70,
        rede_rx_bytes_s=1000,
        rede_tx_bytes_s=2000,
    )


def test_metricas_ida_e_volta(db):
    repo = MetricasRepository(db)
    repo.inserir([_ponto(i) for i in range(10)])
    pontos = repo.intervalo(AGORA - timedelta(minutes=5), AGORA)
    assert len(pontos) == 6
    assert pontos == sorted(pontos, key=lambda p: p.momento)
    ultimo = repo.ultimo()
    assert ultimo is not None and ultimo.momento == AGORA


def test_reducao_preserva_pico(db):
    pontos = [_ponto(i, cpu=10) for i in range(100, 0, -1)]
    pontos[37] = _ponto(63, cpu=99)
    reduzidos = reduzir(pontos, 10)
    assert len(reduzidos) == 10
    assert max(p.cpu_percentual for p in reduzidos) == 99


def test_datetime_sem_fuso_e_recusado(db):
    with pytest.raises(ValueError):
        MetricasRepository(db).intervalo(datetime(2026, 1, 1), datetime(2026, 1, 2))


def test_eventos_sao_idempotentes_e_filtraveis(db):
    repo = EventosRepository(db)
    ev = Evento(
        id="x1",
        momento=AGORA,
        tipo=TipoEvento.SERVICO,
        severidade=Severidade.ALTO,
        codigo="SERVICE_FAILED",
        titulo="t",
        descricao="d",
        origem=Origem.SIMULADO,
    )
    repo.inserir([ev])
    repo.inserir([ev])
    assert len(repo.listar(AGORA - timedelta(hours=1))) == 1
    assert repo.listar(AGORA - timedelta(hours=1), tipo=TipoEvento.METRICA) == []
    assert len(repo.listar(AGORA - timedelta(hours=1), severidade=Severidade.ALTO)) == 1


def test_filtro_de_evento_nao_aceita_injecao(db):
    repo = EventosRepository(db)
    # parâmetro malicioso vira apenas um valor comparado, nunca SQL
    assert repo.listar(AGORA, limite=5) == []
    AuditoriaRepository(db).registrar(AGORA, CategoriaAuditoria.REQUISICAO, "GET /x'; DROP TABLE eventos; --")
    assert repo.listar(AGORA - timedelta(days=1)) == []  # tabela continua existindo


def test_limpar_origem_simulada_nao_toca_outras(db):
    repo = MetricasRepository(db)
    repo.inserir([_ponto(1)])
    real = _ponto(2).model_copy(update={"origem": Origem.REAL})
    repo.inserir([real])
    repo.limpar_origem(Origem.SIMULADO)
    restantes = repo.intervalo(AGORA - timedelta(hours=1), AGORA)
    assert [p.origem for p in restantes] == [Origem.REAL]


def test_auditoria_registra_e_lista(db):
    repo = AuditoriaRepository(db)
    repo.registrar(AGORA, CategoriaAuditoria.SISTEMA, "inicializacao", detalhe="ok")
    repo.registrar(AGORA, CategoriaAuditoria.BLOQUEIO, "POST /api/x", detalhe="metodo_nao_permitido")
    assert [a.categoria for a in repo.listar().itens] == ["bloqueio", "sistema"]
    assert len(repo.listar(categoria=CategoriaAuditoria.SISTEMA).itens) == 1


def test_auditoria_paginacao_por_cursor_percorre_tudo_sem_repetir(db):
    repo = AuditoriaRepository(db)
    for i in range(25):
        repo.registrar(AGORA, CategoriaAuditoria.REQUISICAO, f"GET /api/{i}")
    vistos, cursor = [], None
    while True:
        pagina = repo.listar(limite=10, antes_id=cursor)
        vistos += [a.id for a in pagina.itens]
        cursor = pagina.proximo_antes_id
        if cursor is None:
            break
    assert len(vistos) == 25 and len(set(vistos)) == 25
    assert vistos == sorted(vistos, reverse=True)


def test_auditoria_categoria_invalida_falha_antes_do_banco(db):
    with pytest.raises(ValueError):
        AuditoriaRepository(db).registrar(AGORA, "inventada", "x")  # type: ignore[arg-type]
