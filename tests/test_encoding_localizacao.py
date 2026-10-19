"""Encoding (MASTER_PROMPT §15) e localização pt-BR (§16), incluindo regressões já corrigidas."""

from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.thresholds import fmt
from app.models import Evento, Origem, Severidade, TipoEvento
from app.models.audit import CategoriaAuditoria
from app.storage.repositories import AuditoriaRepository, EventosRepository
from tests.conftest import AGORA

RAIZ = Path(__file__).resolve().parent.parent
TEXTOS = [
    "João",
    "Conceição",
    "José d'Ávila",
    "Ação",
    "R$ 1.234,56",
    "símbolos ✓ → ±",
    "日本語",
    'aspas "duplas"',
]


@pytest.mark.parametrize("texto", TEXTOS)
def test_texto_especial_ida_e_volta_no_banco(db, texto):
    repo = EventosRepository(db)
    repo.inserir(
        [
            Evento(
                id=f"id-{texto}",
                momento=AGORA,
                tipo=TipoEvento.SISTEMA,
                severidade=Severidade.INFO,
                codigo="C",
                titulo=texto,
                descricao=texto,
                recurso=texto,
                origem=Origem.SIMULADO,
            )
        ]
    )
    lido = repo.listar(AGORA - timedelta(minutes=1))[0]
    assert (lido.titulo, lido.descricao, lido.recurso) == (texto, texto, texto)
    audit = AuditoriaRepository(db)
    audit.registrar(AGORA, CategoriaAuditoria.SISTEMA, texto, detalhe=texto)
    assert audit.listar(limite=1).itens[0].detalhe == texto


def test_api_responde_utf8_com_acentos_intactos(cliente):
    r = cliente.get("/api/services")
    assert (
        "charset=utf-8" in r.headers["content-type"].lower()
        or r.headers["content-type"] == "application/json"
    )
    texto = r.content.decode("utf-8")  # estrito: falha se houver byte inválido
    assert "[Fictício]" in texto
    assert "Ã" not in texto  # mojibake típico de UTF-8 lido como latin-1


def test_dashboard_servido_em_utf8(cliente):
    r = cliente.get("/")
    html = r.content.decode("utf-8")
    assert '<meta charset="utf-8">' in html
    assert "Visão geral" in html and "Diagnóstico" in html


def test_todos_os_arquivos_do_projeto_sao_utf8_valido():
    padroes = [
        "app/**/*.py",
        "app/**/*.js",
        "app/**/*.css",
        "app/**/*.html",
        "tests/*.py",
        "scripts/*",
        "*.md",
    ]
    arquivos = {a for p in padroes for a in RAIZ.glob(p) if a.is_file() and "vendor" not in a.parts}
    assert len(arquivos) > 30
    for arquivo in arquivos:
        dados = arquivo.read_bytes()
        assert not dados.startswith(b"\xef\xbb\xbf"), f"{arquivo.name} tem BOM"
        # U+FFFD é o rastro de um acento perdido numa conversão de encoding.
        assert chr(0xFFFD) not in dados.decode("utf-8"), f"{arquivo.name} tem caractere de substituição"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        (0, "0,0"),
        (49.6, "49,6"),
        (-3.25, "-3,2"),
        (100, "100,0"),
        (1234.56, "1.234,6"),
        (1234567.8, "1.234.567,8"),
    ],
)
def test_fmt_numero_pt_br(valor, esperado):
    assert fmt(valor) == esperado


def test_regressao_textos_de_evento_usam_virgula_decimal(cliente):
    """Bug corrigido: títulos saíam como '(49.5%)'."""
    eventos = cliente.get("/api/events", params={"tipo": "metrica"}).json()["dados"]
    assert eventos
    for e in eventos:
        assert "," in e["titulo"] and ".%" not in e["titulo"]
        assert not any(
            c.isdigit() and n == "." and m.isdigit()
            for c, n, m in zip(e["titulo"], e["titulo"][1:], e["titulo"][2:], strict=False)
        )


def test_regressao_evidencias_nao_misturam_horario_utc(cliente):
    """Bug corrigido: descrições mostravam 'UTC' enquanto a tela mostra horário local."""
    evidencias = cliente.get("/api/diagnostics").json()["dados"]["evidencias"]
    assert evidencias
    assert not any("UTC" in e["descricao"] for e in evidencias)


def test_regressao_capitalizacao_do_dia_e_feita_em_js_nao_em_css():
    """Bug corrigido: CSS capitalize gerava '16 De Outubro'."""
    css = (RAIZ / "app/web/static/css/app.css").read_text(encoding="utf-8")
    assert "text-transform: capitalize" not in css
    js = (RAIZ / "app/web/static/js/dom.js").read_text(encoding="utf-8")
    assert "charAt(0).toUpperCase()" in js
