"""Migrações do SQLite: preservam dados existentes, são atômicas e o banco garante o domínio
(MASTER_PROMPT §9, §12, §55)."""

import sqlite3

import pytest

from app.models import Origem, Severidade, TipoEvento
from app.models.audit import CategoriaAuditoria
from app.storage.database import _V1, VERSAO_ATUAL, Database, MigracaoFalhou


def _banco_v1(caminho, *, metrica_cpu=12.5):
    """Simula um arquivo criado pela versão anterior da aplicação (sem user_version)."""
    conn = sqlite3.connect(caminho)
    conn.executescript(_V1)
    conn.execute(
        "INSERT INTO metricas VALUES ('2026-10-16T12:00:00+00:00','SIMULADO',?,40,5,70,1000,2000)",
        (metrica_cpu,),
    )
    conn.execute(
        "INSERT INTO eventos VALUES ('e1','2026-10-16T12:00:00+00:00','servico','alto','X','Título João',"
        "'Conceição d''Ávila',NULL,'SIMULADO')"
    )
    conn.execute(
        "INSERT INTO auditoria (momento, categoria, acao, status) "
        "VALUES ('2026-10-16T12:00:00+00:00','requisicao','GET /api/x',200)"
    )
    conn.commit()
    conn.close()


def test_banco_novo_nasce_na_versao_atual(tmp_path):
    db = Database(tmp_path / "novo.sqlite3")
    assert db.versao() == VERSAO_ATUAL
    assert db.migracoes_aplicadas == list(range(1, VERSAO_ATUAL + 1))
    db.fechar()


def test_migracao_preserva_dados_existentes(tmp_path):
    caminho = tmp_path / "antigo.sqlite3"
    _banco_v1(caminho)
    db = Database(caminho)
    assert db.migracoes_aplicadas == list(range(1, VERSAO_ATUAL + 1))
    with db.transacao() as conn:
        assert conn.execute("SELECT cpu_percentual FROM metricas").fetchone()[0] == 12.5
        evento = conn.execute("SELECT titulo, descricao FROM eventos").fetchone()
        assert tuple(evento) == ("Título João", "Conceição d'Ávila")
        audit = conn.execute("SELECT acao, status, request_id FROM auditoria").fetchone()
        assert tuple(audit) == ("GET /api/x", 200, None)
    db.fechar()


def test_reabrir_nao_reaplica_migracoes(tmp_path):
    caminho = tmp_path / "x.sqlite3"
    Database(caminho).fechar()
    db = Database(caminho)
    assert db.migracoes_aplicadas == []
    db.fechar()


def test_migracao_que_falha_nao_deixa_banco_pela_metade(tmp_path):
    caminho = tmp_path / "invalido.sqlite3"
    _banco_v1(caminho, metrica_cpu=150)  # dado antigo que viola a constraint nova
    with pytest.raises(MigracaoFalhou, match="Migração 2"):
        Database(caminho)
    conn = sqlite3.connect(caminho)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT cpu_percentual FROM metricas").fetchone()[0] == 150  # dado intacto
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any(t.endswith("_v2") for t in tabelas)
    conn.close()


def test_banco_mais_novo_que_a_aplicacao_e_recusado(tmp_path):
    caminho = tmp_path / "futuro.sqlite3"
    conn = sqlite3.connect(caminho)
    conn.execute(f"PRAGMA user_version = {VERSAO_ATUAL + 1}")
    conn.close()
    with pytest.raises(MigracaoFalhou, match="mais nova"):
        Database(caminho)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO metricas VALUES ('t','SIMULADO',150,1,1,1,1,1)",
        "INSERT INTO metricas VALUES ('t','SIMULADO',-1,1,1,1,1,1)",
        "INSERT INTO metricas VALUES ('t','FALSO',1,1,1,1,1,1)",
        "INSERT INTO metricas VALUES ('t','SIMULADO',1,1,1,1,-5,1)",
        "INSERT INTO eventos VALUES ('e','t','inventado','info','C','T','D',NULL,'SIMULADO')",
        "INSERT INTO eventos VALUES ('e','t','servico','gravissimo','C','T','D',NULL,'SIMULADO')",
        "INSERT INTO eventos VALUES ('e','t','servico','info','C','','D',NULL,'SIMULADO')",
        "INSERT INTO auditoria (momento, categoria, acao) VALUES ('t','outra','x')",
        "INSERT INTO auditoria (momento, categoria, acao, status) VALUES ('t','sistema','x',999)",
    ],
)
def test_banco_recusa_dado_fora_do_dominio(db, sql):
    with pytest.raises(sqlite3.IntegrityError), db.transacao() as conn:
        conn.execute(sql)


def test_constraints_do_banco_aceitam_todos_os_valores_dos_enums(db):
    """Guarda de consistência: enum novo no Python sem migração correspondente quebra aqui."""
    with db.transacao() as conn:
        for i, origem in enumerate(Origem):
            conn.execute("INSERT INTO metricas VALUES (?, ?, 0, 100, 0, 50, 0, 0)", (f"m{i}", origem.value))
        for i, (tipo, sev) in enumerate((t, s) for t in TipoEvento for s in Severidade):
            conn.execute(
                "INSERT INTO eventos VALUES (?, 't', ?, ?, 'C', 'T', 'D', NULL, 'SIMULADO')",
                (f"e{i}", tipo, sev),
            )
        for cat in CategoriaAuditoria:
            conn.execute(
                "INSERT INTO auditoria (momento, categoria, acao) VALUES ('t', ?, 'x')", (cat.value,)
            )
