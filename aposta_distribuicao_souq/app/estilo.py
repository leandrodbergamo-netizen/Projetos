"""Identidade visual Souq — CSS global e componentes de exibição.

Paleta inspirada na loja física: terracota (paredes) como acento, verde-oliva
escuro (teto/painéis) como tinta forte, palha/creme como fundo. Títulos em
Instrument Serif e UI em Instrument Sans. As cores de base ficam no
.streamlit/config.toml; aqui entra o que o tema não cobre.
"""
import streamlit as st

# tokens da loja
TERRACOTA = "#B25B36"
TERRACOTA_HOVER = "#9C4C2B"
VERDE = "#3F4A35"          # oliva escuro (pills, KPI destaque, barras)
FUNDO = "#F3F1EB"
BORDA = "#E3E0D6"
BORDA_INPUT = "#D8D4C8"
TINTA = "#26281F"
TEXTO_2 = "#55534A"
MUDO = "#8F8C7B"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Marcellus&family=Instrument+Sans:wght@400;500;600;700&display=swap');

html, body, [class*="st-"] {{ font-family: 'Instrument Sans', sans-serif; }}
/* a regra acima não pode atropelar a fonte de ícones do Streamlit */
[data-testid="stIconMaterial"], span[class*="material-symbols"] {{
  font-family: 'Material Symbols Rounded' !important;
}}
/* Marcellus: serif romana, o desenho mais próximo do letreiro da loja */
h1, h2, h3 {{ font-family: 'Marcellus', serif !important; font-weight: 400 !important; }}
h1 {{ font-size: 38px !important; }}
h2 {{ font-size: 25px !important; }}
h3 {{ font-size: 21px !important; }}

/* ---------------- sidebar: palha, borda e pills verdes ---------------- */
[data-testid="stSidebar"] {{
  background: {FUNDO};
  border-right: 1px solid {BORDA};
}}
[data-testid="stSidebar"] .stButton button {{
  border-radius: 8px;
  border: none;
  background: transparent;
  color: {TEXTO_2};
  justify-content: flex-start;
  text-align: left;
  font-size: 14px;
}}
[data-testid="stSidebar"] .stButton button:hover {{ background: #E9E6DA; color: {TINTA}; }}
[data-testid="stSidebar"] .stButton button[kind="primary"] {{
  background: {VERDE}; color: {FUNDO}; font-weight: 600;
}}
[data-testid="stSidebar"] .stButton button[kind="primary"]:hover {{ background: {VERDE}; }}

/* ---------------- botões da área principal ---------------- */
/* hierarquia: primário terracota preenchido; secundário com contorno verde e
   fundo tingido (nada de branco), invertendo para verde cheio no hover */
[data-testid="stMain"] .stButton button, [data-testid="stMain"] .stDownloadButton button {{
  border-radius: 8px;
  font-size: 14.5px;
}}
[data-testid="stMain"] .stButton button[kind^="primary"] {{ font-weight: 600; }}
[data-testid="stMain"] .stButton button[kind^="primary"]:hover {{
  background-color: {TERRACOTA_HOVER}; border-color: {TERRACOTA_HOVER};
}}
.stButton button[kind^="secondary"], .stDownloadButton button {{
  border: none; color: {FUNDO} !important; background: {VERDE}; font-weight: 600;
}}
.stButton button[kind^="secondary"]:hover, .stDownloadButton button:hover {{
  background: #55624A; color: {FUNDO} !important;
}}
.stButton button[kind^="secondary"]:disabled, .stButton button[kind^="primary"]:disabled {{
  background: #DAD7CB; color: #98957F !important; border: none;
}}
/* a navegação da sidebar mantém o próprio estilo (pill só quando ativa) */
[data-testid="stSidebar"] .stButton button[kind^="secondary"] {{
  background: transparent; color: {TEXTO_2} !important; font-weight: 400;
}}
[data-testid="stSidebar"] .stButton button[kind^="secondary"]:hover {{
  background: #E9E6DA; color: {TINTA} !important;
}}
/* botão terciário (ex.: lupa da foto): discreto, acende no hover */
.stButton button[kind="tertiary"] {{
  padding: 0 4px; min-height: 0; border: none; background: none;
  font-size: 13px; opacity: .4; color: {TEXTO_2} !important;
}}
.stButton button[kind="tertiary"]:hover {{ opacity: 1; background: none; }}

/* ---------------- inputs ---------------- */
[data-baseweb="input"], [data-baseweb="select"] > div {{ border-radius: 8px; }}
[data-testid="stWidgetLabel"] p {{ font-size: 12.5px; font-weight: 600; color: {TEXTO_2}; }}

/* chips do multiselect em pill verde */
[data-baseweb="tag"] {{
  background: {VERDE} !important; border-radius: 99px !important;
}}
[data-baseweb="tag"] span {{ color: {FUNDO} !important; }}
[data-baseweb="tag"] svg {{ fill: #C6C9B8 !important; }}

/* indicador global de execução: qualquer ação mostra a pill verde no topo */
[data-testid="stStatusWidget"] {{
  background: {VERDE}; border-radius: 99px; padding: 4px 14px;
}}
[data-testid="stStatusWidget"], [data-testid="stStatusWidget"] * {{
  color: #F3F1EB !important; fill: #F3F1EB !important; font-weight: 600;
}}

/* ---------------- avisos no estilo do protótipo ---------------- */
[data-testid="stAlert"] {{
  background: #EEECE2; border-left: 3px solid #C7C4B2;
  border-radius: 0 8px 8px 0; color: #64614F;
}}

/* cartões nativos (st.container border=True) */
[data-testid="stVerticalBlockBorderWrapper"] > div {{
  border-color: {BORDA} !important; border-radius: 12px !important; background: #FFFFFF;
}}
/* cartões de premissas (Configurações): fundo cinza, marcados com .cfg-card */
.cfg-card {{ display: none; }}
[data-testid="stVerticalBlockBorderWrapper"]:has(.cfg-card) > div {{
  background: #ECEBE7 !important; border-color: #DCD9D2 !important;
}}

/* ---------------- componentes próprios ---------------- */
.kpi {{
  background: #FFFFFF; border: 1px solid {BORDA}; border-radius: 12px;
  padding: 18px 20px; height: 100%;
}}
.kpi-escuro {{ background: {VERDE}; border-color: {VERDE}; }}
.kpi-rotulo {{
  font-size: 11.5px; letter-spacing: .1em; text-transform: uppercase; color: {MUDO};
}}
.kpi-escuro .kpi-rotulo {{ color: #B9BCA9; }}
.kpi-valor {{
  font-family: 'Marcellus', serif; font-size: 40px; line-height: 1.15; color: {TINTA};
}}
.kpi-escuro .kpi-valor {{ color: {FUNDO}; }}
.kpi-sub {{ font-size: 12px; color: {MUDO}; }}
.kpi-escuro .kpi-sub {{ color: #B9BCA9; }}

.marca-souq {{ font-family: 'Marcellus', serif; font-size: 24px; line-height: 1.1;
              color: {TINTA}; letter-spacing: .18em; text-transform: uppercase; }}
.marca-sub {{
  font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
  color: {MUDO}; margin-bottom: 10px;
}}

.banner-contexto {{
  display: flex; gap: 22px; flex-wrap: wrap; background: #FFFFFF;
  border: 1px solid {BORDA}; border-radius: 10px; padding: 14px 20px;
  font-size: 13.5px; margin-bottom: 8px;
}}
.banner-contexto .mudo {{ color: {MUDO}; }}

.swatch {{
  width: 56px; height: 70px; border-radius: 6px; display: flex; align-items: center;
  justify-content: center; color: #fff; font-family: 'Marcellus', serif;
  font-size: 22px; background: linear-gradient(160deg, #C8A98E, {TERRACOTA});
}}
.foto-espelho {{ width: 64px; border-radius: 6px; display: block; }}

.barra-tam {{ display: flex; gap: 10px; align-items: flex-end; }}
.barra-tam .col {{ flex: 1; text-align: center; }}
.barra-tam .haste {{ width: 100%; background: {TERRACOTA}; border-radius: 6px 6px 0 0; margin-top: auto; }}
.barra-tam .area {{ height: 110px; display: flex; align-items: flex-end; }}
.barra-tam .rot {{ font-size: 13px; font-weight: 600; margin-top: 6px; }}
.barra-tam .sub {{ font-size: 12px; color: {MUDO}; }}

.contrib {{ display: flex; align-items: center; gap: 14px; font-size: 13.5px; margin: 3px 0; }}
.contrib .nome {{ width: 210px; flex: none; font-weight: 600; overflow: hidden;
                 text-overflow: ellipsis; white-space: nowrap; }}
.contrib .trilho {{ flex: 1; background: #E7E5DA; border-radius: 99px; height: 10px; overflow: hidden; }}
.contrib .barra {{ background: {VERDE}; height: 100%; }}
.contrib .valor {{ width: 96px; text-align: right; color: #64614F; }}
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
