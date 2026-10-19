"""Acesso ao SQLite local, com migrações versionadas.

A versão do esquema fica em `PRAGMA user_version`. Cada migração é um script
SQL imutável, aplicado uma única vez, dentro de transação: se falhar, nada
muda e a aplicação não sobe (fail fast). Para mudar o esquema, ACRESCENTE uma
migração ao final de `MIGRACOES` — nunca edite uma já publicada.
"""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# v1 — esquema original do MVP. Mantido literalmente para reconhecer arquivos antigos.
_V1 = """
CREATE TABLE IF NOT EXISTS metricas (
    momento            TEXT PRIMARY KEY,
    origem             TEXT NOT NULL,
    cpu_percentual     REAL NOT NULL,
    memoria_percentual REAL NOT NULL,
    swap_percentual    REAL NOT NULL,
    disco_percentual   REAL NOT NULL,
    rede_rx_bytes_s    REAL NOT NULL,
    rede_tx_bytes_s    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS eventos (
    id         TEXT PRIMARY KEY,
    momento    TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    severidade TEXT NOT NULL,
    codigo     TEXT NOT NULL,
    titulo     TEXT NOT NULL,
    descricao  TEXT NOT NULL,
    recurso    TEXT,
    origem     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_momento ON eventos (momento);
CREATE TABLE IF NOT EXISTS auditoria (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    momento    TEXT NOT NULL,
    categoria  TEXT NOT NULL,
    acao       TEXT NOT NULL,
    detalhe    TEXT,
    status     INTEGER,
    cliente    TEXT,
    duracao_ms REAL
);
CREATE INDEX IF NOT EXISTS ix_auditoria_momento ON auditoria (momento);
"""

# v2 — o banco passa a garantir o domínio (CHECK), e a auditoria ganha request_id.
# SQLite não altera constraints de tabela existente: recria e copia os dados.
# Os domínios abaixo espelham os enums de app/models; tests/test_migracoes.py
# falha se divergirem.
_V2 = """
CREATE TABLE metricas_v2 (
    momento            TEXT PRIMARY KEY,
    origem             TEXT NOT NULL CHECK (origem IN ('SIMULADO', 'REAL')),
    cpu_percentual     REAL NOT NULL CHECK (cpu_percentual BETWEEN 0 AND 100),
    memoria_percentual REAL NOT NULL CHECK (memoria_percentual BETWEEN 0 AND 100),
    swap_percentual    REAL NOT NULL CHECK (swap_percentual BETWEEN 0 AND 100),
    disco_percentual   REAL NOT NULL CHECK (disco_percentual BETWEEN 0 AND 100),
    rede_rx_bytes_s    REAL NOT NULL CHECK (rede_rx_bytes_s >= 0),
    rede_tx_bytes_s    REAL NOT NULL CHECK (rede_tx_bytes_s >= 0)
);
INSERT INTO metricas_v2 SELECT momento, origem, cpu_percentual, memoria_percentual, swap_percentual,
    disco_percentual, rede_rx_bytes_s, rede_tx_bytes_s FROM metricas;
DROP TABLE metricas;
ALTER TABLE metricas_v2 RENAME TO metricas;

CREATE TABLE eventos_v2 (
    id         TEXT PRIMARY KEY CHECK (id <> ''),
    momento    TEXT NOT NULL,
    tipo       TEXT NOT NULL CHECK (tipo IN ('metrica', 'servico', 'processo', 'sistema', 'seguranca')),
    severidade TEXT NOT NULL CHECK (severidade IN ('info', 'aviso', 'alto', 'critico')),
    codigo     TEXT NOT NULL CHECK (codigo <> ''),
    titulo     TEXT NOT NULL CHECK (titulo <> ''),
    descricao  TEXT NOT NULL,
    recurso    TEXT,
    origem     TEXT NOT NULL CHECK (origem IN ('SIMULADO', 'REAL'))
);
INSERT INTO eventos_v2 SELECT id, momento, tipo, severidade, codigo, titulo, descricao, recurso, origem
    FROM eventos;
DROP TABLE eventos;
ALTER TABLE eventos_v2 RENAME TO eventos;
CREATE INDEX ix_eventos_momento ON eventos (momento);

CREATE TABLE auditoria_v2 (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    momento    TEXT NOT NULL,
    categoria  TEXT NOT NULL CHECK (categoria IN ('requisicao', 'bloqueio', 'sistema')),
    acao       TEXT NOT NULL CHECK (acao <> ''),
    detalhe    TEXT,
    status     INTEGER CHECK (status IS NULL OR status BETWEEN 100 AND 599),
    cliente    TEXT,
    duracao_ms REAL CHECK (duracao_ms IS NULL OR duracao_ms >= 0),
    request_id TEXT
);
INSERT INTO auditoria_v2 (id, momento, categoria, acao, detalhe, status, cliente, duracao_ms)
    SELECT id, momento, categoria, acao, detalhe, status, cliente, duracao_ms FROM auditoria;
DROP TABLE auditoria;
ALTER TABLE auditoria_v2 RENAME TO auditoria;
CREATE INDEX ix_auditoria_momento ON auditoria (momento);
-- filtro por categoria + paginação por cursor (id decrescente)
CREATE INDEX ix_auditoria_categoria_id ON auditoria (categoria, id);
"""

# v3 — histórico de processos para a análise de consumo.
# `processos` é a instância (pid + início: o pid sozinho é reaproveitado pelo kernel);
# `processos_amostras` é a série temporal dela. `grupo` (unidade systemd ou nome) é
# gravado na instância para a consulta da análise usar índice.
_V3 = """
CREATE TABLE processos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pid             INTEGER NOT NULL CHECK (pid > 0),
    iniciado_em     TEXT NOT NULL,
    nome            TEXT NOT NULL CHECK (nome <> ''),
    usuario         TEXT NOT NULL,
    categoria       TEXT NOT NULL,
    unidade_systemd TEXT,
    grupo           TEXT NOT NULL CHECK (grupo <> ''),
    comando         TEXT NOT NULL,
    origem          TEXT NOT NULL CHECK (origem IN ('SIMULADO', 'REAL')),
    UNIQUE (pid, iniciado_em, origem)
);
CREATE INDEX ix_processos_grupo ON processos (grupo);

CREATE TABLE processos_amostras (
    processo_id        INTEGER NOT NULL REFERENCES processos (id) ON DELETE CASCADE,
    momento            TEXT NOT NULL,
    cpu_percentual     REAL NOT NULL CHECK (cpu_percentual >= 0),
    memoria_percentual REAL NOT NULL CHECK (memoria_percentual BETWEEN 0 AND 100),
    memoria_rss_bytes  INTEGER NOT NULL CHECK (memoria_rss_bytes >= 0),
    PRIMARY KEY (processo_id, momento)
) WITHOUT ROWID;
CREATE INDEX ix_processos_amostras_momento ON processos_amostras (momento);
"""

MIGRACOES: list[tuple[int, str, str]] = [
    (1, "esquema inicial", _V1),
    (2, "constraints de domínio e request_id na auditoria", _V2),
    (3, "histórico de processos (instâncias e amostras)", _V3),
]
VERSAO_ATUAL = MIGRACOES[-1][0]


class MigracaoFalhou(RuntimeError):
    """Migração não aplicada; o banco ficou exatamente como estava."""


def aplicar_migracoes(conn: sqlite3.Connection) -> list[int]:
    versao = conn.execute("PRAGMA user_version").fetchone()[0]
    if versao > VERSAO_ATUAL:
        raise MigracaoFalhou(
            f"Banco na versão {versao}, mais nova que a suportada ({VERSAO_ATUAL}). Atualize a aplicação."
        )
    aplicadas = []
    for numero, descricao, sql in MIGRACOES:
        if numero <= versao:
            continue
        try:
            # executescript faz COMMIT do que estiver pendente; o BEGIN explícito
            # torna DDL + cópia de dados + user_version uma única transação.
            conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {numero};\nCOMMIT;")
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.rollback()
            raise MigracaoFalhou(f"Migração {numero} ({descricao}) falhou: {exc}") from exc
        aplicadas.append(numero)
    return aplicadas


class Database:
    def __init__(self, caminho: Path | str) -> None:
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.caminho, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self.migracoes_aplicadas = aplicar_migracoes(self._conn)

    def versao(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    @contextmanager
    def transacao(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def fechar(self) -> None:
        with self._lock:
            self._conn.close()
