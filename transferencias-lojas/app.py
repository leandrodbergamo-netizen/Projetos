"""App Streamlit: sugestões de remanejamento + dashboard de ruptura + painel V×E."""
from __future__ import annotations

import io

import altair as alt
import pandas as pd
import streamlit as st

import config
import engine
import painel
from data_source import carregar_dados

st.set_page_config(page_title="Remanejamento entre Lojas", layout="wide")
st.title("🔁 Remanejamento de Estoque entre Lojas")

# --- Barra lateral: parâmetros de negócio ----------------------------------
st.sidebar.header("Parâmetros")
hoje = config.data_referencia()
st.sidebar.caption(f"Data de referência: **{hoje.isoformat()}**  •  Fonte: **{config.FONTE_DADOS}**")

semanas_min = st.sidebar.number_input(
    "Semanas mín. sem venda (doadora)", min_value=1, max_value=12,
    value=config.SEMANAS_SEM_VENDA_MIN,
    help="Item só pode ser retirado da loja se está parado há pelo menos N semanas.")
max_lojas = st.sidebar.number_input(
    "Máx. lojas atendidas por doadora", min_value=1, max_value=20,
    value=config.MAX_LOJAS_POR_DOADORA)
janela = st.sidebar.number_input(
    "Janela de vendas (dias)", min_value=15, max_value=365,
    value=config.JANELA_VENDAS_DIAS,
    help="Janela usada para medir a venda histórica do SKU pai.")

st.sidebar.divider()
st.sidebar.caption("**Limite de peças por grupo (SKU filho):**")
for g, lim in config.GRUPO_LIMITES.items():
    st.sidebar.caption(f"• {g}: até {lim} (grade quebrada envia tudo)")


@st.cache_data(show_spinner="Carregando dados...")
def _carregar(hoje_iso: str):
    return carregar_dados()


@st.cache_data(show_spinner="Calculando sugestões...")
def _resultado(hoje_iso: str, semanas_min: int, max_lojas: int, janela: int):
    dados = _carregar(hoje_iso)
    return engine.calcular(dados, config.data_referencia(),
                           semanas_min=semanas_min, max_lojas=max_lojas, janela_dias=janela)


@st.cache_data(show_spinner="Calculando ruptura...")
def _rup_skus(hoje_iso: str):
    return engine.ruptura_skus(_carregar(hoje_iso))


dados = _carregar(hoje.isoformat())
res = _resultado(hoje.isoformat(), semanas_min, max_lojas, janela)
nec, doa, sug = res["necessidades"], res["doadoras"], res["sugestoes"]


def _excel_bytes(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        for nome, df in frames.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()


def _opcoes(df, col):
    if col not in df.columns:
        return []
    if col == "colecao":
        return config.colecoes_ordenadas(df[col])
    return sorted(x for x in df[col].dropna().unique() if str(x).strip())


def _filtra(df, col, label, container):
    sel = container.multiselect(label, _opcoes(df, col))
    return df[df[col].isin(sel)] if sel else df


aba_sug, aba_rup, aba_ve = st.tabs([
    "📦 Sugestões", "🚨 Ruptura (Dashboard)", "🧮 Painel Vendas × Estoque"])

# ---------------------------------------------------------------------------
with aba_sug:
    c1, c2, c3 = st.columns(3)
    c1.metric("Rupturas candidatas", len(nec))
    c2.metric("Pares doadores elegíveis", len(doa))
    c3.metric("Transferências sugeridas", len(sug))

    st.subheader("Sugestões")
    if sug.empty:
        st.info("Nenhuma transferência sugerida com os parâmetros atuais.")
    else:
        f1, f2, f3 = st.columns(3)
        f4, f5, f6 = st.columns(3)
        v = sug.copy()
        v = _filtra(v, "linha", "Linha", f1)
        v = _filtra(v, "grupo", "Grupo", f2)
        v = _filtra(v, "subgrupo", "Subgrupo", f3)
        v = _filtra(v, "colecao", "Coleção", f4)
        v = _filtra(v, "status", "Status do produto", f5)
        v = _filtra(v, "loja_receptora", "Loja receptora", f6)

        st.caption(f"{len(v)} de {len(sug)} sugestões")
        st.dataframe(v, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Baixar Excel (sugestões + detalhes)",
            data=_excel_bytes({"sugestoes": sug, "necessidades": nec, "doadoras": doa}),
            file_name="remanejamento.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        resumo = (sug.groupby("loja_doadora")
                  .agg(lojas_atendidas=("loja_receptora", "nunique"), pecas=("qtd", "sum"))
                  .reset_index().sort_values("pecas", ascending=False))
        st.subheader("Carga por loja doadora")
        st.dataframe(resumo, use_container_width=True, hide_index=True)

    with st.expander("Ver rupturas candidatas"):
        st.dataframe(nec, use_container_width=True, hide_index=True)
    with st.expander("Ver pares doadores elegíveis"):
        st.dataframe(doa, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
with aba_rup:
    st.subheader("Ruptura")
    rs = _rup_skus(hoje.isoformat())
    if rs.empty:
        st.info("Sem dados de ruptura.")
    else:
        g1, g2, g3, g4, g5 = st.columns(5)
        rf = rs.copy()
        rf = _filtra(rf, "linha", "Linha", g1)
        rf = _filtra(rf, "grupo", "Grupo", g2)
        rf = _filtra(rf, "subgrupo", "Subgrupo", g3)
        rf = _filtra(rf, "colecao", "Coleção", g4)
        rf = _filtra(rf, "status", "Status", g5)

        por_loja = engine.ruptura_por_loja(rf)
        tot = max(int(rf["sku_filho"].count()), 1)
        k1, k2, k3 = st.columns(3)
        k1.metric("% Ruptura Loja", f"{100*rf['ruptura'].sum()/tot:.1f}%")
        k2.metric("% Ruptura Loja + Trânsito", f"{100*rf['rup_sem_transito'].sum()/tot:.1f}%")
        k3.metric("% Sold Out CD", f"{100*rf['soldout_cd'].sum()/tot:.1f}%")

        st.caption("Ranking de lojas por % de ruptura (maior → menor).")
        chart = (alt.Chart(por_loja).mark_bar().encode(
            x=alt.X("%Ruptura Loja:Q", title="% Ruptura"),
            y=alt.Y("loja:N", sort="-x", title=None),
            tooltip=["loja", "%Ruptura Loja", "%Ruptura Loja+Trânsito", "%Sold Out CD", "sortimento"])
            .properties(height=28 * max(len(por_loja), 1) + 30))
        st.altair_chart(chart, use_container_width=True)

        st.dataframe(por_loja[["loja", "sortimento", "%Ruptura Loja",
                               "%Ruptura Loja+Trânsito", "%Sold Out CD"]],
                     use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Ruptura por subgrupo")
        lojas_op = ["Todas"] + sorted(rf["loja"].unique())
        loja_sel = st.selectbox("Loja", lojas_op)
        rsub = rf if loja_sel == "Todas" else rf[rf["loja"] == loja_sel]
        por_sub = engine.ruptura_por_subgrupo(rsub).head(25)
        chart2 = (alt.Chart(por_sub).mark_bar().encode(
            x=alt.X("%Ruptura Loja:Q", title="% Ruptura"),
            y=alt.Y("subgrupo:N", sort="-x", title=None),
            tooltip=["subgrupo", "%Ruptura Loja", "sortimento"])
            .properties(height=24 * max(len(por_sub), 1) + 30))
        st.altair_chart(chart2, use_container_width=True)
        st.dataframe(por_sub[["subgrupo", "sortimento", "%Ruptura Loja",
                              "%Ruptura Loja+Trânsito", "%Sold Out CD"]],
                     use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
with aba_ve:
    st.caption("Linhas = SKU pai • Colunas = loja. Célula: **QLF** (vendas) / **STK** (estoque) / "
               "**Dias** (desde o recebimento). Cor = peças vendidas.")
    op = painel.opcoes_filtro(dados)
    c = st.columns(5)
    filtros = {}
    rotulos = {"linha": "Linha", "grupo": "Grupo", "subgrupo": "Subgrupo",
               "colecao": "Coleção", "status": "Status"}
    for i, col in enumerate(["linha", "grupo", "subgrupo", "colecao", "status"]):
        filtros[col] = c[i].multiselect(rotulos[col], op.get(col, []))
    top_n = st.slider("Qtd. de SKUs pai (top por venda)", 10, 60, 25, step=5)

    html = painel.html_painel(dados, hoje, janela_dias=janela, filtros=filtros, top_n=top_n)
    if html is None:
        st.info("Sem dados para o filtro selecionado.")
    else:
        st.markdown(html, unsafe_allow_html=True)
