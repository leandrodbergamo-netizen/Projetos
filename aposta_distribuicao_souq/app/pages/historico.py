"""Histórico — hub dos cenários de aposta salvos.

Cada aposta salva vira UM registro (a distribuição atualiza o mesmo registro).
Daqui: ver detalhes, DISTRIBUIR um cenário (a matriz abre nesta página),
exportar em CSV e apagar — um ou vários de uma vez.
"""
import pandas as pd
import streamlit as st

from app.pages import distribuicao
from core import historico, planilha
from core.config_utils import load_config
from core.dados import opcoes_perfil_clima
from core.taxonomia import ordem_tamanhos

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _hora_local(valores):
    """criado_em é gravado em UTC (a nuvem roda em UTC); exibe em Brasília."""
    dt = pd.to_datetime(valores, utc=True, errors="coerce")
    return dt.tz_convert("America/Sao_Paulo") if not hasattr(dt, "dt") \
        else dt.dt.tz_convert("America/Sao_Paulo")


def _linha_csv(row) -> dict:
    p = historico.normalizar_payload(row["payload"])
    ins, res = p.get("inputs", {}), p.get("resultado", {})
    return {
        "quando": _hora_local(row["criado_em"]).strftime("%d/%m/%Y %H:%M"),
        "cenario": row["resumo"],
        "sku_ref": ins.get("sku_ref", ""),
        "subgrupo": ins.get("subgrupo", ""),
        "tecido": ins.get("tecido", ""),
        "cores": ", ".join(ins.get("cores") or []),
        "grade": ", ".join(ins.get("grade") or []),
        "faixas": "/".join(ins.get("faixas") or []),
        "preco": ins.get("preco", ""),      # só payloads antigos (v1) têm preço
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
    payload = historico.normalizar_payload(payload)
    ins, res = payload.get("inputs", {}), payload.get("resultado", {})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Aposta sugerida", f"{res.get('aposta_sugerida', 0):.0f}")
    c2.metric("Venda projetada", f"{res.get('venda_projetada', 0):.0f}")
    c3.metric("Reserva CD", f"{res.get('reserva_cd', 0):.0f}")
    c4.metric("Semanas-equiv.", f"{res.get('semanas_equivalentes', 0):.1f}")
    if ins:
        ref = f"**SKU ref.:** {ins['sku_ref']} · " if ins.get("sku_ref") else ""
        st.write(f"{ref}**Entrada:** {ins.get('dt_entrada')} · **Coleção:** {ins.get('colecao')} · "
                 f"**Faixas:** {'/'.join(ins.get('faixas') or []) or '—'} · "
                 f"**Horizonte:** {ins.get('horizonte_semanas')} sem · "
                 f"**Aproveitamento:** {100 * float(ins.get('aproveitamento', 0)):.0f}% · "
                 f"**Grade:** {', '.join(ins.get('grade') or []) or '—'}")
    st.write("**Espelhos:** " + (", ".join(payload.get("espelhos", [])) or "—"))
    if payload.get("distribuicao_editada"):
        st.caption(f"Distribuição salva · aposta final **{payload.get('aposta_final', 0):.0f} un** · "
                   f"distribuído **{payload.get('distribuido_editado', 0)} un**")
        st.dataframe(pd.DataFrame(payload["distribuicao_editada"]).T, width="stretch")


def _importar(cen: pd.DataFrame, df_hist: pd.DataFrame) -> None:
    """Valida (all-or-nothing) e processa a planilha-mãe: rateia e grava cada
    cenário no Histórico (id vazio cria; preenchido atualiza)."""
    from app.dados_app import contexto_lojas, produtos_prep, vendas_fp

    with st.spinner("Validando a planilha…"):
        pp = produtos_prep()
        disp = opcoes_perfil_clima()
        ctx = {
            "subgrupos": set(pp["desc_sub_grupo_wbg"].dropna().unique()),
            "tecidos": set(pp["grupo_material"].dropna().unique()),
            "tamanhos": set(ordem_tamanhos()),
            "perfis": set(disp["perfis"]), "climas": set(disp["climas"]),
            "ids": set(df_hist["id"].astype(str)),
        }
        linhas, erros = planilha.validar(cen, ctx)
    if erros:
        st.error("**Nada foi gravado** — corrija a planilha e importe de novo:\n\n"
                 + "\n".join(f"- {e}" for e in erros))
        return

    fp = vendas_fp()
    cfg = {**load_config(), "ecom_locs": contexto_lojas()["ecom_locs"]}
    resumo_rows, falhas = [], 0
    prog = st.progress(0.0, text="Distribuindo cenários…")
    for i, linha in enumerate(linhas):
        try:
            payload, _ = planilha.montar_cenario(linha, pp, fp, cfg)
            if linha.get("id"):
                historico.atualizar(linha["id"], payload, resumo=payload["resumo"])
                acao = "atualizado"
            else:
                historico.salvar(payload["resumo"], payload)
                acao = "criado"
            resumo_rows.append({
                "Cenário": payload["resumo"], "Ação": acao,
                "Aposta final": int(round(payload["aposta_final"])),
                "Nas lojas": payload["distribuido_editado"],
                "Lojas": payload["parque"]["n_lojas_alvo"]})
        except Exception as erro:
            # a validação é all-or-nothing, mas a gravação é linha a linha
            # (rede/banco podem falhar no meio): reporta o que passou
            falhas += 1
            resumo_rows.append({"Cenário": f"linha {i + 2} da planilha",
                                "Ação": f"ERRO: {str(erro)[:120]}",
                                "Aposta final": None, "Nas lojas": None, "Lojas": None})
        prog.progress((i + 1) / len(linhas), text=f"{i + 1}/{len(linhas)} cenários")
    prog.empty()
    ok = len(linhas) - falhas
    st.session_state["import_resultado"] = pd.DataFrame(resumo_rows)
    st.session_state["flash_import"] = (f"{ok} cenário(s) gravado(s)"
                                        + (f" · {falhas} com erro" if falhas else "") + ".")
    st.rerun()


def _secao_importar(df_hist: pd.DataFrame) -> None:
    if st.session_state.get("flash_import"):
        st.success(st.session_state.pop("flash_import"))
        res = st.session_state.pop("import_resultado", None)
        if res is not None:
            st.dataframe(res, hide_index=True, width="stretch")
    with st.expander("Importar planilha-mãe (distribuição massiva)"):
        st.caption("Cada linha = um cenário completo com a **aposta já decidida**; o "
                   "app valida, grava no Histórico e roda só o rateio loja × tamanho. "
                   "Use o export Excel como modelo (a aba *leia-me* documenta cada "
                   "coluna). Qualquer erro bloqueia o import inteiro.")
        arquivo = st.file_uploader("Planilha (.xlsx)", type=["xlsx"], key="upload_planilha")
        if arquivo is None:
            return
        try:
            cen = pd.read_excel(arquivo, sheet_name="cenarios")
        except Exception as erro:
            st.error(f"Não consegui ler a aba 'cenarios': `{str(erro)[:150]}`")
            return
        st.caption(f"{len(cen)} linha(s) na aba 'cenarios'.")
        if st.button("Validar e processar", type="primary", key="btn_importar"):
            _importar(cen, df_hist)


def _secao_distribuir() -> None:
    """Seção de distribuição do registro aberto (st.session_state['registro_dist_id'])."""
    if st.session_state.get("flash_dist"):
        st.success(st.session_state.pop("flash_dist"))
    rid = st.session_state.get("registro_dist_id")
    if not rid:
        return
    with st.spinner("Lendo o cenário…"):
        reg = historico.obter(rid)
    if reg is None:
        st.session_state.pop("registro_dist_id", None)
        st.warning("O registro selecionado não existe mais no Histórico.")
        return
    st.divider()
    t1, t2 = st.columns([4.4, 1.3], vertical_alignment="center")
    t1.markdown(f"**Distribuindo:** {reg['resumo']}")
    if t2.button("Fechar distribuição", width="stretch"):
        st.session_state.pop("registro_dist_id", None)
        st.session_state.pop("distribuicao", None)
        st.rerun()
    distribuicao.secao(historico.normalizar_payload(reg["payload"]), reg["id"])


def render() -> None:
    st.title("Histórico de Apostas")
    st.caption("Cada aposta salva vira um registro. Marque **um** cenário para ver os "
               "detalhes e **Distribuir** (a matriz abre aqui embaixo e o salvar "
               "atualiza o mesmo registro); marque **vários** para exportar ou "
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

    if len(idx) == 1:
        sel = df.iloc[idx[0]]
        with st.expander("Detalhes do cenário", expanded=True):
            _detalhes(sel["payload"])
        if st.button("Distribuir", type="primary"):
            st.session_state.pop("distribuicao", None)
            st.session_state["registro_dist_id"] = sel["id"]
            st.rerun()

    if idx:
        b1, b2, b3 = st.columns(3)
        # sep=";" + decimal="," + BOM: abre direto no Excel brasileiro
        csv = (pd.DataFrame([_linha_csv(df.iloc[i]) for i in idx])
               .to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"))
        b1.download_button(f"Exportar selecionados ({len(idx)}) — CSV", csv,
                           file_name="historico_apostas.csv", mime="text/csv")
        xls = planilha.exportar(
            [{"id": str(df.iloc[i]["id"]),
              "payload": historico.normalizar_payload(df.iloc[i]["payload"])}
             for i in idx])
        b2.download_button(f"Exportar ({len(idx)}) — planilha-mãe (Excel)", xls,
                           file_name="planilha_mae_apostas.xlsx", mime=MIME_XLSX,
                           help="Mesma máscara do import: exporte, ajuste e importe "
                                "para distribuir em massa.")
        if b3.button(f"Excluir selecionados ({len(idx)})"):
            with st.spinner("Excluindo cenários…"):
                for i in idx:
                    historico.excluir(df.iloc[i]["id"])
            st.rerun()

    _secao_importar(df)
    _secao_distribuir()
