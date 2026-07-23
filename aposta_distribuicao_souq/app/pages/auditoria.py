"""Auditoria — o que sustenta os números do simulador.

Três blocos: a curva sazonal (com os marcos de Mães/BF/Natal), a cobertura das
bases (quanto do escopo tem material, foto, data de liquidação) e os de-paras de
material/cor/tamanho para validação do negócio.
"""
import pandas as pd
import streamlit as st

from app.dados_app import produtos_prep, vendas_fp
from core.sazonalidade import curva_por, marcar_feriados


def _curva() -> None:
    st.subheader("Curva sazonal semanal")
    st.caption("Índice por semana ISO (100 = semana média), por loja ativa. É o que "
               "desazonaliza os espelhos e re-sazonaliza a projeção.")
    pp, fp = produtos_prep(), vendas_fp()

    c1, c2 = st.columns(2)
    subgrupos = ["(geral)"] + sorted(fp["subgrupo"].dropna().unique().tolist())
    sg = c1.selectbox("Subgrupo", subgrupos)
    tecidos = ["(geral)"] + sorted(fp["grupo_material"].dropna().unique().tolist())
    tc = c2.selectbox("Tecido", tecidos)

    curva, nivel = curva_por(fp, subgrupo=None if sg == "(geral)" else sg,
                             material=None if tc == "(geral)" else tc)
    anos = tuple(sorted(fp["dt_transacao"].dt.year.dropna().unique().astype(int)))
    curva = marcar_feriados(curva, anos)

    st.caption(f"Nível usado (fallback automático por amostra): **{nivel}**")
    base = curva.set_index("semana")[["indice"]]
    st.line_chart(base, height=260)

    marcos = curva[(curva["feriado"] != "") | (curva["temporada"] != "")]
    with st.expander("Semanas com feriado/temporada"):
        st.dataframe(
            marcos[["semana", "indice", "feriado", "temporada", "tem_emenda"]]
            .assign(indice=lambda d: d["indice"].round(0)),
            width="stretch", hide_index=True)


def _cobertura() -> None:
    st.subheader("Cobertura das bases")
    pp, fp = produtos_prep(), vendas_fp()
    esc = pp[pp["rank_colecao"] >= 2022].drop_duplicates("cod_sku_pai")

    tem_foto = esc["url"].fillna("").str.lower().str.endswith((".jpg", ".jpeg", ".png", ".webp"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Modelos no escopo", f"{len(esc):,}".replace(",", "."))
    m2.metric("Com tecido definido", f"{100 * (esc['grupo_material'] != 'Outros').mean():.0f}%")
    m3.metric("Com foto", f"{100 * tem_foto.mean():.0f}%")
    m4.metric("Com data de liquidação", f"{100 * esc['dt_liquidacao'].notna().mean():.0f}%")

    vendas_ano = fp.groupby(fp["dt_transacao"].dt.year)["qtd_produto"].sum()
    vendas_ano.index = vendas_ano.index.astype(int).astype(str)
    st.caption("Unidades full price no escopo Souq, por ano:")
    st.bar_chart(vendas_ano, height=180)


def _deparas() -> None:
    st.subheader("De-paras (validáveis pelo negócio)")
    st.caption("Editáveis em `config/*.yaml`. O que estiver estranho aqui é ajuste de "
               "uma linha no arquivo — não de código.")
    pp = produtos_prep()
    esc = pp[pp["rank_colecao"] >= 2022]

    t1, t2, t3 = st.tabs(["Tecido", "Cor", "Tamanho"])
    with t1:
        vc = esc.groupby("grupo_material")["cod_sku_pai"].nunique().sort_values(ascending=False)
        st.dataframe(vc.rename("modelos"), width="stretch")
        outros = esc[esc["grupo_material"] == "Outros"]["desc_material"].value_counts(dropna=False)
        with st.expander(f"O que caiu em 'Outros' ({int(outros.sum())} itens)"):
            st.dataframe(outros.rename("itens").head(30), width="stretch")
    with t2:
        vc = (esc.groupby(["cor_grupo", "desc_cor"])["cod_sku_pai"].nunique()
              .rename("modelos").reset_index()
              .sort_values(["cor_grupo", "modelos"], ascending=[True, False]))
        st.dataframe(vc, width="stretch", hide_index=True, height=350)
    with t3:
        vc = (esc.groupby(["tamanho_grupo", "desc_tamanho"])["sk_produto"].count()
              .rename("itens").reset_index()
              .sort_values(["tamanho_grupo", "itens"], ascending=[True, False]))
        st.dataframe(vc, width="stretch", hide_index=True, height=350)
        sem = esc[esc["tamanho_grupo"].isna()]["desc_tamanho"].value_counts()
        if len(sem):
            st.warning("Tamanhos sem bucket (ajustar `config/tamanhos.yaml`): "
                       + ", ".join(f"{t} ({n})" for t, n in sem.items()))


def render() -> None:
    st.title("Auditoria")
    with st.spinner("Carregando bases…"):
        produtos_prep()
        vendas_fp()
    _curva()
    st.divider()
    _cobertura()
    st.divider()
    _deparas()
