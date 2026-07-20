"""Histórico — cenários de aposta salvos, com reabertura na Distribuição.

Cada clique em "Projetar aposta" grava o cenário (inputs, espelhos, resultado e
os insumos da distribuição). Aqui dá para revisitar, comparar, reabrir e apagar.
"""
import pandas as pd
import streamlit as st

from core import historico


def render() -> None:
    st.title("Histórico de Apostas")
    st.caption("Cada projeção fica registrada aqui. Reabra um cenário para rodar a "
               "distribuição dele, ou exclua o que virou ruído.")

    try:
        df = historico.listar()
    except Exception as erro:
        st.error(f"Não consegui ler o histórico: `{str(erro)[:200]}`")
        return
    if df.empty:
        st.info("Nenhum cenário ainda. Projete uma aposta na aba **Nova Aposta** — "
                "ela aparece aqui automaticamente.")
        return

    tabela = pd.DataFrame({
        "quando": pd.to_datetime(df["criado_em"]).dt.strftime("%d/%m/%Y %H:%M"),
        "cenário": df["resumo"],
        "aposta": df["payload"].map(lambda p: round(p.get("aposta_total", 0))),
        "espelhos": df["payload"].map(lambda p: len(p.get("espelhos", []))),
        "id": df["id"],
    })
    st.dataframe(tabela.drop(columns=["id"]), width="stretch", hide_index=True)

    rotulos = [f"{q} — {c}" for q, c in zip(tabela["quando"], tabela["cenário"])]
    escolha = st.selectbox("Cenário", rotulos, index=0)
    sel = df.iloc[rotulos.index(escolha)]
    payload = sel["payload"]

    with st.expander("Detalhes do cenário", expanded=True):
        ins, res = payload.get("inputs", {}), payload.get("resultado", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Aposta sugerida", f"{res.get('aposta_sugerida', 0):.0f}")
        c2.metric("Venda projetada", f"{res.get('venda_projetada', 0):.0f}")
        c3.metric("Reserva CD", f"{res.get('reserva_cd', 0):.0f}")
        c4.metric("Semanas-equiv.", f"{res.get('semanas_equivalentes', 0):.1f}")
        if ins:
            st.write(f"**Entrada:** {ins.get('dt_entrada')} · **Coleção:** {ins.get('colecao')} · "
                     f"**Horizonte:** {ins.get('horizonte_semanas')} sem · "
                     f"**Aproveitamento:** {100 * float(ins.get('aproveitamento', 0)):.0f}% · "
                     f"**Grade:** {', '.join(ins.get('grade') or []) or '—'}")
        st.write("**Espelhos:** " + (", ".join(payload.get("espelhos", [])) or "—"))

    b1, b2 = st.columns(2)
    if b1.button("Reabrir na Distribuição", type="primary"):
        st.session_state["projecao"] = {
            k: payload[k] for k in ("resumo", "aposta_total", "reserva_cd_pct",
                                    "participacoes_hist", "curva_tamanhos",
                                    "velocidades_loja", "espelhos")
            if k in payload
        }
        st.session_state["pagina"] = "Distribuição"
        st.rerun()
    if b2.button("Excluir cenário"):
        historico.excluir(sel["id"])
        st.rerun()
