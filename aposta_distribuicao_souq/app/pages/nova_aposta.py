"""Nova Aposta — simulador de reunião.

Fluxo: inputs do produto novo -> tabela de candidatos a espelho (com foto) ->
seleção -> projeção da aposta (velocidade desazonalizada + sazonalidade + Ecom)
-> envia participações/curva para a aba Distribuição.
"""
from datetime import date

import pandas as pd
import streamlit as st

from app.dados_app import contexto_lojas, opcoes, produtos_prep, vendas_fp
from core.config_utils import load_config
from core.dados import curva_tamanhos, participacao_lojas
from core.espelho import (candidatos_espelho, enriquecer_velocidade, projetar_aposta,
                          velocidade_por_loja_desaz)
from core.regra_distribuicao import participacao_com_loja_nova
from core.sazonalidade import curva_por
from core.taxonomia import faixa_preco

GRUPOS = ["TECIDO PLANO", "MALHA", "TRICOT", "JEANS"]
QUALQUER = "(qualquer)"


def _foto(url):
    u = str(url) if url is not None else ""
    return u if u.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else None


def render() -> None:
    st.title("Nova Aposta")
    st.caption("Selecione as características do produto novo, escolha os espelhos e projete a aposta.")

    cfg = load_config()
    pp = produtos_prep()
    fp = vendas_fp()
    ctx = contexto_lojas()

    # ------------------------------------------------------------------ inputs
    c1, c2, c3 = st.columns(3)
    with c1:
        subgrupo = st.selectbox("Subgrupo", opcoes("desc_sub_grupo_wbg"))
        grupo = st.selectbox("Grupo (construção)", GRUPOS)
    with c2:
        tecido = st.selectbox("Tecido (matéria-prima)", opcoes("grupo_material"))
        cor = st.selectbox("Cor", opcoes("cor_grupo"))
    with c3:
        preco = st.number_input("Preço sugerido (R$)", min_value=0.0, value=498.0, step=10.0)
        dt_entrada = st.date_input("Data de entrada em loja", value=date.today(),
                                   help="Premissa dt_envio + 7 dias; posiciona a janela sazonal.")

    with st.expander("Parâmetros"):
        p1, p2, p3, p4 = st.columns(4)
        horizonte = p1.number_input("Horizonte (semanas)", 4, 52, int(cfg.get("horizonte_semanas", 12)))
        aprov = p2.number_input("Aproveitamento", 0.3, 1.0, float(cfg.get("aproveitamento", 0.70)), 0.01)
        reserva_pct = p3.number_input("Reserva CD (%)", 0.0, 0.5, float(cfg.get("reserva_cd_pct", 0.20)), 0.01)
        grade_min = p4.number_input("Grade mínima (un/loja)", 0, 50, 3)

    faixa_info = faixa_preco(grupo, subgrupo, preco)
    fx = faixa_info["faixa"]
    st.info(f"Faixa de preço: **{fx or '—'}**  ·  MOQ: **{faixa_info.get('moq') or '—'}**  "
            f"·  lojas-alvo (Souq físicas ativas): **{ctx['n_lojas_alvo']}**")

    # -------------------------------------------------------------- candidatos
    cand, soft = candidatos_espelho(
        pp, subgrupo=subgrupo, grupo=grupo, faixa=fx, tecido=tecido,
        cor_grupo=cor if cor != QUALQUER else None,
        desde_colecao=float(cfg.get("desde_colecao", 2022.0)),
    )
    curva, nivel = curva_por(fp, subgrupo=subgrupo, material=tecido)

    if cand.empty:
        st.warning("Nenhum candidato a espelho com esses filtros. Afrouxe cor/tecido ou ajuste a faixa.")
        return

    cand = enriquecer_velocidade(cand, fp, curva, ctx["ecom_locs"])
    st.subheader(f"Candidatos a espelho ({len(cand)}) — curva sazonal: {nivel}")
    st.caption(
        f"Filtro de cor {'mantido' if soft else 'afrouxado (poucos candidatos)'}. "
        "Manga/comprimento/fit são apenas consulta — não filtram. Marque os espelhos a usar."
    )

    sel_todos = st.checkbox("Selecionar todos", value=False)
    tabela = pd.DataFrame({
        "Usar": sel_todos,
        "foto": cand["url"].map(_foto) if "url" in cand.columns else None,
        "desc_item": cand.get("desc_item"),
        "cod_sku_pai": cand["cod_sku_pai"],
        "coleção": cand.get("desc_colecao"),
        "cor": cand.get("cor_grupo"),
        "preço": cand.get("preco"),
        "manga": cand.get("desc_manga"),
        "comprimento": cand.get("desc_comprimento"),
        "fit": cand.get("desc_fit"),
        "unid_hist": cand["unidades"],
        "n_lojas": cand["n_lojas"],
        "vel/loja": cand["vel_loja_desaz"],
    })

    editado = st.data_editor(
        tabela, hide_index=True, width="stretch", key="editor_espelhos",
        column_config={
            "Usar": st.column_config.CheckboxColumn("Usar", default=False),
            "foto": st.column_config.ImageColumn("Foto"),
            "preço": st.column_config.NumberColumn("Preço", format="R$ %.0f"),
            "vel/loja": st.column_config.NumberColumn("Vel/loja", format="%.2f"),
        },
        disabled=[c for c in tabela.columns if c != "Usar"],
    )
    escolhidos = editado[editado["Usar"]]["cod_sku_pai"].tolist()

    # ---------------------------------------------------------------- projetar
    if st.button("Projetar aposta", type="primary", disabled=not escolhidos):
        vels = [velocidade_por_loja_desaz(fp, s, curva, ctx["ecom_locs"]) for s in escolhidos]
        vels = [v for v in vels if v]
        if not vels:
            st.error("Os espelhos escolhidos não têm histórico de venda no escopo Souq.")
            return
        ap = projetar_aposta(vels, curva, pd.Timestamp(dt_entrada), ctx["n_lojas_alvo"],
                             horizonte_semanas=int(horizonte), aproveitamento=aprov,
                             reserva_cd_pct=reserva_pct, moq=faixa_info.get("moq"))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Venda projetada", f"{ap.venda_projetada:.0f}")
        m2.metric("Aposta sugerida", f"{ap.aposta_sugerida:.0f}")
        m3.metric("Reserva CD", f"{ap.reserva_cd:.0f}")
        m4.metric("Semanas-equiv.", f"{ap.semanas_equivalentes:.1f}")
        for aviso in ap.avisos:
            st.warning(aviso)

        # participações (com loja nova) + curva de tamanhos p/ a aba Distribuição
        skus = [v.cod_sku_pai for v in vels]
        fp_esp_fisico = fp[fp["cod_sku_pai"].isin(skus) & ~fp["sk_localidade"].isin(ctx["ecom_locs"])]
        part = participacao_com_loja_nova(
            participacao_lojas(fp_esp_fisico), ctx["lojas_alvo"], ctx["cluster_por_loja"])
        curva_tam = curva_tamanhos(fp[fp["cod_sku_pai"].isin(skus)],
                                   produtos_prep(), col_tamanho="desc_tamanho")

        st.session_state["projecao"] = {
            "resumo": f"{subgrupo}/{grupo}/{tecido}/{cor} · R${preco:.0f} · faixa {fx}",
            "aposta_total": ap.aposta_sugerida,
            "reserva_cd_pct": reserva_pct,
            "grade_minima": grade_min,
            "participacoes": part,
            "curva_tamanhos": curva_tam,
            "espelhos": skus,
        }
        st.success("Projeção pronta. Abra a aba **Distribuição** para ver a matriz loja × tamanho.")
