"""Histórico — cenários de aposta salvos, com reabertura na Distribuição.

Cada clique em "Projetar aposta" grava o cenário (inputs, espelhos, resultado e
os insumos da distribuição). Aqui dá para revisitar, reabrir, exportar em CSV e
apagar — um ou vários de uma vez.
"""
import pandas as pd
import streamlit as st

from core import historico


def _hora_local(valores):
    """criado_em é gravado em UTC (a nuvem roda em UTC); exibe em Brasília."""
    dt = pd.to_datetime(valores, utc=True, errors="coerce")
    return dt.tz_convert("America/Sao_Paulo") if not hasattr(dt, "dt") \
        else dt.dt.tz_convert("America/Sao_Paulo")


def _linha_csv(row) -> dict:
    p = row["payload"]
    ins, res = p.get("inputs", {}), p.get("resultado", {})
    return {
        "quando": _hora_local(row["criado_em"]).strftime("%d/%m/%Y %H:%M"),
        "cenario": row["resumo"],
        "sku_ref": ins.get("sku_ref", ""),
        "subgrupo": ins.get("subgrupo", ""),
        "tecido": ins.get("tecido", ""),
        "cores": ", ".join(ins.get("cores") or []),
        "grade": ", ".join(ins.get("grade") or []),
        "preco": ins.get("preco", ""),
        "faixa": ins.get("faixa", ""),
        "colecao": ins.get("colecao", ""),
        "dt_entrada": ins.get("dt_entrada", ""),
        "aproveitamento_pct": round(100 * float(ins.get("aproveitamento", 0))) if ins else "",
        "horizonte_semanas": ins.get("horizonte_semanas", ""),
        "venda_projetada": res.get("venda_projetada", ""),
        "venda_ecom": res.get("venda_ecom", ""),
        "aposta_sugerida": res.get("aposta_sugerida", p.get("aposta_total", "")),
        "reserva_cd": res.get("reserva_cd", ""),
        "semanas_equivalentes": res.get("semanas_equivalentes", ""),
        "espelhos": ", ".join(p.get("espelhos") or []),
    }


def _detalhes(payload: dict) -> None:
    ins, res = payload.get("inputs", {}), payload.get("resultado", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aposta sugerida", f"{res.get('aposta_sugerida', 0):.0f}")
    c2.metric("Venda projetada", f"{res.get('venda_projetada', 0):.0f}")
    c3.metric("Reserva CD", f"{res.get('reserva_cd', 0):.0f}")
    c4.metric("Semanas-equiv.", f"{res.get('semanas_equivalentes', 0):.1f}")
    if ins:
        ref = f"**SKU ref.:** {ins['sku_ref']} · " if ins.get("sku_ref") else ""
        st.write(f"{ref}**Entrada:** {ins.get('dt_entrada')} · **Coleção:** {ins.get('colecao')} · "
                 f"**Horizonte:** {ins.get('horizonte_semanas')} sem · "
                 f"**Aproveitamento:** {100 * float(ins.get('aproveitamento', 0)):.0f}% · "
                 f"**Grade:** {', '.join(ins.get('grade') or []) or '—'}")
    st.write("**Espelhos:** " + (", ".join(payload.get("espelhos", [])) or "—"))
    if payload.get("distribuicao_editada"):
        st.caption(f"Distribuição salva · aposta final **{payload.get('aposta_final', 0):.0f} un** · "
                   f"distribuído **{payload.get('distribuido_editado', 0)} un**")
        st.dataframe(pd.DataFrame(payload["distribuicao_editada"]).T, width="stretch")


def render() -> None:
    st.title("Histórico de Apostas")
    st.caption("Cada projeção fica registrada aqui. Marque **um** cenário para ver os "
               "detalhes e reabrir na Distribuição; marque **vários** para exportar ou "
               "excluir em lote.")

    try:
        with st.spinner("Lendo o histórico…"):
            df = historico.listar()
    except Exception as erro:
        st.error(f"Não consegui ler o histórico: `{str(erro)[:200]}`")
        return
    if df.empty:
        st.info("Nenhum cenário ainda. Projete uma aposta na aba **Nova Aposta** — "
                "ela aparece aqui automaticamente.")
        return

    sel_todos = st.checkbox("Selecionar todos", key="hist_sel_todos")
    tabela = pd.DataFrame({
        "Sel": sel_todos,
        "quando": _hora_local(df["criado_em"]).dt.strftime("%d/%m/%Y %H:%M"),
        "cenário": df["resumo"],
        "aposta": df["payload"].map(lambda p: round(p.get("aposta_total", 0))),
        "espelhos": df["payload"].map(lambda p: len(p.get("espelhos", []))),
    })
    # a chave muda com o toggle: o editor renasce com todas as linhas (des)marcadas,
    # e depois cada linha continua editável individualmente
    editado = st.data_editor(
        tabela, hide_index=True, width="stretch", key=f"editor_historico_{int(sel_todos)}",
        column_config={"Sel": st.column_config.CheckboxColumn("Sel", default=sel_todos)},
        disabled=[c for c in tabela.columns if c != "Sel"])
    idx = editado.index[editado["Sel"]].tolist()
    if not idx:
        return

    if len(idx) == 1:
        sel = df.iloc[idx[0]]
        with st.expander("Detalhes do cenário", expanded=True):
            _detalhes(sel["payload"])
        if st.button("Reabrir aposta + distribuição", type="primary"):
            payload = sel["payload"]
            st.session_state["projecao"] = {
                k: payload[k] for k in ("resumo", "aposta_total", "reserva_cd_pct",
                                        "participacoes_hist", "participacoes_espelhos",
                                        "curva_tamanhos", "velocidades_loja",
                                        "vel_media_loja", "espelhos", "suavizacao",
                                        "lojas_com_espelho_proprio", "inputs",
                                        "resultado", "avisos_projecao", "contribuicoes")
                if k in payload
            }
            st.session_state.pop("distribuicao", None)
            st.session_state["pagina"] = "Nova Aposta"
            st.session_state["etapa"] = 4      # direto na etapa de distribuição
            st.rerun()

    b1, b2 = st.columns(2)
    # sep=";" + decimal="," + BOM: abre direto no Excel brasileiro
    csv = (pd.DataFrame([_linha_csv(df.iloc[i]) for i in idx])
           .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
    b1.download_button(f"Exportar selecionados ({len(idx)}) — CSV", csv,
                       file_name="historico_apostas.csv", mime="text/csv")
    if b2.button(f"Excluir selecionados ({len(idx)})"):
        with st.spinner("Excluindo cenários…"):
            for i in idx:
                historico.excluir(df.iloc[i]["id"])
        st.rerun()
