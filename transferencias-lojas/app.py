"""App Streamlit: sugestões de remanejamento + dashboard de ruptura + painel V×E.

Redesign visual (jul/2026): tema sóbrio (verde-petróleo/terracota), header
próprio, parâmetros em popover, cards HTML e tabelas com nomes legíveis.
A lógica de negócio (engine/cobertura/sazonalidade) não muda aqui.
"""
from __future__ import annotations

import io
import re as _re

import altair as alt
import pandas as pd
import streamlit as st

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
    "header": "#1C2B29", "cab_tabela": "#FAFAF8",
}

st.set_page_config(page_title="Remanejamento de Estoque", layout="wide",
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

/* Painéis com borda (containers) */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {COR["superficie"]}; border-color: {COR["borda"]} !important; border-radius: 10px;
}}
.panel-titulo {{ font-size: 15px; font-weight: 600; color: {COR["texto"]}; }}
.panel-nota {{ font-size: 11.5px; color: {COR["texto3"]}; text-align: right; padding-top: 2px; }}

/* Cabeçalhos de tabela do st.dataframe */
[data-testid="stDataFrame"] thead th {{
    background: {COR["cab_tabela"]}; color: {COR["texto2"]};
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em;
}}
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
    f'<span class="titulo">Remanejamento de Estoque</span></div>'
    f'<div class="meta">Referência <b>{hoje.day:02d} {_MESES[hoje.month - 1]} {hoje.year}</b>'
    f'<span class="dot"></span>{_fonte_rotulo}</div>'
    f'</div>', unsafe_allow_html=True)


# --- Dados / resultado (mesma lógica de antes) ------------------------------
@st.cache_data(show_spinner="Carregando dados...")
def _carregar(hoje_iso: str):
    return carregar_dados()


@st.cache_data(show_spinner="Calculando sugestões...")
def _resultado(hoje_iso: str, semanas_min: int, max_lojas: int, janela: int):
    dados = _carregar(hoje_iso)
    res = engine.calcular(dados, config.data_referencia(),
                          semanas_min=semanas_min, max_lojas=max_lojas, janela_dias=janela)
    # Potencial SEM o teto de lojas por doadora (indicador % Cobertura).
    res["potencial"] = engine.gerar_sugestoes(
        res["necessidades"], res["doadoras"], dados, max_lojas=10**9)
    return res


@st.cache_data(show_spinner="Calculando ruptura...")
def _rup_skus(hoje_iso: str):
    return engine.ruptura_skus(_carregar(hoje_iso))


dados = _carregar(hoje.isoformat())


# --- Helpers de exibição ----------------------------------------------------
def _fmt(n) -> str:
    """1852 -> '1.852' (milhar pt-BR)."""
    return f"{int(n):,}".replace(",", ".")


def _pct(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


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
              "dias_sem_venda": "Sem venda (dias)", "dias_em_loja": "Em loja (dias)"}
SUG_RENOME = {"loja_doadora": "Loja doadora", "loja_receptora": "Loja receptora",
              "linha": "Linha", "grupo": "Grupo", "subgrupo": "Subgrupo",
              "colecao": "Coleção", "status": "Status", "sku_pai": "SKU pai",
              "sku_filho": "SKU filho", "tamanho": "Tamanho", "qtd": "Qtd",
              "grade_quebrada": "Grade quebrada", "score_receptora": "Score",
              "dias_parado_doadora": "Parado (dias)"}

FILTROS_SUG = [("linha", "Linha"), ("grupo", "Grupo"), ("subgrupo", "Subgrupo"),
               ("colecao", "Coleção"), ("status", "Status"),
               ("loja_receptora", "Loja receptora")]
FILTROS_DIM = [("linha", "Linha"), ("grupo", "Grupo"), ("subgrupo", "Subgrupo"),
               ("colecao", "Coleção"), ("status", "Status")]

_pop = st.popover if hasattr(st, "popover") else st.expander

tab_sug, tab_rup, tab_ve = st.tabs(["Sugestões", "Ruptura", "Vendas × Estoque"])

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
                "Semanas mín. sem venda (doadora)", min_value=1, max_value=12,
                value=config.SEMANAS_SEM_VENDA_MIN,
                help="Item só pode ser retirado da loja se está parado há pelo menos N semanas.")
            max_lojas = st.number_input(
                "Máx. lojas atendidas por doadora", min_value=1, max_value=20,
                value=config.MAX_LOJAS_POR_DOADORA)
            janela = st.number_input(
                "Janela de vendas (dias)", min_value=15, max_value=365,
                value=config.JANELA_VENDAS_DIAS,
                help="Janela usada para medir a venda histórica do SKU pai.")
    c_chips.markdown(
        f'<div class="chips">'
        f'<span class="chip">Sem venda ≥<b>{semanas_min} sem</b></span>'
        f'<span class="chip">Máx. por doadora<b>{max_lojas} lojas</b></span>'
        f'<span class="chip">Janela<b>{janela} dias</b></span>'
        f'</div>', unsafe_allow_html=True)

    res = _resultado(hoje.isoformat(), semanas_min, max_lojas, janela)
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
            "Parado (dias)": exib["dias_parado_doadora"].astype(int),
        })
        sty = (disp.style
               .map(lambda _: f"color:{COR['acento']};font-weight:600", subset=["Score"])
               .map(lambda x: f"color:{COR['alerta']};font-weight:600" if x >= 60 else "",
                    subset=["Parado (dias)"])
               .map(lambda x: (f"color:{COR['alerta']};font-weight:700;"
                               "font-size:10px;letter-spacing:0.04em") if x else "",
                    subset=["Grade"])
               .format({"Score": "{:.1f}"}))

        c_conta, c_limpa, c_csv = st.columns([4.6, 1.1, 1.3])
        c_conta.markdown(f'<div class="conta">{_fmt(len(v))} de {_fmt(len(sug))} '
                         'sugestões</div>', unsafe_allow_html=True)
        if ativo:
            c_limpa.button("Limpar filtros", on_click=_limpar_filtros,
                           args=("fs", FILTROS_SUG), use_container_width=True)
        csv = (exib.rename(columns=SUG_RENOME)
               .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        c_csv.download_button("Exportar CSV", data=csv, file_name="sugestoes.csv",
                              mime="text/csv", use_container_width=True)

        st.dataframe(sty, use_container_width=True, hide_index=True, height=390)
        st.caption("Limites por SKU filho: Home até 10 · Acessórios até 4 · Roupa até 2 — "
                   "grade quebrada envia todo o estoque do tamanho.")

        st.download_button(
            "Baixar Excel completo (sugestões + necessidades + doadoras)",
            data=_excel_bytes({"sugestoes": sug, "necessidades": nec, "doadoras": doa}),
            file_name="remanejamento.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with st.expander("Ver rupturas candidatas"):
        st.dataframe(nec.rename(columns=NEC_RENOME),
                     use_container_width=True, hide_index=True)
    with st.expander("Ver pares doadores elegíveis"):
        st.dataframe(doa.rename(columns=DOA_RENOME),
                     use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
with tab_rup:
    st.markdown('<div class="pg-titulo">Ruptura</div>'
                '<div class="pg-sub">Grades incompletas por loja e subgrupo.</div>',
                unsafe_allow_html=True)

    rs = _rup_skus(hoje.isoformat())
    if rs.empty:
        st.info("Sem dados de ruptura.")
    else:
        filtros_r = _linha_filtros(rs, FILTROS_DIM, "fr")
        rf = _aplica(rs, filtros_r)

        tot = max(int(rf["sku_filho"].count()), 1)
        p_loja = 100 * rf["ruptura"].sum() / tot
        p_trans = 100 * rf["rup_sem_transito"].sum() / tot
        p_cd = 100 * rf["soldout_cd"].sum() / tot
        m1, m2, m3 = st.columns(3)
        card(m1, "% Ruptura loja", _pct(p_loja), "estoque físico da loja")
        card(m2, "% Ruptura loja + trânsito", _pct(p_trans), "considerando peças a caminho")
        card(m3, "% Sold out CD", _pct(p_cd), "sem reposição disponível no CD")
        st.write("")

        g_rank, g_carga = st.columns([3, 2])
        with g_rank, st.container(border=True):
            t1, t2 = st.columns([3, 1])
            t1.markdown('<div class="panel-titulo">Ranking de lojas por % de ruptura</div>',
                        unsafe_allow_html=True)
            t2.markdown('<div class="panel-nota">maior → menor</div>', unsafe_allow_html=True)

            por_loja = engine.ruptura_por_loja(rf)
            d = por_loja.copy()
            d["loja_curta"] = d["loja"].astype(str).str.replace(_SEM_SOUQ, "", regex=True)
            rot_acima = f"Acima da média ({_pct(p_loja)})"
            d["situacao"] = d["%Ruptura Loja"].gt(p_loja).map(
                {True: rot_acima, False: "Na média ou abaixo"})
            d["rotulo"] = d["%Ruptura Loja"].map(_pct)

            base = alt.Chart(d).encode(
                y=alt.Y("loja_curta:N", title=None,
                        sort=alt.EncodingSortField(field="%Ruptura Loja", order="descending"),
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

        with g_carga, st.container(border=True):
            st.markdown('<div class="panel-titulo">Carga por loja doadora</div>',
                        unsafe_allow_html=True)
            if sug.empty:
                st.caption("Sem sugestões na rodada atual.")
            else:
                resumo = (sug.groupby("loja_doadora")
                          .agg(lojas=("loja_receptora", "nunique"), pecas=("qtd", "sum"))
                          .reset_index().sort_values("pecas", ascending=False)
                          .rename(columns={"loja_doadora": "Loja doadora",
                                           "lojas": "Lojas atendidas", "pecas": "Peças"}))
                st.dataframe(resumo, use_container_width=True, hide_index=True, height=420)

        st.write("")
        with st.container(border=True):
            st.markdown('<div class="panel-titulo">Ruptura por subgrupo</div>',
                        unsafe_allow_html=True)
            lojas_op = ["Todas as lojas"] + sorted(rf["loja"].unique())
            loja_sel = st.selectbox("Loja", lojas_op, label_visibility="collapsed")
            rsub = rf if loja_sel == "Todas as lojas" else rf[rf["loja"] == loja_sel]
            # Normaliza espaços (evita subgrupo duplicado, ex.: 'JAQUETA ').
            rsub = rsub.assign(subgrupo=rsub["subgrupo"].astype(str).str.strip())
            por_sub = engine.ruptura_por_subgrupo(rsub)
            por_sub = por_sub[por_sub["%Ruptura Loja"] > 0].head(25)
            if por_sub.empty:
                st.caption("Sem ruptura nos subgrupos do filtro atual.")
            else:
                ds = por_sub.copy()
                ds["nome"] = ds["subgrupo"].astype(str).str.title()
                ds["rotulo"] = ds["%Ruptura Loja"].map(_pct)
                base_s = alt.Chart(ds).encode(
                    y=alt.Y("nome:N", title=None,
                            sort=alt.EncodingSortField(field="%Ruptura Loja", order="descending"),
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
