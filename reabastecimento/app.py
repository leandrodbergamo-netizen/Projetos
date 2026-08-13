"""App Streamlit: sugestões de remanejamento + dashboard de ruptura + painel V×E.

Redesign visual (jul/2026): tema sóbrio (verde-petróleo/terracota), header
próprio, parâmetros em popover, cards HTML e tabelas com nomes legíveis.
A lógica de negócio (engine/cobertura/sazonalidade) não muda aqui.
"""
from __future__ import annotations

import html as _html
import io
import re as _re

import altair as alt
import pandas as pd
import streamlit as st

import aderencia
import config
import data_source
import engine
import painel
from data_source import carregar_dados

# --- Paleta (única fonte de cor do app) -------------------------------------
COR = {
    "fundo": "#F4F3F0", "superficie": "#FFFFFF", "borda": "#E4E2DD",
    "texto": "#1C1E21", "texto2": "#6B7075", "texto3": "#9A9E9C",
    "acento": "#17635A", "alerta": "#B04A3A", "barra": "#3E6B65",
    "header": "#1C2B29", "cab_tabela": "#1E3A5F",
}

st.set_page_config(page_title="Reabastecimento", layout="wide",
                   initial_sidebar_state="collapsed")


def inject_css() -> None:
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap');

html, body, [class*="st-"] {{
    font-family: 'IBM Plex Sans', sans-serif;
}}
/* Ícones do Streamlit são ligaduras Material Symbols ("expand_more" etc.):
   precisam manter a fonte de ícones, senão viram texto sobreposto. */
[data-testid="stIconMaterial"], [class*="material-symbols"] {{
    font-family: 'Material Symbols Rounded' !important;
}}
[data-testid="stMetric"], [data-testid="stDataFrame"], .card-v, .conta {{
    font-variant-numeric: tabular-nums;
}}
#MainMenu, footer, [data-testid="stStatusWidget"], .stDeployButton,
[data-testid="stDecoration"], header[data-testid="stHeader"] {{
    display: none !important;
}}
.block-container {{ padding-top: 1.5rem; max-width: 1280px; }}

/* Header global */
.souq-header {{
    position: relative; left: 50%; margin-left: -50vw; width: 100vw;
    margin-top: -1.5rem; margin-bottom: 0;
    background: {COR["header"]}; color: #E8EAE9;
    padding: 0.85rem max(calc((100vw - 1280px) / 2 + 1rem), 1.5rem);
    display: flex; justify-content: space-between; align-items: center;
}}
.souq-header .logo {{ font-weight: 700; letter-spacing: 0.12em; font-size: 16px; color: #fff; }}
.souq-header .titulo {{ margin-left: 14px; font-size: 14px; color: #C9CECC; }}
.souq-header .meta {{ font-size: 12.5px; color: #C9CECC; }}
.souq-header .meta b {{ color: #fff; font-weight: 600; }}
.souq-header .dot {{
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: #4CAF7D; margin: 0 5px 1px 16px;
}}

/* Abas */
.stTabs [data-baseweb="tab-list"] {{ gap: 1.6rem; border-bottom: 1px solid {COR["borda"]}; }}
.stTabs [data-baseweb="tab"] {{ padding: 0.55rem 0.2rem; color: {COR["texto2"]}; font-weight: 500; }}
.stTabs [aria-selected="true"] {{ color: {COR["texto"]}; font-weight: 600; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {COR["acento"]}; }}
.stTabs [data-baseweb="tab-border"] {{ background-color: {COR["borda"]}; }}

/* Títulos de página */
.pg-titulo {{ font-size: 26px; font-weight: 700; color: {COR["texto"]}; margin: 0.6rem 0 0.1rem; }}
.pg-sub {{ font-size: 13.5px; color: {COR["texto2"]}; margin-bottom: 0.9rem; }}

/* Chips de parâmetros */
.chips {{ display: flex; gap: 8px; flex-wrap: wrap; padding-top: 2px; }}
.chip {{
    background: {COR["superficie"]}; border: 1px solid {COR["borda"]}; border-radius: 8px;
    padding: 6px 12px; font-size: 12.5px; color: {COR["texto2"]};
}}
.chip b {{ color: {COR["texto"]}; font-weight: 600; margin-left: 4px; }}

/* Cards de métricas */
.card {{
    background: {COR["superficie"]}; border: 1px solid {COR["borda"]}; border-radius: 8px;
    padding: 14px 16px 12px;
}}
.card-l {{ font-size: 12px; color: {COR["texto2"]}; margin-bottom: 2px; }}
.card-v {{ font-size: 26px; font-weight: 600; line-height: 1.2; }}
.card-c {{ font-size: 11.5px; color: {COR["texto3"]}; margin-top: 2px; }}

/* Linha de contagem/exportação */
.conta {{ font-size: 12.5px; color: {COR["texto2"]}; padding-top: 0.45rem; }}

/* Tabelas HTML (header azul escuro, fonte branca) */
.tb-wrap {{
    overflow: auto; border: 1px solid {COR["borda"]}; border-radius: 8px;
    background: {COR["superficie"]};
}}
.tb {{ border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12.5px; }}
.tb thead th {{
    position: sticky; top: 0; z-index: 2;
    background: {COR["cab_tabela"]}; color: #FFFFFF;
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; padding: 8px 10px; text-align: left; white-space: nowrap;
}}
.tb td {{
    padding: 6px 10px; border-bottom: 1px solid #EDECE8; white-space: nowrap;
    font-variant-numeric: tabular-nums;
}}
.tb tbody tr:hover {{ background: #F7F6F3; }}
.tb-aviso {{ font-size: 11.5px; color: {COR["texto3"]}; margin: 4px 2px 0; }}

/* Painéis com borda (containers) */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {COR["superficie"]}; border-color: {COR["borda"]} !important; border-radius: 10px;
}}
.panel-titulo {{ font-size: 15px; font-weight: 600; color: {COR["texto"]}; }}
.panel-nota {{ font-size: 11.5px; color: {COR["texto3"]}; text-align: right; padding-top: 2px; }}

</style>""", unsafe_allow_html=True)


inject_css()

# --- Header global ----------------------------------------------------------
_MESES = ["jan", "fev", "mar", "abr", "mai", "jun",
          "jul", "ago", "set", "out", "nov", "dez"]
_FONTES = {"supabase": "Supabase conectado", "db": "Supabase conectado",
           "postgres": "Supabase conectado", "excel": "Bases Excel locais",
           "mock": "Dados de exemplo"}

hoje = config.data_referencia()
_fonte_rotulo = _FONTES.get(data_source._fonte(), data_source._fonte())
st.markdown(
    f'<div class="souq-header">'
    f'<div><span class="logo">SOUQ</span>'
    f'<span class="titulo">Reabastecimento</span></div>'
    f'<div class="meta">Referência <b>{hoje.day:02d} {_MESES[hoje.month - 1]} {hoje.year}</b>'
    f'<span class="dot"></span>{_fonte_rotulo}</div>'
    f'</div>', unsafe_allow_html=True)


# --- Dados / resultado (mesma lógica de antes) ------------------------------
@st.cache_data(show_spinner="Carregando dados...")
def _carregar(hoje_iso: str):
    return carregar_dados()


@st.cache_data(show_spinner="Calculando sugestões...")
def _resultado(hoje_iso: str, semanas_min: int, max_lojas: int, janela: int,
               nao_doam: tuple = (), nao_recebem: tuple = ()):
    dados = _carregar(hoje_iso)
    res = engine.calcular(dados, config.data_referencia(),
                          semanas_min=semanas_min, max_lojas=max_lojas, janela_dias=janela,
                          nao_doam=set(nao_doam), nao_recebem=set(nao_recebem))
    # Potencial SEM o teto de lojas por doadora (indicador % Cobertura).
    res["potencial"] = engine.gerar_sugestoes(
        res["necessidades"], res["doadoras"], dados, max_lojas=10**9)
    return res


@st.cache_data(show_spinner="Calculando ruptura...")
def _rup_skus(hoje_iso: str):
    return engine.ruptura_skus(_carregar(hoje_iso))


@st.cache_data(show_spinner="Calculando cobertura...")
def _cobertura(hoje_iso: str):
    return engine.cobertura_sortimento(_carregar(hoje_iso), config.data_referencia())


@st.cache_data(show_spinner="Calculando abastecimento...")
def _abastecimento(hoje_iso: str, janela: int, reserva: int, nao_recebem: tuple = ()):
    return engine.calcular_abastecimento(
        _carregar(hoje_iso), config.data_referencia(), janela_dias=janela,
        reserva=reserva, nao_recebem=set(nao_recebem))


@st.cache_data(show_spinner="Calculando alertas...")
def _alerta_cd(hoje_iso: str):
    return engine.alerta_parado_cd(_carregar(hoje_iso), config.data_referencia())


dados = _carregar(hoje.isoformat())


# --- Helpers de exibição ----------------------------------------------------
def _fmt(n) -> str:
    """1852 -> '1.852' (milhar pt-BR)."""
    return f"{int(n):,}".replace(",", ".")


def _pct(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def _sem(x) -> str:
    """Semanas de cobertura: 12.3 -> '12,3 sem'."""
    return "—" if pd.isna(x) else f"{float(x):.1f} sem".replace(".", ",")


def card(alvo, label: str, valor: str, contexto: str = "", cor: str | None = None) -> None:
    alvo.markdown(
        f'<div class="card"><div class="card-l">{label}</div>'
        f'<div class="card-v" style="color:{cor or COR["texto"]}">{valor}</div>'
        f'<div class="card-c">{contexto}</div></div>', unsafe_allow_html=True)


def _opcoes(df, col):
    if col not in df.columns:
        return []
    if col == "colecao":
        return config.colecoes_ordenadas(df[col])
    return sorted(x for x in df[col].dropna().unique() if str(x).strip())


def _aplica(df, filtros: dict):
    for col, sel in filtros.items():
        if sel and col in df.columns:
            df = df[df[col].isin(sel)]
    return df


def _linha_filtros(df, dims: list[tuple[str, str]], prefixo: str) -> dict:
    """Multiselects compactos numa única linha (label colapsado + placeholder)."""
    cols = st.columns(len(dims))
    filtros = {}
    for (col, rotulo), c in zip(dims, cols):
        filtros[col] = c.multiselect(
            rotulo, _opcoes(df, col), key=f"{prefixo}_{col}",
            label_visibility="collapsed", placeholder=rotulo)
    return filtros


def _limpar_filtros(prefixo: str, dims: list[tuple[str, str]]) -> None:
    for col, _ in dims:
        st.session_state[f"{prefixo}_{col}"] = []


def _rotulo_colecao(c) -> str:
    """'INVERNO 2026' -> 'Inverno 26'."""
    t = str(c).title()
    return _re.sub(r"20(\d{2})", r"\1", t)


def _tamanho_de(df):
    """Série 'tamanho' casada por sku_filho (fallback: o próprio SKU)."""
    prod = dados["produtos"]
    if "tamanho" in prod.columns and "sku_filho" in df.columns:
        tam = prod[["sku_filho", "tamanho"]].drop_duplicates("sku_filho")
        return df.merge(tam, on="sku_filho", how="left")["tamanho"].fillna("—").values
    return df.get("sku_filho", pd.Series(dtype=str)).values


def _tabela_html(df: pd.DataFrame, altura: int = 400, fmt: dict | None = None,
                 css: dict | None = None, max_linhas: int = 1500) -> str:
    """Tabela HTML com header fixo azul escuro (st.dataframe não permite fonte
    branca no cabeçalho — o texto vem do tema, sem opção própria).

    fmt: {coluna: fn(valor)->str} formata o texto; css: {coluna: fn(valor)->css}
    devolve estilo inline da célula. Renderiza até max_linhas (aviso no rodapé).
    """
    fmt, css = fmt or {}, css or {}
    cols = list(df.columns)
    ths = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)
    linhas = []
    for row in df.head(max_linhas).itertuples(index=False):
        tds = []
        for c, val in zip(cols, row):
            txt = fmt[c](val) if c in fmt else ("" if val is None else str(val))
            estilo = css[c](val) if c in css else ""
            estilo = f" style='{estilo}'" if estilo else ""
            tds.append(f"<td{estilo}>{_html.escape(txt)}</td>")
        linhas.append("<tr>" + "".join(tds) + "</tr>")
    aviso = ""
    if len(df) > max_linhas:
        aviso = (f"<div class='tb-aviso'>Mostrando as primeiras {_fmt(max_linhas)} "
                 f"de {_fmt(len(df))} linhas — refine os filtros ou exporte o arquivo "
                 "completo.</div>")
    return (f"<div class='tb-wrap' style='max-height:{altura}px'><table class='tb'>"
            f"<thead><tr>{ths}</tr></thead><tbody>{''.join(linhas)}</tbody>"
            f"</table></div>{aviso}")


_DIR = "text-align:right"
_MONO = "font-family:'IBM Plex Mono',monospace;font-size:11px"


def _excel_bytes(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        for nome, df in frames.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()


def _estilo_barras(chart: alt.Chart) -> alt.Chart:
    return (chart
            .configure(font="IBM Plex Sans")
            .configure_view(strokeWidth=0)
            .configure_axis(grid=False, domain=False, ticks=False,
                            labelColor=COR["texto"], labelFontSize=12))


_SEM_SOUQ = _re.compile(r"^Souq\s+", flags=_re.IGNORECASE)

NEC_RENOME = {"loja": "Loja", "linha": "Linha", "grupo": "Grupo", "subgrupo": "Subgrupo",
              "colecao": "Coleção", "status": "Status", "sku_pai": "SKU pai",
              "sku_filho": "SKU filho", "descricao": "Descrição",
              "prev_4sem": "Prev. 4 sem (pç)", "cobertura_pai": "Cobertura pai (sem)",
              "score": "Score", "qtd_sugerida": "Qtd sugerida"}
DOA_RENOME = {"loja": "Loja", "sku_filho": "SKU filho", "qtd_disp": "Qtd disponível",
              "dias_sem_venda": "Pai sem venda (dias)", "dias_em_loja": "Em loja (dias)"}
SUG_RENOME = {"loja_doadora": "Loja doadora", "loja_receptora": "Loja receptora",
              "linha": "Linha", "grupo": "Grupo", "subgrupo": "Subgrupo",
              "colecao": "Coleção", "status": "Status", "sku_pai": "SKU pai",
              "sku_filho": "SKU filho", "tamanho": "Tamanho", "qtd": "Qtd",
              "grade_quebrada": "Grade quebrada", "score_receptora": "Score",
              "dias_parado_doadora": "Pai parado (dias)"}
ABAST_RENOME = {"loja_receptora": "Loja receptora", "linha": "Linha", "grupo": "Grupo",
                "subgrupo": "Subgrupo", "colecao": "Coleção", "status": "Status",
                "sku_pai": "SKU pai", "sku_filho": "SKU filho", "tamanho": "Tamanho",
                "qtd": "Qtd", "introducao": "Introdução", "parcial": "Parcial",
                "score_receptora": "Score"}
ALERTA_RENOME = {"linha": "Linha", "grupo": "Grupo", "subgrupo": "Subgrupo",
                 "colecao": "Coleção", "status": "Status", "sku_pai": "SKU pai",
                 "sku_filho": "SKU filho", "descricao": "Descrição",
                 "tamanho": "Tamanho", "qtd_cd": "Qtd CD", "dt_envio": "Dt. envio",
                 "dias_desde_envio": "Dias desde envio"}
ADER_RENOME = {"loja_doadora": "Loja doadora", "loja_receptora": "Loja receptora",
               "sku_pai": "SKU pai", "tamanho": "Tamanho", "sku_filho": "SKU filho",
               "qtd": "Qtd", "data": "Data", "nao_saiu": "Na doadora",
               "virou_venda": "Venda doadora", "transferido": "Transferido",
               "transito_receptora": "Trânsito p/ receptora",
               "estoque_receptora": "Estoque receptora",
               "classificacao": "Classificação"}

FILTROS_SUG = [("linha", "Linha"), ("grupo", "Grupo"), ("subgrupo", "Subgrupo"),
               ("colecao", "Coleção"), ("status", "Status"),
               ("loja_receptora", "Loja receptora")]
FILTROS_DIM = [("linha", "Linha"), ("grupo", "Grupo"), ("subgrupo", "Subgrupo"),
               ("colecao", "Coleção"), ("status", "Status")]

_pop = st.popover if hasattr(st, "popover") else st.expander

tab_sug, tab_cd, tab_rup, tab_ve, tab_alertas = st.tabs(
    ["Sugestões", "Abastecimento CD", "Ruptura e Cobertura", "Vendas × Estoque",
     "Alertas"])

# ---------------------------------------------------------------------------
with tab_sug:
    st.markdown('<div class="pg-titulo">Sugestões de transferência</div>'
                '<div class="pg-sub">Lojas doadoras com peças paradas → '
                'lojas receptoras com ruptura.</div>', unsafe_allow_html=True)

    # Parâmetros: chips somente-leitura + popover de edição.
    c_chips, c_edit = st.columns([4.2, 1])
    with c_edit:
        with _pop("Editar parâmetros"):
            semanas_min = st.number_input(
                "Semanas mín. sem venda do SKU pai (doadora)", min_value=1, max_value=12,
                value=config.SEMANAS_SEM_VENDA_MIN,
                help="A loja só doa o item se o SKU PAI está sem venda nela há pelo "
                     "menos N semanas (a doação continua a nível de SKU filho).")
            max_lojas = st.number_input(
                "Máx. lojas atendidas por doadora", min_value=1, max_value=20,
                value=config.MAX_LOJAS_POR_DOADORA)
            janela = st.number_input(
                "Janela de vendas (dias)", min_value=15, max_value=365,
                value=config.JANELA_VENDAS_DIAS,
                help="Janela usada para medir a venda histórica do SKU pai.")
            lojas_exc = sorted(dados["estoque_loja"]["loja"].dropna().unique())
            _cfg_nd = {config.norm_loja(x) for x in config.LOJAS_NAO_DOAM}
            _cfg_nr = {config.norm_loja(x) for x in config.LOJAS_NAO_RECEBEM}
            nao_doam = st.multiselect(
                "Exceções: lojas que NÃO doam", lojas_exc,
                default=[l for l in lojas_exc if config.norm_loja(l) in _cfg_nd])
            nao_recebem = st.multiselect(
                "Exceções: lojas que NÃO recebem", lojas_exc,
                default=[l for l in lojas_exc if config.norm_loja(l) in _cfg_nr])
    chips = (f'<span class="chip">Pai sem venda ≥<b>{semanas_min} sem</b></span>'
             f'<span class="chip">Máx. por doadora<b>{max_lojas} lojas</b></span>'
             f'<span class="chip">Janela<b>{janela} dias</b></span>')
    if nao_doam:
        chips += f'<span class="chip">Não doam<b>{len(nao_doam)}</b></span>'
    if nao_recebem:
        chips += f'<span class="chip">Não recebem<b>{len(nao_recebem)}</b></span>'
    c_chips.markdown(f'<div class="chips">{chips}</div>', unsafe_allow_html=True)

    res = _resultado(hoje.isoformat(), semanas_min, max_lojas, janela,
                     tuple(nao_doam), tuple(nao_recebem))
    nec, doa, sug, pot = res["necessidades"], res["doadoras"], res["sugestoes"], res["potencial"]

    # Cards (preenchidos após os filtros, para refletirem a seleção).
    k1, k2, k3, k4 = st.columns(4)
    card(k1, "Rupturas candidatas", _fmt(len(nec)), "grades incompletas na rede")
    card(k2, "Pares doadores elegíveis", _fmt(len(doa)), "combinações loja × SKU possíveis")
    ph_sug, ph_cob = k3.empty(), k4.empty()

    st.write("")
    if sug.empty:
        card(ph_sug, "Transferências sugeridas", "0", "após limites e score", COR["acento"])
        card(ph_cob, "% Cobertura da regra", "—", "sem sugestões para comparar")
        st.info("Nenhuma transferência sugerida com os parâmetros atuais.")
    else:
        filtros = _linha_filtros(sug, FILTROS_SUG, "fs")
        v = _aplica(sug, filtros)
        vp = _aplica(pot, filtros)
        ativo = any(filtros.values())

        card(ph_sug, "Transferências sugeridas", _fmt(len(v)),
             f"de {_fmt(len(sug))} · filtros ativos" if ativo else "após limites e score",
             COR["acento"])

        # % Cobertura: peças sugeridas COM o teto de lojas por doadora sobre o
        # potencial SEM o teto (ambos com os filtros aplicados).
        pecas, pecas_pot = int(v["qtd"].sum()), int(vp["qtd"].sum())
        cob_pct = 100.0 * pecas / pecas_pot if pecas_pot else 100.0
        card(ph_cob, "% Cobertura da regra", _pct(cob_pct),
             f"{_fmt(pecas)} de {_fmt(pecas_pot)} peças sem o teto de {max_lojas} lojas")

        # Tabela de exibição: colunas legíveis, Produto composto, tamanho no
        # lugar do sku_filho (o CSV/Excel mantém o SKU).
        exib = v.copy()
        exib["tamanho"] = _tamanho_de(v)
        disp = pd.DataFrame({
            "Loja doadora": exib["loja_doadora"],
            "Loja receptora": "→ " + exib["loja_receptora"].astype(str),
            "Produto": exib["subgrupo"].astype(str).str.title() + " · "
                       + exib["colecao"].map(_rotulo_colecao),
            "SKU pai": exib["sku_pai"],
            "Tamanho": exib["tamanho"],
            "Qtd": exib["qtd"].astype(int),
            "Grade": exib["grade_quebrada"].map(
                lambda s: "GRADE QUEBRADA" if s == "Sim" else ""),
            "Score": exib["score_receptora"].astype(float),
            "Pai parado (dias)": exib["dias_parado_doadora"].astype(int),
        })
        tabela = _tabela_html(
            disp, altura=400,
            fmt={"Score": lambda x: f"{x:.1f}", "Qtd": lambda x: str(int(x))},
            css={
                "Score": lambda _: f"color:{COR['acento']};font-weight:600;{_DIR}",
                "Qtd": lambda _: _DIR,
                "Pai parado (dias)": lambda x: (
                    f"color:{COR['alerta']};font-weight:600;{_DIR}" if x >= 60 else _DIR),
                "Grade": lambda x: (f"color:{COR['alerta']};font-weight:700;"
                                    "font-size:10px;letter-spacing:0.04em") if x else "",
                "SKU pai": lambda _: _MONO,
                "Tamanho": lambda _: "text-align:center",
            })

        c_conta, c_limpa, c_csv = st.columns([4.6, 1.1, 1.3])
        c_conta.markdown(f'<div class="conta">{_fmt(len(v))} de {_fmt(len(sug))} '
                         'sugestões</div>', unsafe_allow_html=True)
        if ativo:
            c_limpa.button("Limpar filtros", on_click=_limpar_filtros,
                           args=("fs", FILTROS_SUG), use_container_width=True)
        csv = (exib.rename(columns=SUG_RENOME)
               .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        c_csv.download_button("Exportar CSV", data=csv, file_name="sugestoes.csv",
                              mime="text/csv", use_container_width=True, type="primary")

        st.markdown(tabela, unsafe_allow_html=True)
        st.caption("Limites por SKU filho: Home até 10 · Acessórios até 4 · Roupa até 2 — "
                   "grade quebrada envia todo o estoque do tamanho.")

        st.download_button(
            "Baixar Excel completo (sugestões + necessidades + doadoras)",
            data=_excel_bytes({"sugestoes": sug, "necessidades": nec, "doadoras": doa}),
            file_name="remanejamento.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    _f1 = lambda x: "—" if pd.isna(x) else f"{float(x):.1f}"  # noqa: E731
    with st.expander("Ver rupturas candidatas"):
        st.markdown(_tabela_html(
            nec.rename(columns=NEC_RENOME), altura=360, max_linhas=500,
            fmt={"Prev. 4 sem (pç)": _f1, "Cobertura pai (sem)": _f1, "Score": _f1},
            css={"Score": lambda _: _DIR, "Prev. 4 sem (pç)": lambda _: _DIR,
                 "Cobertura pai (sem)": lambda _: _DIR, "Qtd sugerida": lambda _: _DIR,
                 "SKU pai": lambda _: _MONO, "SKU filho": lambda _: _MONO}),
            unsafe_allow_html=True)
    with st.expander("Ver pares doadores elegíveis"):
        st.markdown(_tabela_html(
            doa.rename(columns=DOA_RENOME), altura=360, max_linhas=500,
            fmt={"Em loja (dias)": _f1},
            css={"Qtd disponível": lambda _: _DIR, "Sem venda (dias)": lambda _: _DIR,
                 "Em loja (dias)": lambda _: _DIR, "SKU filho": lambda _: _MONO}),
            unsafe_allow_html=True)

# ---------------------------------------------------------------------------
with tab_cd:
    st.markdown('<div class="pg-titulo">Abastecimento a partir do CD</div>'
                '<div class="pg-sub">CD → lojas com ruptura que vendem o SKU pai. '
                'O remanejamento entre lojas cobre apenas o que o CD não tem.</div>',
                unsafe_allow_html=True)

    ca_chips, ca_edit = st.columns([4.2, 1])
    with ca_edit:
        with _pop("Editar parâmetros"):
            reserva_cd = st.number_input(
                "Reserva por SKU no CD (peças)", min_value=0, max_value=999,
                value=config.RESERVA_CD_PADRAO,
                help="Peças mantidas no CD por SKU (e-commerce/atacado). "
                     "0 = distribuir tudo.")
    chips_cd = (f'<span class="chip">Reserva CD<b>{reserva_cd} pç/SKU</b></span>'
                f'<span class="chip">Janela<b>{janela} dias</b></span>')
    if nao_recebem:
        chips_cd += f'<span class="chip">Não recebem<b>{len(nao_recebem)}</b></span>'
    ca_chips.markdown(f'<div class="chips">{chips_cd}</div>', unsafe_allow_html=True)

    ab = _abastecimento(hoje.isoformat(), janela, int(reserva_cd), tuple(nao_recebem))
    nec_cd, abast, sobra_cd = ab["necessidades_cd"], ab["abastecimento"], ab["sobra_cd"]

    a1, a2, a3, a4 = st.columns(4)
    skus_eleg = set(nec_cd["sku_filho"]) if not nec_cd.empty else set()
    card(a1, "SKUs elegíveis no CD", _fmt(len(skus_eleg)),
         "com estoque no CD e ruptura em loja")
    pecas_eleg = int(sobra_cd.loc[sobra_cd["sku_filho"].isin(skus_eleg), "qtd"].sum()) \
        if skus_eleg else 0
    card(a2, "Peças no CD (elegíveis)", _fmt(pecas_eleg), "estoque dos SKUs com demanda")
    ph_ab, ph_at = a3.empty(), a4.empty()

    st.write("")
    if abast.empty:
        card(ph_ab, "Peças a distribuir", "0", "sem cruzamento demanda × estoque",
             COR["acento"])
        card(ph_at, "% da demanda atendida", "—", "sem distribuição para comparar")
        st.info("Nenhuma distribuição sugerida com os parâmetros atuais.")
    else:
        filtros_cd = _linha_filtros(abast, FILTROS_SUG, "fa")
        va = _aplica(abast, filtros_cd)
        ativo_cd = any(filtros_cd.values())

        # Demanda correspondente (necessidades do CD) sob os mesmos filtros.
        filtros_nec = {("loja" if c == "loja_receptora" else c): s
                       for c, s in filtros_cd.items()}
        na = _aplica(nec_cd, filtros_nec)
        pecas_ab = int(va["qtd"].sum())
        demanda = int(na["qtd_sugerida"].sum()) if len(na) else 0
        card(ph_ab, "Peças a distribuir", _fmt(pecas_ab),
             f"{_fmt(len(va))} envios" + (" · filtros ativos" if ativo_cd else ""),
             COR["acento"])
        card(ph_at, "% da demanda atendida",
             _pct(100.0 * pecas_ab / demanda) if demanda else "—",
             f"{_fmt(pecas_ab)} de {_fmt(demanda)} peças pedidas")

        exib_a = va.copy()
        exib_a["tamanho"] = _tamanho_de(va)
        obs = [" · ".join(f for f in (("INTRODUÇÃO" if i == "Sim" else ""),
                                      ("PARCIAL" if p == "Sim" else "")) if f)
               for i, p in zip(exib_a["introducao"], exib_a["parcial"])]
        disp_a = pd.DataFrame({
            "Loja receptora": "→ " + exib_a["loja_receptora"].astype(str),
            "Produto": exib_a["subgrupo"].astype(str).str.title() + " · "
                       + exib_a["colecao"].map(_rotulo_colecao),
            "SKU pai": exib_a["sku_pai"],
            "Tamanho": exib_a["tamanho"],
            "Qtd": exib_a["qtd"].astype(int),
            "Obs": obs,
            "Score": exib_a["score_receptora"].astype(float),
        })
        tabela_a = _tabela_html(
            disp_a, altura=400,
            fmt={"Score": lambda x: f"{x:.1f}", "Qtd": lambda x: str(int(x))},
            css={
                "Score": lambda _: f"color:{COR['acento']};font-weight:600;{_DIR}",
                "Qtd": lambda _: _DIR,
                "Obs": lambda x: (
                    (f"color:{COR['alerta']};" if "PARCIAL" in str(x)
                     else f"color:{COR['acento']};")
                    + "font-weight:700;font-size:10px;letter-spacing:0.04em") if x else "",
                "SKU pai": lambda _: _MONO,
                "Tamanho": lambda _: "text-align:center",
            })

        ca_conta, ca_limpa, ca_csv = st.columns([4.6, 1.1, 1.3])
        ca_conta.markdown(f'<div class="conta">{_fmt(len(va))} de {_fmt(len(abast))} '
                          'envios</div>', unsafe_allow_html=True)
        if ativo_cd:
            ca_limpa.button("Limpar filtros", on_click=_limpar_filtros,
                            args=("fa", FILTROS_SUG), use_container_width=True,
                            key="limpa_fa")
        csv_a = (exib_a.rename(columns=ABAST_RENOME)
                 .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        ca_csv.download_button("Exportar CSV", data=csv_a, file_name="abastecimento.csv",
                               mime="text/csv", use_container_width=True,
                               type="primary", key="csv_fa")

        st.markdown(tabela_a, unsafe_allow_html=True)
        st.caption("Prioridade por score (demanda prevista ÷ cobertura). "
                   "INTRODUÇÃO = loja sem nenhum filho do pai (re-clusterização via CD); "
                   "PARCIAL = estoque do CD não cobre o pedido. "
                   "Limites por SKU filho: Home 10 · Acessórios 4 · Roupa 2.")

        with st.expander("Carga por loja receptora"):
            resumo_cd = (va.groupby("loja_receptora")
                         .agg(skus=("sku_filho", "nunique"), pecas=("qtd", "sum"))
                         .reset_index().sort_values("pecas", ascending=False)
                         .rename(columns={"loja_receptora": "Loja", "skus": "SKUs",
                                          "pecas": "Peças"}))
            st.markdown(_tabela_html(
                resumo_cd, altura=300,
                css={"Peças": lambda _: _DIR, "SKUs": lambda _: _DIR}),
                unsafe_allow_html=True)

        st.download_button(
            "Baixar Excel completo (abastecimento + necessidades + sobra CD)",
            data=_excel_bytes({"abastecimento": abast, "necessidades_cd": nec_cd,
                               "sobra_cd": sobra_cd}),
            file_name="abastecimento_cd.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="xlsx_fa")

    with st.expander("Ver sobra no CD (após a distribuição)"):
        sob = sobra_cd.rename(columns={
            "linha": "Linha", "subgrupo": "Subgrupo", "colecao": "Coleção",
            "status": "Status", "sku_pai": "SKU pai", "sku_filho": "SKU filho",
            "descricao": "Descrição", "qtd": "Estoque CD", "enviado": "Enviado",
            "sobra": "Sobra"})
        ordem = [c for c in ("Linha", "Subgrupo", "Coleção", "Status", "SKU pai",
                             "SKU filho", "Descrição", "Estoque CD", "Enviado",
                             "Sobra") if c in sob.columns]
        st.markdown(_tabela_html(
            sob[ordem], altura=360, max_linhas=500,
            css={"Estoque CD": lambda _: _DIR, "Enviado": lambda _: _DIR,
                 "Sobra": lambda _: _DIR, "SKU pai": lambda _: _MONO,
                 "SKU filho": lambda _: _MONO}),
            unsafe_allow_html=True)

# ---------------------------------------------------------------------------
with tab_rup:
    st.markdown('<div class="pg-titulo">Ruptura e Cobertura</div>'
                '<div class="pg-sub">Grades incompletas e semanas de estoque '
                'por loja e subgrupo.</div>',
                unsafe_allow_html=True)

    rs = _rup_skus(hoje.isoformat())
    if rs.empty:
        st.info("Sem dados de ruptura.")
    else:
        cob = _cobertura(hoje.isoformat())
        filtros_r = _linha_filtros(rs, FILTROS_DIM, "fr")
        rf = _aplica(rs, filtros_r)

        tot = max(int(rf["sku_filho"].count()), 1)
        p_loja = 100 * rf["ruptura"].sum() / tot
        p_trans = 100 * rf["rup_sem_transito"].sum() / tot
        p_cd = 100 * rf["soldout_cd"].sum() / tot
        cob_loja = engine.cobertura_agregada(rf, cob, "loja")
        prev_tot = float(cob_loja["prev_sem"].sum()) if not cob_loja.empty else 0.0
        cob_geral = cob_loja["estoque"].sum() / prev_tot if prev_tot > 0 else float("nan")
        m1, m2, m3, m4 = st.columns(4)
        card(m1, "% Ruptura loja", _pct(p_loja), "estoque físico da loja")
        card(m2, "% Ruptura loja + trânsito", _pct(p_trans), "considerando peças a caminho")
        card(m3, "% Sold out CD", _pct(p_cd), "sem reposição disponível no CD")
        card(m4, "Cobertura média", _sem(cob_geral),
             "estoque ÷ venda semanal prevista (full price)")
        st.write("")

        with st.container(border=True):
            c_rup, c_cob = st.columns(2, gap="large")

            with c_rup:
                t1, t2 = st.columns([2.6, 1.4])
                t1.markdown('<div class="panel-titulo">% de ruptura por loja</div>',
                            unsafe_allow_html=True)
                t2.markdown('<div class="panel-nota">maior → menor</div>', unsafe_allow_html=True)

                # Pré-ordenado no DataFrame (sort=None preserva a ordem no gráfico).
                d = (engine.ruptura_por_loja(rf)
                     .sort_values("%Ruptura Loja", ascending=False).reset_index(drop=True))
                d["loja_curta"] = d["loja"].astype(str).str.replace(_SEM_SOUQ, "", regex=True)
                rot_acima = f"Acima da média ({_pct(p_loja)})"
                d["situacao"] = d["%Ruptura Loja"].gt(p_loja).map(
                    {True: rot_acima, False: "Na média ou abaixo"})
                d["rotulo"] = d["%Ruptura Loja"].map(_pct)

                base = alt.Chart(d).encode(
                    y=alt.Y("loja_curta:N", title=None, sort=None,
                            axis=alt.Axis(labelLimit=220)))
                barras = base.mark_bar(size=13, cornerRadiusEnd=2).encode(
                    x=alt.X("%Ruptura Loja:Q", axis=None,
                            scale=alt.Scale(domain=[0, float(d["%Ruptura Loja"].max()) * 1.18])),
                    color=alt.Color("situacao:N",
                                    scale=alt.Scale(domain=[rot_acima, "Na média ou abaixo"],
                                                    range=[COR["alerta"], COR["barra"]]),
                                    legend=alt.Legend(orient="top", title=None,
                                                      labelColor=COR["texto2"])))
                rotulos = base.mark_text(align="left", dx=5, fontSize=11,
                                         color=COR["texto"]).encode(
                    x=alt.X("%Ruptura Loja:Q"), text="rotulo:N")
                st.altair_chart(_estilo_barras((barras + rotulos).properties(
                    height=26 * max(len(d), 1) + 46)), use_container_width=True)

            with c_cob:
                t3, t4 = st.columns([2.6, 1.4])
                t3.markdown('<div class="panel-titulo">Cobertura por loja</div>',
                            unsafe_allow_html=True)
                t4.markdown('<div class="panel-nota">semanas · menor → maior</div>',
                            unsafe_allow_html=True)

                dc = (cob_loja.dropna(subset=["cobertura_sem"])
                      .sort_values("cobertura_sem").reset_index(drop=True))
                if dc.empty:
                    st.caption("Sem previsão de venda para calcular cobertura no filtro atual.")
                else:
                    dc["loja_curta"] = dc["loja"].astype(str).str.replace(_SEM_SOUQ, "", regex=True)
                    horiz = config.COBERTURA_HORIZONTE_SEMANAS
                    rot_baixa = f"Abaixo de {horiz} sem"
                    rot_ok = f"{horiz} sem ou mais"
                    dc["situacao"] = dc["cobertura_sem"].lt(horiz).map(
                        {True: rot_baixa, False: rot_ok})
                    dc["rotulo"] = dc["cobertura_sem"].map(_sem)

                    base_c = alt.Chart(dc).encode(
                        y=alt.Y("loja_curta:N", title=None, sort=None,
                                axis=alt.Axis(labelLimit=220)))
                    barras_c = base_c.mark_bar(size=13, cornerRadiusEnd=2).encode(
                        x=alt.X("cobertura_sem:Q", axis=None,
                                scale=alt.Scale(domain=[0, float(dc["cobertura_sem"].max()) * 1.18])),
                        color=alt.Color("situacao:N",
                                        scale=alt.Scale(domain=[rot_baixa, rot_ok],
                                                        range=[COR["alerta"], COR["acento"]]),
                                        legend=alt.Legend(orient="top", title=None,
                                                          labelColor=COR["texto2"])))
                    rot_c = base_c.mark_text(align="left", dx=5, fontSize=11,
                                             color=COR["texto"]).encode(
                        x=alt.X("cobertura_sem:Q"), text="rotulo:N")
                    st.altair_chart(_estilo_barras((barras_c + rot_c).properties(
                        height=26 * max(len(dc), 1) + 46)), use_container_width=True)

        st.write("")
        with st.container(border=True):
            st.markdown('<div class="panel-titulo">Ruptura e cobertura por subgrupo</div>',
                        unsafe_allow_html=True)
            lojas_op = ["Todas as lojas"] + sorted(rf["loja"].unique())
            loja_sel = st.selectbox("Loja", lojas_op, label_visibility="collapsed")
            rsub = rf if loja_sel == "Todas as lojas" else rf[rf["loja"] == loja_sel]
            # Normaliza espaços (evita subgrupo duplicado, ex.: 'JAQUETA ').
            rsub = rsub.assign(subgrupo=rsub["subgrupo"].astype(str).str.strip())

            c_rs, c_cs = st.columns(2, gap="large")
            with c_rs:
                st.caption("% de ruptura — maiores primeiro")
                por_sub = engine.ruptura_por_subgrupo(rsub)
                por_sub = por_sub[por_sub["%Ruptura Loja"] > 0].head(25)
                if por_sub.empty:
                    st.caption("Sem ruptura nos subgrupos do filtro atual.")
                else:
                    ds = por_sub.sort_values("%Ruptura Loja", ascending=False).copy()
                    ds["nome"] = ds["subgrupo"].astype(str).str.title()
                    ds["rotulo"] = ds["%Ruptura Loja"].map(_pct)
                    base_s = alt.Chart(ds).encode(
                        y=alt.Y("nome:N", title=None, sort=None,
                                axis=alt.Axis(labelLimit=220)))
                    barras_s = base_s.mark_bar(size=12, cornerRadiusEnd=2,
                                               color=COR["barra"]).encode(
                        x=alt.X("%Ruptura Loja:Q", axis=None,
                                scale=alt.Scale(domain=[0, float(ds["%Ruptura Loja"].max()) * 1.18])))
                    rot_s = base_s.mark_text(align="left", dx=5, fontSize=11,
                                             color=COR["texto"]).encode(
                        x=alt.X("%Ruptura Loja:Q"), text="rotulo:N")
                    st.altair_chart(_estilo_barras((barras_s + rot_s).properties(
                        height=24 * max(len(ds), 1) + 20)), use_container_width=True)

            with c_cs:
                st.caption("Cobertura (semanas) — menores primeiro")
                cob_sub = engine.cobertura_agregada(rsub, cob, "subgrupo")
                cob_sub = (cob_sub.dropna(subset=["cobertura_sem"])
                           .sort_values("cobertura_sem").head(25))
                if cob_sub.empty:
                    st.caption("Sem previsão de venda para calcular cobertura no filtro atual.")
                else:
                    dcs = cob_sub.copy()
                    dcs["nome"] = dcs["subgrupo"].astype(str).str.title()
                    dcs["rotulo"] = dcs["cobertura_sem"].map(_sem)
                    horiz = config.COBERTURA_HORIZONTE_SEMANAS
                    dcs["cor"] = dcs["cobertura_sem"].lt(horiz).map(
                        {True: COR["alerta"], False: COR["acento"]})
                    base_cs = alt.Chart(dcs).encode(
                        y=alt.Y("nome:N", title=None, sort=None,
                                axis=alt.Axis(labelLimit=220)))
                    barras_cs = base_cs.mark_bar(size=12, cornerRadiusEnd=2).encode(
                        x=alt.X("cobertura_sem:Q", axis=None,
                                scale=alt.Scale(domain=[0, float(dcs["cobertura_sem"].max()) * 1.18])),
                        color=alt.Color("cor:N", scale=None))
                    rot_cs = base_cs.mark_text(align="left", dx=5, fontSize=11,
                                               color=COR["texto"]).encode(
                        x=alt.X("cobertura_sem:Q"), text="rotulo:N")
                    st.altair_chart(_estilo_barras((barras_cs + rot_cs).properties(
                        height=24 * max(len(dcs), 1) + 20)), use_container_width=True)

# ---------------------------------------------------------------------------
with tab_ve:
    st.markdown('<div class="pg-titulo">Vendas × Estoque por loja</div>',
                unsafe_allow_html=True)

    cols_ve = st.columns([1, 1, 1, 1, 1, 0.8])
    op = painel.opcoes_filtro(dados)
    filtros_ve = {}
    for (col, rotulo), c in zip(FILTROS_DIM, cols_ve[:5]):
        filtros_ve[col] = c.multiselect(rotulo, op.get(col, []), key=f"fv_{col}",
                                        label_visibility="collapsed", placeholder=rotulo)
    top_n = cols_ve[5].number_input("Qtd. de SKUs pai", min_value=10, max_value=60,
                                    value=25, step=5, label_visibility="collapsed",
                                    help="Quantos SKUs pai mostrar (top por venda).")
    st.markdown(f'<div class="pg-sub">Top {top_n} SKUs pai por venda. '
                'Cor = intensidade de venda; número grande = vendas (QLF), '
                'abaixo = estoque.</div>', unsafe_allow_html=True)

    html = painel.html_painel(dados, hoje, janela_dias=janela,
                              filtros=filtros_ve, top_n=top_n)
    if html is None:
        st.info("Sem dados para o filtro selecionado.")
    else:
        st.markdown(html, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
with tab_alertas:
    st.markdown('<div class="pg-titulo">Alertas</div>'
                '<div class="pg-sub">Peças paradas no CD e conferência dos '
                'remanejamentos executados.</div>', unsafe_allow_html=True)

    # --- SKU filho parado no CD --------------------------------------------
    st.markdown(f'<div style="font-size:16px;font-weight:600;color:{COR["texto"]};'
                'margin:10px 0 2px">SKU filho parado no CD</div>',
                unsafe_allow_html=True)
    st.caption("SKU filho com estoque no CD, ZERO peças em loja e pai já enviado "
               "(dt_envio preenchida). Status monitorados: "
               + " · ".join(sorted(config.STATUS_ALERTA_CD)) + ".")

    al = _alerta_cd(hoje.isoformat())
    if dados.get("estoque_amplo") is None:
        st.info("Alerta indisponível nesta fonte: a tabela `estoque_amplo` ainda "
                "não foi publicada na nuvem (rode o publica_supabase / aguarde a "
                "carga diária).")
    elif al.empty:
        st.success("Nenhum SKU filho parado no CD pelos critérios atuais.")
    else:
        filtros_al = _linha_filtros(al, FILTROS_DIM, "fal")
        vl = _aplica(al, filtros_al)
        ativo_al = any(filtros_al.values())

        b1, b2, b3, b4 = st.columns(4)
        card(b1, "SKUs parados no CD", _fmt(vl["sku_filho"].nunique()),
             "filtros ativos" if ativo_al else "sem estoque em nenhuma loja",
             COR["alerta"])
        card(b2, "Peças paradas", _fmt(int(vl["qtd_cd"].sum())),
             "estoque no CD desses SKUs")
        card(b3, "SKUs pai afetados", _fmt(vl["sku_pai"].nunique()),
             "produtos já lançados")
        card(b4, "Dias desde envio (mediana)",
             _fmt(int(vl["dias_desde_envio"].median())) if len(vl) else "—",
             "do pai mais recente")
        st.write("")

        cl_conta, cl_limpa, cl_csv = st.columns([4.6, 1.1, 1.3])
        cl_conta.markdown(f'<div class="conta">{_fmt(len(vl))} de {_fmt(len(al))} '
                          'SKUs</div>', unsafe_allow_html=True)
        if ativo_al:
            cl_limpa.button("Limpar filtros", on_click=_limpar_filtros,
                            args=("fal", FILTROS_DIM), use_container_width=True,
                            key="limpa_fal")
        csv_al = (vl.rename(columns=ALERTA_RENOME)
                  .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        cl_csv.download_button("Exportar CSV", data=csv_al,
                               file_name="alerta_parado_cd.csv", mime="text/csv",
                               use_container_width=True, type="primary",
                               key="csv_fal")

        st.markdown(_tabela_html(
            vl.rename(columns=ALERTA_RENOME), altura=420,
            fmt={"Dt. envio": lambda d: pd.Timestamp(d).strftime("%d/%m/%Y"),
                 "Qtd CD": lambda x: _fmt(x),
                 "Dias desde envio": lambda x: _fmt(x)},
            css={"Qtd CD": lambda _: _DIR,
                 "Dias desde envio": lambda x: (
                     f"color:{COR['alerta']};font-weight:600;{_DIR}"
                     if int(x) >= 90 else _DIR),
                 "SKU pai": lambda _: _MONO, "SKU filho": lambda _: _MONO,
                 "Tamanho": lambda _: "text-align:center"}),
            unsafe_allow_html=True)

        st.download_button(
            "Baixar Excel completo (todos os SKUs parados)",
            data=_excel_bytes({"parado_cd": al.rename(columns=ALERTA_RENOME)}),
            file_name="alerta_parado_cd.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="xlsx_fal")

    # --- Aderência de remanejamento ----------------------------------------
    st.write("")
    st.markdown(f'<div style="font-size:16px;font-weight:600;color:{COR["texto"]};'
                'margin:14px 0 2px">Aderência de remanejamento</div>',
                unsafe_allow_html=True)
    st.caption("Suba o CSV do remanejamento solicitado — colunas separadas por ';': "
               "loja doadora; loja receptora; sku pai; tamanho; qtd; data "
               "(dd/mm/aaaa). Estimativa: o que ainda está na doadora não saiu; o "
               "que ela vendeu desde a data conta como venda; o restante é "
               "considerado transferido. Trânsito e estoque da receptora são "
               "evidência de chegada (o trânsito não tem data, pode ser de outro "
               "movimento).")

    arq = st.file_uploader("CSV do remanejamento", type=["csv"],
                           key="upload_aderencia")
    if arq is not None:
        try:
            cru = aderencia.ler_csv(arq.getvalue())
        except ValueError as e:
            st.error(str(e))
            cru = None
        if cru is not None:
            lojas_conhecidas = (set(dados["estoque_loja"]["loja"])
                                | set(dados["vendas"]["loja"]))
            validas, invalidas = aderencia.validar(cru, dados["produtos"],
                                                   lojas_conhecidas, hoje)
            res = aderencia.calcular(validas, dados["estoque_loja"],
                                     dados["transito"], dados["vendas"])
            k = res["kpis"]

            d1, d2, d3, d4 = st.columns(4)
            tem = k["linhas"] > 0
            card(d1, "Score de aderência", _pct(100 * k["score"]) if tem else "—",
                 "média de % peças e % SKUs",
                 (COR["acento"] if k["score"] >= 0.7 else COR["alerta"]) if tem else None)
            card(d2, "% Peças atendidas", _pct(100 * k["pct_pecas"]) if tem else "—",
                 f"{_fmt(k['pecas_transferidas'])} de "
                 f"{_fmt(k['pecas_solicitadas'])} peças")
            card(d3, "% SKUs atendidos", _pct(100 * k["pct_skus"]) if tem else "—",
                 f"{_fmt(k['linhas_atendidas'])} de {_fmt(k['linhas'])} linhas 100% "
                 "atendidas")
            card(d4, "Linhas inválidas", _fmt(len(invalidas)),
                 "ignoradas no cálculo",
                 COR["alerta"] if len(invalidas) else None)
            st.write("")

            if not res["detalhe"].empty:
                _css_classif = {
                    "Atendido": f"color:{COR['acento']};font-weight:600",
                    "Parcial": f"color:{COR['alerta']};font-weight:600",
                    "Venda na doadora": f"color:{COR['alerta']}",
                    "Não atendido": f"color:{COR['alerta']};font-weight:700",
                }
                st.markdown(_tabela_html(
                    res["detalhe"].rename(columns=ADER_RENOME), altura=420,
                    fmt={"Data": lambda d: pd.Timestamp(d).strftime("%d/%m/%Y")},
                    css={"Classificação": lambda x: _css_classif.get(str(x), ""),
                         "SKU pai": lambda _: _MONO, "SKU filho": lambda _: _MONO,
                         "Qtd": lambda _: _DIR, "Na doadora": lambda _: _DIR,
                         "Venda doadora": lambda _: _DIR,
                         "Transferido": lambda _: _DIR,
                         "Trânsito p/ receptora": lambda _: _DIR,
                         "Estoque receptora": lambda _: _DIR,
                         "Tamanho": lambda _: "text-align:center"}),
                    unsafe_allow_html=True)
                csv_det = (res["detalhe"].rename(columns=ADER_RENOME)
                           .to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"))
                st.download_button("Exportar resultado (CSV)", data=csv_det,
                                   file_name="aderencia_remanejamento.csv",
                                   mime="text/csv", type="primary", key="csv_ader")

            if not invalidas.empty:
                with st.expander(f"Linhas inválidas ({_fmt(len(invalidas))})"):
                    st.markdown(_tabela_html(invalidas, altura=300),
                                unsafe_allow_html=True)
                    csv_inv = (invalidas.to_csv(index=False, sep=";", decimal=",")
                               .encode("utf-8-sig"))
                    st.download_button("Baixar linhas inválidas", data=csv_inv,
                                       file_name="aderencia_invalidas.csv",
                                       mime="text/csv", key="csv_ader_inv")
