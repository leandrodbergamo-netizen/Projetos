"""Identidade visual Souq — CSS global e componentes de exibição.

Tokens do redesign (protótipo "Aposta e Distribuição.dc.html"): fundo papel
#F6F4EF, tinta #201D1A, acento #BE3A34, bordas #E5E0D8/#DAD4C9, títulos em
Instrument Serif e UI em Instrument Sans. As cores de base ficam no
.streamlit/config.toml; aqui entra o que o tema não cobre.
"""
import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Instrument+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="st-"] { font-family: 'Instrument Sans', sans-serif; }
h1, h2, h3 { font-family: 'Instrument Serif', serif !important; font-weight: 400 !important; }
h1 { font-size: 40px !important; }
h2 { font-size: 26px !important; }
h3 { font-size: 22px !important; }

/* ---------------- sidebar: papel, borda e pills escuras ---------------- */
[data-testid="stSidebar"] {
  background: #F6F4EF;
  border-right: 1px solid #E5E0D8;
}
[data-testid="stSidebar"] .stButton button {
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #4B463E;
  justify-content: flex-start;
  text-align: left;
  font-size: 14px;
}
[data-testid="stSidebar"] .stButton button:hover { background: #ECE7DE; color: #201D1A; }
[data-testid="stSidebar"] .stButton button[kind="primary"] {
  background: #201D1A; color: #F6F4EF; font-weight: 600;
}
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover { background: #201D1A; }

/* ---------------- botões da área principal ---------------- */
.stButton button, .stDownloadButton button {
  border-radius: 8px;
  font-size: 14.5px;
}
.stButton button[kind="primary"] { font-weight: 600; }
.stButton button[kind="primary"]:hover { background-color: #A32E29; border-color: #A32E29; }
.stButton button[kind="secondary"], .stDownloadButton button {
  border: 1px solid #DAD4C9; color: #4B463E; background: #FFFFFF;
}

/* ---------------- inputs ---------------- */
[data-baseweb="input"], [data-baseweb="select"] > div { border-radius: 8px; }
[data-testid="stWidgetLabel"] p { font-size: 12.5px; font-weight: 600; color: #4B463E; }

/* chips do multiselect em pill escura */
[data-baseweb="tag"] {
  background: #201D1A !important; border-radius: 99px !important;
}
[data-baseweb="tag"] span { color: #F6F4EF !important; }
[data-baseweb="tag"] svg { fill: #CFC8BC !important; }

/* ---------------- avisos no estilo do protótipo ---------------- */
[data-testid="stAlert"] {
  background: #F1EDE6; border-left: 3px solid #C9C2B4;
  border-radius: 0 8px 8px 0; color: #6B6459;
}

/* cartões nativos (st.container border=True) */
[data-testid="stVerticalBlockBorderWrapper"] > div {
  border-color: #E5E0D8 !important; border-radius: 12px !important; background: #FFFFFF;
}

/* ---------------- componentes próprios ---------------- */
.kpi {
  background: #FFFFFF; border: 1px solid #E5E0D8; border-radius: 12px;
  padding: 18px 20px; height: 100%;
}
.kpi-escuro { background: #201D1A; border-color: #201D1A; }
.kpi-rotulo {
  font-size: 11.5px; letter-spacing: .1em; text-transform: uppercase; color: #8A8378;
}
.kpi-escuro .kpi-rotulo { color: #A39A8C; }
.kpi-valor {
  font-family: 'Instrument Serif', serif; font-size: 42px; line-height: 1.15; color: #201D1A;
}
.kpi-escuro .kpi-valor { color: #F6F4EF; }
.kpi-sub { font-size: 12px; color: #8A8378; }

.marca-souq { font-family: 'Instrument Serif', serif; font-size: 26px; line-height: 1.1; color: #201D1A; }
.marca-sub {
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: #8A8378; margin-bottom: 10px;
}

.banner-contexto {
  display: flex; gap: 22px; flex-wrap: wrap; background: #FFFFFF;
  border: 1px solid #E5E0D8; border-radius: 10px; padding: 14px 20px;
  font-size: 13.5px; margin-bottom: 8px;
}
.banner-contexto .mudo { color: #8A8378; }

.swatch {
  width: 56px; height: 70px; border-radius: 6px; display: flex; align-items: center;
  justify-content: center; color: #fff; font-family: 'Instrument Serif', serif;
  font-size: 22px; background: linear-gradient(160deg, #C9C2B4, #8A8378);
}
.foto-espelho { width: 64px; border-radius: 6px; display: block; }

.barra-tam { display: flex; gap: 10px; align-items: flex-end; }
.barra-tam .col { flex: 1; text-align: center; }
.barra-tam .haste { width: 100%; background: #BE3A34; border-radius: 6px 6px 0 0; margin-top: auto; }
.barra-tam .area { height: 110px; display: flex; align-items: flex-end; }
.barra-tam .rot { font-size: 13px; font-weight: 600; margin-top: 6px; }
.barra-tam .sub { font-size: 12px; color: #8A8378; }

.contrib { display: flex; align-items: center; gap: 14px; font-size: 13.5px; margin: 3px 0; }
.contrib .nome { width: 210px; flex: none; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.contrib .trilho { flex: 1; background: #ECE7DE; border-radius: 99px; height: 10px; overflow: hidden; }
.contrib .barra { background: #201D1A; height: 100%; }
.contrib .valor { width: 96px; text-align: right; color: #6B6459; }
</style>
"""


def aplicar() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def kpi(coluna, rotulo: str, valor: str, sub: str = "", escuro: bool = False) -> None:
    """Cartão KPI no padrão do protótipo (o de destaque vai escuro)."""
    classe = "kpi kpi-escuro" if escuro else "kpi"
    coluna.markdown(
        f'<div class="{classe}"><div class="kpi-rotulo">{rotulo}</div>'
        f'<div class="kpi-valor">{valor}</div>'
        f'<div class="kpi-sub">{sub}</div></div>',
        unsafe_allow_html=True,
    )


def banner(itens: list[tuple[str, str]]) -> None:
    """Faixa de contexto: [("faixa de preço", "P2"), ...]."""
    html = "".join(f'<span><span class="mudo">{r}</span> <b>{v}</b></span>' for r, v in itens)
    st.markdown(f'<div class="banner-contexto">{html}</div>', unsafe_allow_html=True)


def barras_tamanho(curva: dict[str, float], total_un: float) -> None:
    """Barras verticais da curva de tamanhos (peso normalizado -> % e un)."""
    soma = sum(curva.values()) or 1.0
    maior = max(curva.values()) / soma if curva else 1.0
    cols = "".join(
        f'<div class="col"><div class="area"><div class="haste" '
        f'style="height:{100 * (p / soma) / maior:.0f}%"></div></div>'
        f'<div class="rot">{t}</div>'
        f'<div class="sub">{total_un * p / soma:.0f} un · {100 * p / soma:.0f}%</div></div>'
        for t, p in curva.items()
    )
    st.markdown(f'<div class="barra-tam">{cols}</div>', unsafe_allow_html=True)


def barras_contribuicao(itens: list[tuple[str, float]]) -> None:
    """Barras horizontais: [(nome, vel un/sem), ...]."""
    maior = max((v for _, v in itens), default=1.0) or 1.0
    html = "".join(
        f'<div class="contrib"><span class="nome">{n}</span>'
        f'<div class="trilho"><div class="barra" style="width:{100 * v / maior:.0f}%"></div></div>'
        f'<span class="valor">{v:.1f} un/sem</span></div>'
        for n, v in itens
    )
    st.markdown(html, unsafe_allow_html=True)
