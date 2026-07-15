"""Distribuição — matriz loja × tamanho.

Dois modos:
- "Da projeção": usa a aposta/participações/curva calculadas na aba Nova Aposta
  (participação já com lojas novas extrapoladas por Cluster; Ecom fora da matriz).
- "Manual": entrada avulsa de participações e curva, para simulações rápidas.
"""
import pandas as pd
import streamlit as st

from core.config_utils import load_config
from core.regra_distribuicao import distribuir


def _mostra_resultado(resultado):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Reserva CD", f"{resultado.reserva_cd:.0f}")
    m2.metric("Disponível lojas", f"{resultado.disponivel_lojas:.0f}")
    m3.metric("Distribuído", f"{resultado.total_distribuido()}")
    m4.metric("Sobra p/ CD", f"{resultado.sobra_para_cd}")
    for aviso in resultado.avisos:
        st.info(aviso)
    st.subheader("Matriz loja × tamanho")
    matriz = pd.DataFrame(resultado.matriz).T.fillna(0).astype(int)
    if not matriz.empty:
        matriz["TOTAL"] = matriz.sum(axis=1)
        matriz = matriz.sort_values("TOTAL", ascending=False)
    st.dataframe(matriz, width="stretch")
    st.session_state["ultima_distribuicao"] = matriz


def _da_projecao():
    proj = st.session_state.get("projecao")
    if not proj:
        st.info("Nenhuma projeção ainda. Vá à aba **Nova Aposta**, escolha os espelhos e clique em "
                "**Projetar aposta**.")
        return
    st.write(f"Projeção atual: **{proj['resumo']}**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Aposta total", f"{proj['aposta_total']:.0f}")
    c2.metric("Lojas-alvo", f"{len(proj['participacoes'])}")
    c3.metric("Espelhos", f"{len(proj['espelhos'])}")
    grade = st.number_input("Grade mínima (un/loja)", 0, 50, int(proj.get("grade_minima", 3)))
    if st.button("Distribuir projeção", type="primary"):
        resultado = distribuir(
            aposta_total=proj["aposta_total"],
            participacoes=proj["participacoes"],
            curva_tamanhos=proj["curva_tamanhos"],
            reserva_cd_pct=proj.get("reserva_cd_pct", 0.20),
            grade_minima=grade,
        )
        _mostra_resultado(resultado)


def _manual():
    cfg = load_config()
    col1, col2 = st.columns(2)
    with col1:
        aposta_total = st.number_input("Aposta total (unidades)", min_value=0.0, value=1000.0, step=10.0)
        reserva_cd_pct = st.slider("Reserva CD (%)", 0.0, 0.5, float(cfg.get("reserva_cd_pct", 0.20)), 0.01)
    with col2:
        grade_minima = st.number_input("Grade mínima (unidades/loja)", min_value=0.0, value=0.0, step=1.0)

    st.caption("Participação histórica (não precisa somar 1).")
    lojas_default = pd.DataFrame({"loja": ["Loja 1", "Loja 2", "Loja 3"],
                                  "participacao": [0.5, 0.3, 0.2]})
    lojas_df = st.data_editor(lojas_default, num_rows="dynamic", key="lojas_editor", width="stretch")
    curva_default = pd.DataFrame({"tamanho": ["P", "M", "G", "GG"], "peso": [1.0, 2.0, 2.0, 1.0]})
    curva_df = st.data_editor(curva_default, num_rows="dynamic", key="curva_editor", width="stretch")

    if st.button("Distribuir", type="primary", key="dist_manual"):
        participacoes = {str(r["loja"]): float(r["participacao"]) for _, r in lojas_df.iterrows()
                         if str(r.get("loja", "")).strip() and float(r.get("participacao", 0) or 0) > 0}
        curva = {str(r["tamanho"]): float(r["peso"]) for _, r in curva_df.iterrows()
                 if str(r.get("tamanho", "")).strip()}
        if not participacoes:
            st.error("Informe ao menos uma loja com participação > 0.")
            return
        _mostra_resultado(distribuir(aposta_total, participacoes, curva,
                                     reserva_cd_pct=reserva_cd_pct, grade_minima=grade_minima))


def render() -> None:
    st.title("Distribuição")
    st.caption("Reserva CD · participação por loja (com loja nova por Cluster) · grade mínima · "
               "abertura por tamanho. Ecom entra na aposta, mas não na matriz física.")
    tab_proj, tab_manual = st.tabs(["Da projeção", "Manual"])
    with tab_proj:
        _da_projecao()
    with tab_manual:
        _manual()
