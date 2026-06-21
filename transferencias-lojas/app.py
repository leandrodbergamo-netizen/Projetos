"""App Streamlit: sugestões de remanejamento entre lojas + painel loja x SKU."""
from __future__ import annotations

import io

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
    help="Item só pode ser retirado da loja se está parado há pelo menos N semanas desde o recebimento.")
max_lojas = st.sidebar.number_input(
    "Máx. lojas atendidas por doadora", min_value=1, max_value=20,
    value=config.MAX_LOJAS_POR_DOADORA)
janela = st.sidebar.number_input(
    "Janela de vendas (dias)", min_value=15, max_value=365,
    value=config.JANELA_VENDAS_DIAS,
    help="Janela usada para medir a probabilidade de venda (venda histórica do SKU pai).")

st.sidebar.divider()
st.sidebar.caption("**Limite de peças por grupo (SKU filho):**")
for g, lim in config.GRUPO_LIMITES.items():
    st.sidebar.caption(f"• {g}: até {lim}")


@st.cache_data(show_spinner="Carregando dados...")
def _carregar(hoje_iso: str):
    return carregar_dados()


dados = _carregar(hoje.isoformat())
res = engine.calcular(dados, hoje, semanas_min=semanas_min,
                      max_lojas=max_lojas, janela_dias=janela)
nec, doa, sug = res["necessidades"], res["doadoras"], res["sugestoes"]


def _excel_bytes(frames: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
        for nome, df in frames.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()


aba_sug, aba_painel = st.tabs(["📦 Sugestões de Remanejamento", "📊 Painel Loja × SKU"])

with aba_sug:
    c1, c2, c3 = st.columns(3)
    c1.metric("Rupturas candidatas", len(nec))
    c2.metric("Pares doadores elegíveis", len(doa))
    c3.metric("Transferências sugeridas", len(sug))

    st.subheader("Sugestões")
    if sug.empty:
        st.info("Nenhuma transferência sugerida com os parâmetros atuais.")
    else:
        fg, fl = st.columns([1, 2])
        g_sel = fg.selectbox("Filtrar grupo", ["Todos"] + sorted(sug["grupo"].unique()))
        lojas_rec = sorted(sug["loja_receptora"].unique())
        l_sel = fl.multiselect("Filtrar loja receptora", lojas_rec)
        sug_view = sug.copy()
        if g_sel != "Todos":
            sug_view = sug_view[sug_view["grupo"] == g_sel]
        if l_sel:
            sug_view = sug_view[sug_view["loja_receptora"].isin(l_sel)]
        st.caption(f"{len(sug_view)} de {len(sug)} sugestões")
        st.dataframe(sug_view, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Baixar Excel (sugestões + detalhes)",
            data=_excel_bytes({"sugestoes": sug, "necessidades": nec, "doadoras": doa}),
            file_name="remanejamento.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # Resumo de carga por loja doadora (verifica o teto de 4 lojas).
        resumo = (sug.groupby("loja_doadora")
                  .agg(lojas_atendidas=("loja_receptora", "nunique"),
                       pecas=("qtd", "sum"))
                  .reset_index().sort_values("pecas", ascending=False))
        st.subheader("Carga por loja doadora")
        st.dataframe(resumo, use_container_width=True, hide_index=True)

    with st.expander("Ver rupturas candidatas (lojas que precisam receber)"):
        st.dataframe(nec, use_container_width=True, hide_index=True)
    with st.expander("Ver pares doadores elegíveis (estoque parado ≥ N semanas)"):
        st.dataframe(doa, use_container_width=True, hide_index=True)

with aba_painel:
    st.caption("Linhas = lojas • Colunas = SKU pai. Verde = melhor; vermelho = pior.")
    f1, f2 = st.columns([1, 1])
    grupo_sel = f1.selectbox("Grupo", ["Todos", "Home", "Acessórios", "Roupa"])
    top_n = f2.slider("Qtd. de SKUs pai (top por venda)", 10, 80, 30, step=5,
                      help="Há milhares de SKUs pai; mostramos os de maior venda na janela.")

    pivot_est, pivot_vend, giro = painel.montar_matrizes(
        dados, hoje, janela_dias=janela, grupo=grupo_sel, top_n=top_n)

    if pivot_est.empty:
        st.info("Sem dados para o filtro selecionado.")
    else:
        st.subheader("Giro de estoque (vendas ÷ estoque)")
        st.caption("Identifica as lojas com melhor giro — quanto maior, mais verde.")
        st.dataframe(painel.estilizar_giro(giro), use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("Estoque (peças)")
            st.dataframe(painel.estilizar(pivot_est), use_container_width=True)
        with col_b:
            st.subheader(f"Vendas — últimos {janela} dias (peças)")
            st.dataframe(painel.estilizar(pivot_vend), use_container_width=True)
