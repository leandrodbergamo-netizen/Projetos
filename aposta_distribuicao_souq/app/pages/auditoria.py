"""Auditoria — o que sustenta os números do simulador.

Quatro blocos: a aceleração de venda por loja (fator por filial que vale para
todas as apostas), a curva sazonal (com os marcos de Mães/BF/Natal), a cobertura
das bases (quanto do escopo tem material, foto, data de liquidação) e os de-paras
de material/cor/tamanho para validação do negócio.
"""
import pandas as pd
import streamlit as st

from app.dados_app import aceleracao_lojas, produtos_prep, salvar_aceleracao, vendas_fp
from core import aceleracao as acel
from core.dados import lojas_alvo_souq
from core.sazonalidade import curva_por, marcar_feriados

_COL_ACEL = "Aceleração (%)"
_CHAVE_EDITOR_ACEL = "aud_acel_editor"


def _pct(valor) -> int:
    """Percentual inteiro em [0, 300]; célula vazia/inválida volta a 100."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return acel.PCT_NEUTRO
    if v != v:          # NaN (célula apagada no editor)
        return acel.PCT_NEUTRO
    return int(round(min(max(v, acel.PCT_MIN), acel.PCT_MAX)))


def _aceleracao() -> None:
    st.subheader("Aceleração de venda por loja")
    st.caption("Quanto cada loja deve vender em relação ao próprio histórico: "
               "**100%** = igual ao histórico · **0%** = não vai vender nada (sai do "
               "parque e da matriz) · **120%** = cresce 20% em peças. Vale para **todas "
               "as apostas** — pondera a venda projetada (lojas-equivalentes) e a "
               f"participação no rateio. Fica salvo {acel.onde_grava()}.")
    atual = aceleracao_lojas()
    lojas = lojas_alvo_souq()
    if lojas.empty:
        st.markdown("_Nenhuma loja física ativa na base de lojas._")
        return
    lojas = lojas.assign(_nome=lojas["desc_nome"].astype(str)).sort_values("_nome")
    tab = pd.DataFrame({
        "sk": [str(float(x)) for x in lojas["sk_localidade"]],
        "Loja": lojas["_nome"].values,
        "Perfil": lojas["Perfil"].values if "Perfil" in lojas.columns else "",
        "Clima": lojas["Temperatura"].values if "Temperatura" in lojas.columns else "",
    })
    tab[_COL_ACEL] = [_pct(atual.get(sk, acel.PCT_NEUTRO)) for sk in tab["sk"]]
    n_ajust = int((tab[_COL_ACEL] != acel.PCT_NEUTRO).sum())

    a, b = st.columns([4, 1.3], vertical_alignment="bottom")
    a.caption(f"{len(tab)} lojas ativas · {n_ajust} com ajuste. Edite a coluna "
              f"**{_COL_ACEL}** — salva ao sair da célula.")
    if b.button("Voltar todas a 100%", width="stretch", key="aud_acel_reset",
                disabled=n_ajust == 0):
        with st.spinner("Salvando…"):
            salvar_aceleracao({})
        st.session_state.pop(_CHAVE_EDITOR_ACEL, None)
        st.toast("Aceleração zerada: todas as lojas em 100%.", icon="✅")
        st.rerun()

    editado = st.data_editor(
        tab, hide_index=True, width="stretch", key=_CHAVE_EDITOR_ACEL,
        height=min(38 + 35 * len(tab), 560),
        disabled=["Loja", "Perfil", "Clima"],
        column_config={
            "sk": None,
            "Loja": st.column_config.TextColumn("Loja", width="large"),
            _COL_ACEL: st.column_config.NumberColumn(
                _COL_ACEL, min_value=acel.PCT_MIN, max_value=acel.PCT_MAX, step=5,
                format="%d%%", help="100 = histórico · 0 = não vende · 120 = +20% em peças"),
        })
    novo = {sk: _pct(v) for sk, v in zip(editado["sk"], editado[_COL_ACEL])
            if _pct(v) != acel.PCT_NEUTRO}
    if novo != atual:
        with st.spinner("Salvando…"):
            salvar_aceleracao(novo)
        st.toast("Aceleração por loja salva.", icon="✅")
        st.rerun()   # contador e botão de reset refletem o salvo


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
    _aceleracao()
    st.divider()
    with st.spinner("Carregando bases…"):
        produtos_prep()
        vendas_fp()
    with st.spinner("Montando a curva sazonal…"):
        _curva()
    st.divider()
    with st.spinner("Medindo a cobertura das bases…"):
        _cobertura()
    st.divider()
    with st.spinner("Montando os de-paras…"):
        _deparas()
