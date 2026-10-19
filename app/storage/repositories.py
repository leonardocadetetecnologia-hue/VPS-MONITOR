"""Repositórios: única camada que conhece SQL. Sempre consultas parametrizadas."""

import sqlite3
from datetime import UTC, datetime
from typing import Any

from app.models import Evento, Origem, PontoHistorico, Processo, Severidade, TipoEvento
from app.models.audit import CategoriaAuditoria, PaginaAuditoria, RegistroAuditoria
from app.models.processes import AmostraProcesso
from app.storage.database import Database

_CAMPOS_METRICA = (
    "cpu_percentual",
    "memoria_percentual",
    "swap_percentual",
    "disco_percentual",
    "rede_rx_bytes_s",
    "rede_tx_bytes_s",
)
# Montado uma vez a partir de constantes do módulo (nunca de entrada externa).
_SQL_INSERIR_METRICA = (
    f"INSERT OR REPLACE INTO metricas (momento, origem, {', '.join(_CAMPOS_METRICA)}) "  # noqa: S608
    f"VALUES ({', '.join('?' * (len(_CAMPOS_METRICA) + 2))})"
)


def _iso(momento: datetime) -> str:
    """Sempre UTC com o mesmo formato: assim a comparação textual no SQLite é cronológica."""
    if momento.tzinfo is None:
        raise ValueError("datetime sem fuso horário não é aceito")
    return momento.astimezone(UTC).isoformat(timespec="seconds")


def _ponto(linha: sqlite3.Row) -> PontoHistorico:
    return PontoHistorico(
        momento=datetime.fromisoformat(linha["momento"]),
        origem=Origem(linha["origem"]),
        **{c: linha[c] for c in _CAMPOS_METRICA},
    )


class MetricasRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def inserir(self, pontos: list[PontoHistorico]) -> int:
        linhas = [
            (_iso(p.momento), p.origem.value, *(getattr(p, c) for c in _CAMPOS_METRICA)) for p in pontos
        ]
        with self.db.transacao() as conn:
            return conn.executemany(_SQL_INSERIR_METRICA, linhas).rowcount

    def intervalo(self, inicio: datetime, fim: datetime, max_pontos: int = 0) -> list[PontoHistorico]:
        with self.db.transacao() as conn:
            linhas = conn.execute(
                "SELECT * FROM metricas WHERE momento BETWEEN ? AND ? ORDER BY momento",
                (_iso(inicio), _iso(fim)),
            ).fetchall()
        pontos = [_ponto(linha) for linha in linhas]
        if max_pontos and len(pontos) > max_pontos:
            pontos = reduzir(pontos, max_pontos)
        return pontos

    def ultimo(self) -> PontoHistorico | None:
        with self.db.transacao() as conn:
            linha = conn.execute("SELECT * FROM metricas ORDER BY momento DESC LIMIT 1").fetchone()
        return _ponto(linha) if linha else None

    def contar(self) -> int:
        with self.db.transacao() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM metricas").fetchone()[0])

    def limpar_origem(self, origem: Origem) -> None:
        with self.db.transacao() as conn:
            conn.execute("DELETE FROM metricas WHERE origem = ?", (origem.value,))


def reduzir(pontos: list[PontoHistorico], max_pontos: int) -> list[PontoHistorico]:
    """Agrupa em baldes consecutivos. Média para a maioria; MÁXIMO para CPU,
    memória e swap — numa ferramenta investigativa um pico não pode sumir."""
    if max_pontos < 1:
        raise ValueError("max_pontos deve ser >= 1")
    tamanho = -(-len(pontos) // max_pontos)  # divisão com teto
    reduzidos = []
    for i in range(0, len(pontos), tamanho):
        balde = pontos[i : i + tamanho]
        n = len(balde)
        reduzidos.append(
            PontoHistorico(
                momento=balde[-1].momento,
                origem=balde[0].origem,
                cpu_percentual=max(p.cpu_percentual for p in balde),
                memoria_percentual=max(p.memoria_percentual for p in balde),
                swap_percentual=max(p.swap_percentual for p in balde),
                disco_percentual=round(sum(p.disco_percentual for p in balde) / n, 2),
                rede_rx_bytes_s=round(sum(p.rede_rx_bytes_s for p in balde) / n, 1),
                rede_tx_bytes_s=round(sum(p.rede_tx_bytes_s for p in balde) / n, 1),
            )
        )
    return reduzidos


class EventosRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def inserir(self, eventos: list[Evento]) -> int:
        linhas = [
            (e.id, _iso(e.momento), e.tipo.value, e.severidade.value, e.codigo,
             e.titulo, e.descricao, e.recurso, e.origem.value)
            for e in eventos
        ]  # fmt: skip
        with self.db.transacao() as conn:
            return conn.executemany(
                "INSERT OR IGNORE INTO eventos "
                "(id, momento, tipo, severidade, codigo, titulo, descricao, recurso, origem) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                linhas,
            ).rowcount

    def listar(
        self,
        desde: datetime,
        ate: datetime | None = None,
        tipo: TipoEvento | None = None,
        severidade: Severidade | None = None,
        limite: int = 200,
    ) -> list[Evento]:
        sql = "SELECT * FROM eventos WHERE momento >= ?"
        params: list[Any] = [_iso(desde)]
        if ate is not None:
            sql += " AND momento <= ?"
            params.append(_iso(ate))
        if tipo is not None:
            sql += " AND tipo = ?"
            params.append(tipo.value)
        if severidade is not None:
            sql += " AND severidade = ?"
            params.append(severidade.value)
        sql += " ORDER BY momento DESC LIMIT ?"
        params.append(limite)
        with self.db.transacao() as conn:
            linhas = conn.execute(sql, params).fetchall()
        return [
            Evento(
                id=linha["id"],
                momento=datetime.fromisoformat(linha["momento"]),
                tipo=TipoEvento(linha["tipo"]),
                severidade=Severidade(linha["severidade"]),
                codigo=linha["codigo"],
                titulo=linha["titulo"],
                descricao=linha["descricao"],
                recurso=linha["recurso"],
                origem=Origem(linha["origem"]),
            )
            for linha in linhas
        ]

    def limpar_origem(self, origem: Origem) -> None:
        with self.db.transacao() as conn:
            conn.execute("DELETE FROM eventos WHERE origem = ?", (origem.value,))


class ProcessosRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def inserir(self, leituras: list[tuple[datetime, Processo, str]]) -> int:
        """Grava (momento, processo, grupo). A instância é criada na primeira leitura
        e reaproveitada nas seguintes; tudo numa única transação."""
        ids: dict[tuple[int, str, str], int] = {}
        amostras = []
        with self.db.transacao() as conn:
            for momento, p, grupo in leituras:
                chave = (p.pid, _iso(p.iniciado_em), p.origem.value)
                processo_id = ids.get(chave)
                if processo_id is None:
                    conn.execute(
                        "INSERT INTO processos (pid, iniciado_em, nome, usuario, categoria, unidade_systemd, "
                        "grupo, comando, origem) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT (pid, iniciado_em, origem) DO NOTHING",
                        (chave[0], chave[1], p.nome, p.usuario, p.categoria, p.unidade_systemd, grupo,
                         p.comando, chave[2]),
                    )  # fmt: skip
                    processo_id = int(
                        conn.execute(
                            "SELECT id FROM processos WHERE pid = ? AND iniciado_em = ? AND origem = ?", chave
                        ).fetchone()[0]
                    )
                    ids[chave] = processo_id
                amostras.append(
                    (processo_id, _iso(momento), p.cpu_percentual, p.memoria_percentual, p.memoria_rss_bytes)
                )
            conn.executemany(
                "INSERT OR REPLACE INTO processos_amostras "
                "(processo_id, momento, cpu_percentual, memoria_percentual, memoria_rss_bytes) "
                "VALUES (?, ?, ?, ?, ?)",
                amostras,
            )
        return len(amostras)

    def amostras_grupo(self, grupo: str, inicio: datetime, fim: datetime) -> list[AmostraProcesso]:
        with self.db.transacao() as conn:
            linhas = conn.execute(
                "SELECT a.momento, p.pid, p.iniciado_em, p.nome, a.cpu_percentual, a.memoria_percentual, "
                "a.memoria_rss_bytes FROM processos p "
                "JOIN processos_amostras a ON a.processo_id = p.id "
                "WHERE p.grupo = ? AND a.momento BETWEEN ? AND ? ORDER BY a.momento, p.pid",
                (grupo, _iso(inicio), _iso(fim)),
            ).fetchall()
        return [
            AmostraProcesso(
                momento=datetime.fromisoformat(linha["momento"]),
                pid=linha["pid"],
                iniciado_em=datetime.fromisoformat(linha["iniciado_em"]),
                nome=linha["nome"],
                cpu_percentual=linha["cpu_percentual"],
                memoria_percentual=linha["memoria_percentual"],
                memoria_rss_bytes=linha["memoria_rss_bytes"],
            )
            for linha in linhas
        ]

    def contar_amostras(self) -> int:
        with self.db.transacao() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM processos_amostras").fetchone()[0])

    def limpar_origem(self, origem: Origem) -> None:
        # As amostras saem junto (ON DELETE CASCADE).
        with self.db.transacao() as conn:
            conn.execute("DELETE FROM processos WHERE origem = ?", (origem.value,))


class AuditoriaRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def registrar(
        self,
        momento: datetime,
        categoria: CategoriaAuditoria,
        acao: str,
        detalhe: str | None = None,
        status: int | None = None,
        cliente: str | None = None,
        duracao_ms: float | None = None,
        request_id: str | None = None,
    ) -> None:
        with self.db.transacao() as conn:
            conn.execute(
                "INSERT INTO auditoria "
                "(momento, categoria, acao, detalhe, status, cliente, duracao_ms, request_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _iso(momento),
                    CategoriaAuditoria(categoria).value,
                    acao,
                    detalhe,
                    status,
                    cliente,
                    duracao_ms,
                    request_id,
                ),
            )

    def listar(
        self, limite: int = 100, categoria: CategoriaAuditoria | None = None, antes_id: int | None = None
    ) -> PaginaAuditoria:
        """Paginação por cursor (id decrescente): estável mesmo com inserções concorrentes."""
        sql = "SELECT * FROM auditoria WHERE 1 = 1"
        params: list[Any] = []
        if categoria is not None:
            sql += " AND categoria = ?"
            params.append(CategoriaAuditoria(categoria).value)
        if antes_id is not None:
            sql += " AND id < ?"
            params.append(antes_id)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limite + 1)  # um a mais só para saber se existe próxima página
        with self.db.transacao() as conn:
            linhas = conn.execute(sql, params).fetchall()
        itens = [RegistroAuditoria(**dict(linha)) for linha in linhas[:limite]]
        proximo = itens[-1].id if len(linhas) > limite else None
        return PaginaAuditoria(itens=itens, proximo_antes_id=proximo)
